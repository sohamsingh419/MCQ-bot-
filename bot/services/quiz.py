"""Question selection and safe Telegram native-quiz delivery."""
from __future__ import annotations

import asyncio
import logging

from bot.services.question_validator import normalize_text
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import IntegrityError
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import PollType
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError, TimedOut

from bot.config import QUESTION_LANGUAGE, Settings, UNIFIED_EXAM_LEVEL, default_subjects_for_state, get_settings, subjects_for_state, syllabus_topics_for
from bot.database.database import Database
from bot.database.models import GroupSettings, Question
from bot.database.repositories import Repository
from bot.services.ai_generator import AIQuestionGenerator, AIQuestionGenerationError, question_types_for_difficulty
from bot.services.question_validator import ValidQuestion, is_structurally_complete, source_evidence_supports_question

logger = logging.getLogger(__name__)

_SOURCE_TOPIC_STOPWORDS = {"state", "india", "and", "the", "of", "for", "के", "का", "की", "और"}
def _topic_relevant_source_chunks(chunks: list, topic: str, limit: int = 3) -> list:
    terms = {
        token for token in normalize_text(topic).split()
        if len(token) >= 4 and token not in _SOURCE_TOPIC_STOPWORDS
    }
    if not terms:
        return []
    ranked = []
    for chunk in chunks:
        haystack = normalize_text(f"{chunk.topic} {chunk.text}")
        score = sum(1 for term in terms if term in haystack)
        if score:
            ranked.append((score, -chunk.chunk_index, chunk))
    ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked[:limit]]


class NoFreshQuestionAvailable(AIQuestionGenerationError):
    """No unseen question is available for the requested chat scope."""


# Conservative visual limits for the single-message native-poll layout. The
# validator still allows larger source text; those questions use the long form.
SHORT_POLL_QUESTION_MAX = 105
SHORT_POLL_OPTION_MAX = 48
SHORT_POLL_OPTIONS_TOTAL_MAX = 170


class QuizService:
    def __init__(self, bot: Bot, database: Database, settings: Settings, generator: AIQuestionGenerator) -> None:
        self.bot = bot
        self.database = database
        self.settings = settings
        self.generator = generator
        self._group_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    @staticmethod
    def preferred_question_source(settings: GroupSettings) -> str:
        """Return the source requested for the next delivery; new chats start with AI."""
        return settings.source_mode if settings.source_mode in {"ai", "source"} else "ai"

    @staticmethod
    def next_question_source(delivered_source: str) -> str:
        """Return the preferred source after a successfully delivered question."""
        return "ai" if delivered_source == "source" else "source"

    @staticmethod
    def subject_for_next_quiz(settings: GroupSettings) -> str:
        allowed = set(subjects_for_state(settings.state))
        subjects = [subject for subject in (settings.subjects or []) if subject in allowed]
        if not subjects:
            subjects = default_subjects_for_state(settings.state)
        return subjects[settings.current_rotation_index % len(subjects)]

    @staticmethod
    def topic_for_next_quiz(settings: GroupSettings, subject: str) -> str:
        topics = syllabus_topics_for(settings.state, subject)
        topic_state = settings.topic_rotation_state or {}
        return topics[int(topic_state.get(subject, 0)) % len(topics)]

    @staticmethod
    def advance_topic(settings: GroupSettings, subject: str) -> None:
        topic_state = dict(settings.topic_rotation_state or {})
        topic_state[subject] = int(topic_state.get(subject, 0)) + 1
        settings.topic_rotation_state = topic_state

    async def _question_for_settings(
        self, repo: Repository, settings: GroupSettings, exclude_question_ids: set[int] | None = None,
        question_type_index: int | None = None,
    ) -> Question:
        allowed_subjects = set(subjects_for_state(settings.state))
        subjects = [item for item in (settings.subjects or []) if item in allowed_subjects]
        if not subjects:
            subjects = default_subjects_for_state(settings.state)
        subject = self.subject_for_next_quiz(settings)
        topic = self.topic_for_next_quiz(settings, subject)
        preferred_source = self.preferred_question_source(settings)
        source_chunk = None
        source_context = None
        source_title = None
        source_chunks = []
        if preferred_source == "source":
            source_chunks = await repo.source_chunks_for_scope(state=settings.state, subject=subject, topic=topic, limit=3)
            if not source_chunks:
                candidates = await repo.source_chunks_for_scope(state=settings.state, subject=subject, limit=50)
                source_chunks = _topic_relevant_source_chunks(candidates, topic)
                # A PDF can cover the selected subject without using the exact same
                # wording as the hidden syllabus topic. In that case, still use a
                # rotating subject-level chunk rather than silently switching to AI-only mode.
                if not source_chunks and candidates:
                    start = settings.current_rotation_index % len(candidates)
                    source_chunks = [candidates[(start + offset) % len(candidates)] for offset in range(min(3, len(candidates)))]
        if source_chunks:
            source_chunk = source_chunks[settings.current_rotation_index % len(source_chunks)]
            source_context = "\n\n".join(
                f"[Source chunk, pages {chunk.page_start}-{chunk.page_end}]\n{chunk.text}" for chunk in source_chunks
            )
            source_document = await repo.get_source_document(source_chunk.document_id)
            source_title = source_document.title if source_document else None
        question_types = question_types_for_difficulty(UNIFIED_EXAM_LEVEL, subject=subject)
        if question_type_index is not None:
            question_type = question_types[question_type_index % len(question_types)]
        else:
            question_type = question_types[settings.current_rotation_index % len(question_types)]
        query_source = "source" if preferred_source == "source" else "non-source"
        cached = await repo.list_questions_for_scope(
            settings.state, [subject], UNIFIED_EXAM_LEVEL, 1, language=QUESTION_LANGUAGE, topic=topic,
            exclude_question_ids=exclude_question_ids, source=query_source,
            question_type=question_type,
        )
        if not cached and preferred_source == "source":
            cached = await repo.list_questions_for_scope(
                settings.state, [subject], UNIFIED_EXAM_LEVEL, 1, language=QUESTION_LANGUAGE,
                exclude_question_ids=exclude_question_ids, source="source",
            )
        if cached:
            cached_question = cached[0]
            if not is_structurally_complete(cached_question.question_type, cached_question.question_text):
                logger.warning("Skipping cached question %s because its structured stem is incomplete", cached_question.id)
            elif source_chunk and source_context and not source_evidence_supports_question(cached_question, source_context):
                logger.warning("Skipping cached source question %s because its answer is not evidenced by the current PDF context", cached_question.id)
            else:
                return cached_question
        previous = await repo.similar_question_texts(settings.state, subject, language=QUESTION_LANGUAGE)
        try:
            generated = await self.generator.generate(
                state=settings.state, subject=subject, topic=topic, question_type=question_type,
                language=QUESTION_LANGUAGE, previous_questions=previous,
                similarity_threshold=self.settings.question_similarity_threshold, source_context=source_context,
            )
            if source_chunk and (not source_context or not source_evidence_supports_question(generated, source_context)):
                logger.warning(
                    "PDF evidence guard rejected generated MCQ for %s/%s/%s; answer=%r",
                    settings.state, subject, topic, generated.options[generated.correct_option],
                )
                raise AIQuestionGenerationError("Generated answer is not evidenced by the selected PDF source")
            try:
                return await repo.add_question(
                    question_text=generated.question, options=generated.options, correct_option=generated.correct_option,
                    explanation=generated.explanation, key_point=generated.key_point, state=settings.state,
                    subject=generated.subject, topic=generated.topic, difficulty=UNIFIED_EXAM_LEVEL,
                    question_type=generated.question_type, language=generated.language,
                    source="source" if source_chunk else "ai", source_group_id=settings.group_id, ai_model=self.settings.ai_model,
                    source_document_id=source_chunk.document_id if source_chunk else None,
                    source_title=source_title,
                    source_page_start=source_chunk.page_start if source_chunk else None,
                    source_page_end=source_chunk.page_end if source_chunk else None,
                )
            except IntegrityError as exc:
                raise AIQuestionGenerationError("Generated question collided with an existing question; please retry") from exc
        except AIQuestionGenerationError as exc:
            fallback = await repo.fallback_question_for_scope(
                settings.state, subjects, language=QUESTION_LANGUAGE, topic=topic,
                exclude_question_ids=exclude_question_ids, source=query_source, question_type=question_type,
            )
            if fallback is None:
                fallback = await repo.fallback_question_for_scope(
                    settings.state, subjects, language=QUESTION_LANGUAGE,
                    exclude_question_ids=exclude_question_ids, source=query_source, question_type=question_type,
                )
            opposite_source = "source" if preferred_source == "ai" else "non-source"
            if fallback is None and question_type:
                # Prefer the requested mock type, but do not stall a live test
                # when the pool has no item of that type. Exclusions still
                # prevent repetition; the fallback is only a final resort.
                fallback = await repo.fallback_question_for_scope(
                    settings.state, subjects, language=QUESTION_LANGUAGE,
                    exclude_question_ids=exclude_question_ids, source=query_source,
                )
                if fallback is not None:
                    logger.warning(
                        "Mock type %s unavailable for chat %s; using a different stored type %s",
                        question_type, settings.group_id, fallback.question_type,
                    )
            if fallback is None:
                # If the preferred side is empty, use the opposite source once;
                # the cursor will remain on the unavailable side after delivery.
                fallback = await repo.fallback_question_for_scope(
                    settings.state, subjects, language=QUESTION_LANGUAGE, topic=topic,
                    exclude_question_ids=exclude_question_ids, source=opposite_source,
                )
            if fallback is None and opposite_source:
                fallback = await repo.fallback_question_for_scope(
                    settings.state, subjects, language=QUESTION_LANGUAGE,
                    exclude_question_ids=exclude_question_ids, source=opposite_source,
                )
            if fallback is not None and not is_structurally_complete(fallback.question_type, fallback.question_text):
                logger.warning("Skipping fallback question %s because its structured stem is incomplete", fallback.id)
                fallback = None
            if fallback is not None:
                logger.warning(
                    "AI generation unavailable for chat %s; using stored question %s instead: %s",
                    settings.group_id, fallback.id, exc,
                )
                return fallback
            raise NoFreshQuestionAvailable(
                f"No unseen question is available for {settings.state}/{subject} at the unified Exam level"
            ) from exc

    @staticmethod
    def explanation_labels(language: str) -> dict[str, str]:
        if language == "Hindi":
            return {"answer": "सही उत्तर", "explanation": "व्याख्या", "key_point": "मुख्य बिंदु"}
        return {"answer": "Correct Answer", "explanation": "Explanation", "key_point": "Key Point"}

    @staticmethod
    def uses_single_poll_layout(question: Question) -> bool:
        """Return whether the question and all four options fit comfortably together."""
        if getattr(question, "question_type", None) in {"Statement-based", "Multiple-statement", "Assertion-Reason", "Match-the-following"}:
            return False
        question_length_ok = len(question.question_text) <= SHORT_POLL_QUESTION_MAX
        options_length_ok = max((len(option) for option in question.options), default=0) <= SHORT_POLL_OPTION_MAX
        options_total_ok = sum(len(option) for option in question.options) <= SHORT_POLL_OPTIONS_TOTAL_MAX
        return question_length_ok and options_length_ok and options_total_ok

    @staticmethod
    def poll_content(
        question: Question,
        ui_language: str | None = None,
        mock_progress: tuple[int, int] | None = None,
    ) -> tuple[str, list[str]]:
        """Use full content for short items and add visible progress only for mock tests."""
        if QuizService.uses_single_poll_layout(question):
            prefix = f"[{mock_progress[0]}/{mock_progress[1]}] " if mock_progress else ""
            return prefix + question.question_text, list(question.options)
        if (ui_language or question.language) == "Hindi":
            return "सही उत्तर चुनें", ["A", "B", "C", "D"]
        return "Choose the correct answer", ["A", "B", "C", "D"]

    @staticmethod
    def full_question_card(
        question: Question,
        ui_language: str | None = None,
        mock_progress: tuple[int, int] | None = None,
    ) -> str:
        """Show question content with selected UI labels and optional mock progress."""
        is_matching = getattr(question, "question_type", None) == "Match-the-following"
        interface_language = ui_language or question.language
        if mock_progress:
            progress = f"[{mock_progress[0]}/{mock_progress[1]}]"
            heading = f"🎲 {'मॉक टेस्ट' if interface_language == 'Hindi' else 'MOCK TEST'} • {progress}"
            instruction = (
                "कॉलम A के प्रत्येक item को कॉलम B के सही item से मिलाएँ। नीचे दिए गए पोल में सही mapping चुनें।"
                if is_matching else "नीचे दिए गए पोल में A, B, C या D चुनें।"
            )
        elif interface_language == "Hindi":
            heading = f"प्रतियोगी परीक्षा अभ्यास • {question.subject}"
            instruction = (
                "कॉलम A के प्रत्येक item को कॉलम B के सही item से मिलाएँ। "
                "नीचे दिए गए पोल में केवल सही mapping का A, B, C या D चुनें।"
                if is_matching else "नीचे दिए गए पोल में A, B, C या D चुनें।"
            )
        else:
            heading = f"EXAM-STYLE PRACTICE • {question.subject}"
            instruction = (
                "Match every item in Column A with the correct item in Column B. "
                "Choose only the correct mapping A, B, C or D in the poll below."
                if is_matching else "Choose A, B, C or D in the poll below."
            )
        if is_matching:
            type_heading = "🔗 मिलान प्रश्न\n\n" if interface_language == "Hindi" else "🔗 MATCH THE FOLLOWING\n\n"
            options = "\n".join(f"{letter}) {option}" for letter, option in zip("ABCD", question.options, strict=True))
        else:
            type_heading = ""
            options = "\n".join(f"{letter}. {option}" for letter, option in zip("ABCD", question.options, strict=True))
        source_line = ""
        if getattr(question, "source", "ai") == "source" and getattr(question, "source_title", None):
            pages = f"पृष्ठ {getattr(question, 'source_page_start', '?')}-{getattr(question, 'source_page_end', '?')}" if interface_language == "Hindi" else f"pages {getattr(question, 'source_page_start', '?')}-{getattr(question, 'source_page_end', '?')}"
            label = "स्रोत" if interface_language == "Hindi" else "Source"
            source_line = f"\n\n📚 {label}: {question.source_title} ({pages})"
        return f"{heading}\n\n{type_heading}{question.question_text}\n\n{options}\n\n{instruction}{source_line}"

    @staticmethod
    def explanation_button_label(language: str) -> str:
        return "व्याख्या देखें" if language == "Hindi" else "View Explanation"

    @classmethod
    def explanation_text(cls, question: Question, ui_language: str | None = None) -> str:
        interface_language = ui_language or question.language
        labels = cls.explanation_labels(interface_language)
        answer = question.options[question.correct_option]
        source_line = ""
        if getattr(question, "source", "ai") == "source" and getattr(question, "source_title", None):
            pages = f"पृष्ठ {getattr(question, 'source_page_start', '?')}-{getattr(question, 'source_page_end', '?')}" if interface_language == "Hindi" else f"pages {getattr(question, 'source_page_start', '?')}-{getattr(question, 'source_page_end', '?')}"
            label = "स्रोत" if interface_language == "Hindi" else "Source"
            source_line = f"\n\n📚 {label}: {question.source_title} ({pages})"
        return f"{labels['answer']}: {answer}\n\n{labels['explanation']}: {question.explanation}\n\n{labels['key_point']}: {question.key_point}{source_line}"

    @staticmethod
    def daily_challenge_label(language: str) -> str:
        return "🔥 दैनिक चुनौती" if language == "Hindi" else "🔥 DAILY CHALLENGE"

    @staticmethod
    def daily_challenge_notice(language: str, bonus_xp: int) -> str:
        if language == "Hindi":
            return f"दैनिक चुनौती शुरू हो गई है। सही उत्तर पर अतिरिक्त {bonus_xp} XP मिलेगा।"
        return f"Daily Challenge is live. Correct answers earn an extra {bonus_xp} XP."

    async def warm_question_pool(self, group_id: int) -> int:
        """Generate a small validated reserve so delivery does not depend on one live AI call."""
        if not getattr(self.settings, "question_pool_enabled", True):
            return 0
        async with self._group_locks[group_id]:
            async with self.database.session_factory() as session:
                repo = Repository(session)
                settings = await repo.get_settings(group_id)
                if settings is None or not settings.quiz_active:
                    return 0
                allowed = set(subjects_for_state(settings.state))
                subjects = [item for item in (settings.subjects or []) if item in allowed]
                if not subjects:
                    subjects = default_subjects_for_state(settings.state)
                original_subjects = list(settings.subjects or [])
                original_rotation_index = settings.current_rotation_index
                original_topic_state = dict(settings.topic_rotation_state or {})
                generated_count = 0
                target = int(getattr(self.settings, "question_pool_target", 10))
                per_tick = int(getattr(self.settings, "question_pool_fill_per_tick", 1))
                try:
                    settings.subjects = [subjects[0]]
                    for subject in subjects:
                        if generated_count >= per_tick:
                            break
                        existing = await repo.question_pool_count(settings.state, subject, UNIFIED_EXAM_LEVEL, QUESTION_LANGUAGE)
                        if existing >= target:
                            continue
                        settings.subjects = [subject]
                        settings.current_rotation_index = existing % len(question_types_for_difficulty(UNIFIED_EXAM_LEVEL, subject=subject))
                        try:
                            await self._question_for_settings(repo, settings)
                            self.advance_topic(settings, subject)
                            generated_count += 1
                            await repo.commit()
                            logger.info(
                                "Question pool warmed for group %s: %s/%s active %s questions",
                                group_id, existing + 1, target, subject,
                            )
                        except (AIQuestionGenerationError, NoFreshQuestionAvailable) as exc:
                            logger.info("Question pool warm attempt skipped for group %s/%s: %s", group_id, subject, exc)
                            await repo.rollback()
                            settings = await repo.get_settings(group_id)
                            if settings is None:
                                break
                            settings.subjects = [subject]
                            settings.current_rotation_index = existing % len(question_types_for_difficulty(UNIFIED_EXAM_LEVEL, subject=subject))
                            settings.topic_rotation_state = dict(original_topic_state)
                finally:
                    settings.subjects = original_subjects
                    settings.current_rotation_index = original_rotation_index
                    settings.topic_rotation_state = original_topic_state
                    await repo.commit()
                return generated_count

    def is_quiet_hours(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        try:
            timezone_name = getattr(self.settings, "timezone", None) or get_settings().timezone
            zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, AttributeError):
            zone = ZoneInfo("Asia/Kolkata")
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return 0 <= now.astimezone(zone).hour < 7

    async def send_quiz(
        self, group_id: int, *, quiz_kind: str = "automatic", mock_test_id: int | None = None,
        closes_at: datetime | None = None, force: bool = False, poll_open_period: int | None = None,
        show_explanation: bool = True, mock_question_number: int | None = None,
        mock_question_total: int | None = None,
        exclude_question_ids: set[int] | None = None,
    ) -> Question | None:
        """Send exactly one native, non-anonymous Telegram quiz poll to an independently locked group."""
        if quiz_kind in {"automatic", "manual", "daily_challenge"} and self.is_quiet_hours():
            logger.info("Quiet hours active; skipping %s question delivery to %s", quiz_kind, group_id)
            return None
        async with self._group_locks[group_id]:
            async with self.database.session_factory() as session:
                repo = Repository(session)
                settings = await repo.get_settings(group_id)
                if settings is None or (not force and not settings.quiz_active):
                    return None
                if not force and quiz_kind == "automatic" and settings.last_quiz_at:
                    last_quiz_at = settings.last_quiz_at
                    if last_quiz_at.tzinfo is None:
                        last_quiz_at = last_quiz_at.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) - last_quiz_at < timedelta(minutes=settings.interval_minutes):
                        return None
                try:
                    history_ids, history_texts = await repo.delivered_question_history(group_id)
                    effective_exclusions = set(exclude_question_ids or set()) | history_ids
                    question = None
                    for selection_attempt in range(2):
                        try:
                            question = await self._question_for_settings(
                                repo, settings, effective_exclusions,
                                question_type_index=(mock_question_number - 1) if mock_question_number is not None else None,
                            )
                            break
                        except NoFreshQuestionAvailable:
                            if selection_attempt == 1:
                                raise
                            retry_subject = self.subject_for_next_quiz(settings)
                            self.advance_topic(settings, retry_subject)
                            await repo.commit()
                            logger.info(
                                "Retrying quiz delivery for group %s with the next hidden topic after no fresh question for %s",
                                group_id, retry_subject,
                            )
                    if question is None:
                        raise NoFreshQuestionAvailable("No question was produced after the bounded topic retry")
                    now = datetime.now(timezone.utc)

                    # AI/source lookup can take longer than the nominal round timer.
                    # For mocks, start the fixed timer only after the question is ready.
                    final_close_at = (
                        now + timedelta(seconds=poll_open_period)
                        if mock_test_id is not None and poll_open_period is not None
                        else closes_at
                    )
                    open_period = poll_open_period
                    reply_markup = InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            self.explanation_button_label(settings.language), callback_data=f"explain:{question.id}"
                        )
                    ]]) if show_explanation else None
                    mock_progress = (
                        (mock_question_number, mock_question_total)
                        if mock_question_number is not None and mock_question_total is not None else None
                    )
                    poll_question, poll_options = self.poll_content(question, settings.language, mock_progress)
                    if not self.uses_single_poll_layout(question):
                        await self.bot.send_message(
                            chat_id=group_id,
                            text=self.full_question_card(question, settings.language, mock_progress),
                        )
                    try:
                        message = await self.bot.send_poll(
                            chat_id=group_id, question=poll_question, options=poll_options,
                            type=PollType.QUIZ, is_anonymous=False, correct_option_id=question.correct_option,
                            open_period=open_period, reply_markup=reply_markup,
                        )
                    except RetryAfter as exc:
                        logger.warning("Telegram rate limit for group %s; retrying after %s seconds", group_id, exc.retry_after)
                        await asyncio.sleep(float(exc.retry_after) + 0.5)
                        message = await self.bot.send_poll(
                            chat_id=group_id, question=poll_question, options=poll_options,
                            type=PollType.QUIZ, is_anonymous=False, correct_option_id=question.correct_option,
                            open_period=open_period, reply_markup=reply_markup,
                        )
                    if not message.poll:
                        raise TelegramError("Telegram did not return a poll object")
                    await repo.record_quiz(
                        group_id=group_id, question_id=question.id, poll_id=message.poll.id, message_id=message.message_id,
                        quiz_kind=quiz_kind, closes_at=final_close_at, mock_test_id=mock_test_id,
                    )
                    if mock_test_id is not None and mock_question_number is not None and final_close_at is not None:
                        await repo.set_mock_round(
                            mock_test_id, question_number=mock_question_number,
                            poll_id=message.poll.id, round_ends_at=final_close_at,
                        )
                    subject = self.subject_for_next_quiz(settings)
                    selected_topic = self.topic_for_next_quiz(settings, subject)
                    if question.subject == subject and question.topic == selected_topic:
                        self.advance_topic(settings, subject)
                    if quiz_kind in {"automatic", "manual"}:
                        settings.last_quiz_at = now
                    if quiz_kind in {"automatic", "manual", "mock_test"}:
                        settings.current_rotation_index += 1
                    # Toggle only after Telegram accepted the poll. If the preferred
                    # pool was unavailable and a graceful fallback was used, retain
                    # the same preference for the next attempt.
                    settings.source_mode = self.next_question_source(question.source)
                    await repo.commit()
                    return question
                except (Forbidden, BadRequest) as exc:
                    logger.warning("Cannot deliver quiz to group %s: %s", group_id, exc)
                    await repo.rollback()
                    error_text = str(exc).lower()
                    if isinstance(exc, Forbidden) or "chat not found" in error_text or "bot was blocked" in error_text:
                        try:
                            await repo.update_settings(group_id, quiz_active=False)
                            await repo.commit()
                            logger.info("Disabled scheduled quizzes for unreachable chat %s", group_id)
                        except Exception:
                            await repo.rollback()
                            logger.exception("Could not disable unreachable chat %s", group_id)
                    return None
                except NoFreshQuestionAvailable as exc:
                    logger.info("No unseen question available for chat %s: %s", group_id, exc)
                    await repo.rollback()
                    return None
                except (TimedOut, TelegramError) as exc:
                    await repo.rollback()
                    if quiz_kind == "mock_test":
                        raise
                    logger.exception("Quiz delivery failed for group %s: %s", group_id, exc)
                    return None
                except AIQuestionGenerationError as exc:
                    logger.exception("Quiz generation failed for group %s: %s", group_id, exc)
                    await repo.rollback()
                    return None
                except Exception:
                    logger.exception("Unexpected quiz delivery failure for group %s", group_id)
                    await repo.rollback()
                    return None

    async def send_daily_challenge(self, group_id: int, bonus_xp: int = 20) -> bool:
        async with self._group_locks[group_id]:
            async with self.database.session_factory() as session:
                repo = Repository(session)
                if await repo.today_challenge(group_id):
                    return False
                settings = await repo.get_settings(group_id)
                if not settings:
                    return False
                try:
                    question = await self._question_for_settings(repo, settings)
                    poll_question, poll_options = self.poll_content(question, settings.language)
                    if not self.uses_single_poll_layout(question):
                        await self.bot.send_message(chat_id=group_id, text=self.full_question_card(question, settings.language))
                    message = await self.bot.send_poll(
                        chat_id=group_id, question=poll_question, options=poll_options,
                        type=PollType.QUIZ, is_anonymous=False, correct_option_id=question.correct_option,
                        open_period=None,
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton(
                                self.explanation_button_label(settings.language), callback_data=f"explain:{question.id}"
                            )
                        ]]),
                    )
                    if not message.poll:
                        raise TelegramError("Telegram did not return a poll object")
                    challenge = await repo.create_daily_challenge(group_id, question.id, bonus_xp)
                    await repo.set_daily_poll_id(challenge.id, message.poll.id)
                    await repo.record_quiz(
                        group_id=group_id, question_id=question.id, poll_id=message.poll.id,
                        message_id=message.message_id, quiz_kind="daily_challenge",
                        closes_at=None,
                    )
                    await repo.commit()
                    await self.bot.send_message(chat_id=group_id, text=self.daily_challenge_notice(settings.language, bonus_xp))
                    return True
                except Exception:
                    await repo.rollback()
                    logger.exception("Daily challenge failed for group %s", group_id)
                    return False

    @staticmethod
    def mock_lobby_text(
        title: str,
        count: int,
        round_seconds: int,
        participants: int = 0,
        ui_language: str = "Hindi",
    ) -> str:
        if ui_language == "Hindi":
            return (
                "🎲 *Mock Test शुरू होने वाला है*\n\n"
                f"📚 विषय: *{title}*\n"
                f"📝 कुल प्रश्न: *{count}*\n"
                f"⏱ प्रत्येक प्रश्न: *{round_seconds} सेकंड*\n"
                f"👥 Joined: *{participants}/2*\n\n"
                "🏁 कम से कम 2 participants के Join करने पर Mock Test शुरू होगा।\n"
                "नीचे *Join Mock Test* दबाकर शामिल हों।"
            )
        return (
            "🎲 *Mock Test is about to start*\n\n"
            f"📚 Topic: *{title}*\n"
            f"📝 Total questions: *{count}*\n"
            f"⏱ Time per question: *{round_seconds} seconds*\n"
            f"👥 Joined: *{participants}/2*\n\n"
            "🏁 The Mock Test starts when at least 2 participants join.\n"
            "Tap *Join Mock Test* before starting, or answer any live question later—answering automatically adds you to the ranking."
        )

    @staticmethod
    def mock_lobby_keyboard(mock_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Join Mock Test", callback_data=f"mock:join:{mock_id}")
        ]])

    async def _send_message_retry(self, **kwargs):
        for attempt in range(3):
            try:
                return await self.bot.send_message(**kwargs)
            except RetryAfter as exc:
                if attempt == 2:
                    logger.warning("Telegram retry-after exhausted for chat %s", kwargs.get("chat_id"))
                    return None
                await asyncio.sleep(float(exc.retry_after) + 0.5)
            except (TimedOut, TelegramError) as exc:
                if attempt == 2:
                    logger.warning("Telegram message delivery exhausted for chat %s: %s", kwargs.get("chat_id"), exc)
                    return None
                await asyncio.sleep(2 ** attempt)
        return None

    async def _edit_message_retry(self, **kwargs):
        for attempt in range(3):
            try:
                return await self.bot.edit_message_text(**kwargs)
            except RetryAfter as exc:
                if attempt == 2:
                    logger.warning("Telegram lobby edit retry-after exhausted for chat %s", kwargs.get("chat_id"))
                    return None
                await asyncio.sleep(float(exc.retry_after) + 0.5)
            except (TimedOut, TelegramError) as exc:
                if attempt == 2:
                    logger.warning("Telegram lobby edit exhausted for chat %s: %s", kwargs.get("chat_id"), exc)
                    return None
                await asyncio.sleep(2 ** attempt)
        return None

    async def create_mock_lobby(
        self, group_id: int, *, count: int, round_seconds: int, title: str, created_by: int,
    ) -> int | None:
        """Open a two-player lobby before starting synchronized timed quiz rounds."""
        async with self._group_locks[group_id]:
            async with self.database.session_factory() as session:
                repo = Repository(session)
                if await repo.active_mock_for_group(group_id) is not None:
                    return -1
                settings = await repo.get_settings(group_id)
                if not settings:
                    return None
                ui_language = settings.language
                now = datetime.now(timezone.utc)
                lobby_seconds = 60
                mock = await repo.create_mock_test(
                    group_id=group_id, title=title, count=count, round_seconds=round_seconds,
                    subjects=list(settings.subjects), state=settings.state, difficulty=UNIFIED_EXAM_LEVEL,
                    starts_at=now, lobby_closes_at=now + timedelta(seconds=lobby_seconds),
                    ends_at=now + timedelta(seconds=lobby_seconds + count * round_seconds + 60), created_by=created_by,
                )
                await repo.commit()
        lobby_message = await self._send_message_retry(
            chat_id=group_id,
            text=self.mock_lobby_text(title, count, round_seconds, ui_language=ui_language),
            reply_markup=self.mock_lobby_keyboard(mock.id), parse_mode="Markdown",
        )
        lobby_message_id = getattr(lobby_message, "message_id", None)
        if lobby_message_id is not None:
            async with self.database.session_factory() as session:
                repo = Repository(session)
                await repo.set_mock_lobby_message(mock.id, int(lobby_message_id))
                await repo.commit()
        return mock.id

    async def start_mock_test(self, mock_id: int) -> bool:
        """Start a lobby only when at least two registered participants are present."""
        async with self.database.session_factory() as session:
            repo = Repository(session)
            mock = await repo.get_mock_test(mock_id)
            if mock is None or mock.status != "lobby":
                return False
            participants = await repo.mock_participant_count(mock_id)
            settings = await repo.get_settings(mock.group_id)
            ui_language = settings.language if settings is not None else "Hindi"
            if participants < 2:
                lobby_message_id = mock.lobby_message_id
                await repo.cancel_mock_test(mock_id)
                await repo.commit()
                cancellation_text = (
                    "❌ *Mock Test रद्द हो गया*\n\n"
                    "कम से कम 2 participants आवश्यक थे, लेकिन पर्याप्त participants join नहीं हुए।"
                    if ui_language == "Hindi"
                    else "❌ *Mock Test cancelled*\n\n"
                    "At least 2 participants were required, but fewer joined."
                )
                if lobby_message_id is not None:
                    edited = await self._edit_message_retry(
                        chat_id=mock.group_id, message_id=int(lobby_message_id), text=cancellation_text,
                        reply_markup=None, parse_mode="Markdown",
                    )
                    if edited is not None:
                        return False
                await self._send_message_retry(chat_id=mock.group_id, text=cancellation_text, parse_mode="Markdown")
                return False
            now = datetime.now(timezone.utc)
            await repo.start_mock_test(
                mock_id, starts_at=now, ends_at=now + timedelta(seconds=mock.question_count * mock.round_seconds + 60)
            )
            settings = await repo.get_settings(mock.group_id)
            ui_language = settings.language if settings is not None else "Hindi"
            await repo.commit()
        if ui_language == "Hindi":
            live_text = (
                "🎲 *Mock Test शुरू हो गया!*\n\n"
                f"👥 प्रतिभागी: *{participants}*\n"
                f"📝 कुल प्रश्न: *{mock.question_count}*\n"
                f"⏱ प्रत्येक प्रश्न: *{mock.round_seconds} सेकंड*\n\n"
                f"हर प्रश्न के ऊपर progress जैसे *[1/{mock.question_count}]* दिखाई देगा। "
                "समय समाप्त होने से पहले उत्तर दें। शुभकामनाएँ!"
            )
        else:
            live_text = (
                "🎲 *Mock Test is live!*\n\n"
                f"👥 Participants: *{participants}*\n"
                f"📝 Total questions: *{mock.question_count}*\n"
                f"⏱ *{mock.round_seconds} seconds* per question\n\n"
                f"Every question shows progress like *[1/{mock.question_count}]*. "
                "Answer before the timer closes. Good luck!"
            )
        await self._send_message_retry(chat_id=mock.group_id, text=live_text, parse_mode="Markdown")
        return await self.send_next_mock_round(mock_id)

    async def _advance_mock_subject_topic_for_retry(self, group_id: int) -> None:
        async with self.database.session_factory() as session:
            repo = Repository(session)
            settings = await repo.get_settings(group_id)
            if settings is None:
                return
            subjects = [item for item in (settings.subjects or []) if item in set(subjects_for_state(settings.state))]
            if not subjects:
                subjects = default_subjects_for_state(settings.state)
            subject = subjects[settings.current_rotation_index % len(subjects)]
            topic_state = dict(settings.topic_rotation_state or {})
            topic_state[subject] = int(topic_state.get(subject, 0)) + 1
            settings.topic_rotation_state = topic_state
            await repo.commit()

    async def _defer_mock_round(self, mock_id: int, delay_seconds: int = 15) -> None:
        """Keep a running mock alive after a transient delivery failure."""
        async with self.database.session_factory() as session:
            repo = Repository(session)
            mock = await repo.get_mock_test(mock_id)
            if mock is None or mock.status != "running":
                return
            retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
            current_end = mock.ends_at or retry_at
            if current_end.tzinfo is None:
                current_end = current_end.replace(tzinfo=timezone.utc)
            mock.round_ends_at = retry_at
            mock.ends_at = max(current_end, retry_at + timedelta(seconds=60))
            await repo.commit()

    async def _end_mock_without_question(self, mock_id: int) -> None:
        """Complete a mock once when no validated question can be delivered."""
        async with self.database.session_factory() as session:
            repo = Repository(session)
            mock = await repo.get_mock_test(mock_id)
            if mock is None or mock.status != "running":
                return
            group_id = mock.group_id
            settings = await repo.get_settings(group_id)
            ui_language = settings.language if settings is not None else "Hindi"
            await repo.complete_mock_test(mock_id)
            await repo.commit()
        text = (
            "⚠️ इस Mock Test के लिए validated question उपलब्ध नहीं है। Mock Test यहीं समाप्त किया जा रहा है।"
            if ui_language == "Hindi"
            else "⚠️ No validated question is available for this Mock Test. The Mock Test is ending now."
        )
        await self._send_message_retry(chat_id=group_id, text=text)

    async def send_next_mock_round(self, mock_id: int) -> bool:
        """Publish exactly one official-style quiz poll and wait for its fixed timer to expire."""
        async with self.database.session_factory() as session:
            repo = Repository(session)
            mock = await repo.get_mock_test(mock_id)
            if mock is None or mock.status != "running":
                return False
            if mock.current_question_number >= mock.question_count:
                return False
            number = mock.current_question_number + 1
            group_id = mock.group_id
            round_seconds = mock.round_seconds
            used_question_ids = await repo.mock_question_ids(mock_id)
        closes_at = datetime.now(timezone.utc) + timedelta(seconds=round_seconds)
        # The native poll itself provides the timer context. Do not send a
        # separate Round 1/2 banner before each mock question.
        question = None
        for attempt in range(3):
            try:
                question = await self.send_quiz(
                    group_id, quiz_kind="mock_test", mock_test_id=mock_id, closes_at=closes_at,
                    force=True, poll_open_period=round_seconds, show_explanation=False,
                    mock_question_number=number, mock_question_total=mock.question_count,
                    exclude_question_ids=used_question_ids,
                )
            except (TimedOut, TelegramError) as exc:
                logger.warning("Transient mock round delivery failure for test %s (attempt %s/3): %s", mock_id, attempt + 1, exc)
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                await self._defer_mock_round(mock_id)
                await self._send_message_retry(
                    chat_id=group_id,
                    text="⏳ नेटवर्क समस्या के कारण यह round थोड़ी देर में फिर try होगा। Mock test जारी है।",
                )
                return True
            if question is not None:
                return True
            if attempt < 2:
                await self._advance_mock_subject_topic_for_retry(group_id)
        await self._end_mock_without_question(mock_id)
        return False

    async def stop_mock_test(self, group_id: int) -> int | None:
        """Cancel the active lobby or round for a group administrator."""
        async with self.database.session_factory() as session:
            repo = Repository(session)
            mock = await repo.active_mock_for_group(group_id)
            if mock is None:
                return None
            await repo.cancel_mock_test(mock.id)
            await repo.commit()
        if mock.current_poll_id:
            try:
                await self.bot.stop_poll(chat_id=group_id, message_id=(
                    (await self._mock_poll_message_id(mock.current_poll_id)) or 0
                ))
            except (BadRequest, TelegramError):
                pass
        await self.bot.send_message(
            chat_id=group_id,
            text=f"🛑 {mock.title} was stopped by an administrator. No further questions will be sent.",
        )
        return mock.id

    async def _mock_poll_message_id(self, poll_id: str) -> int | None:
        async with self.database.session_factory() as session:
            history = await Repository(session).get_quiz_by_poll(poll_id)
            return history.message_id if history else None

    async def advance_mock_round(self, mock_id: int) -> bool:
        """Close the expired round before launching the next round or finalizing the test."""
        async with self.database.session_factory() as session:
            repo = Repository(session)
            mock = await repo.get_mock_test(mock_id)
            if mock is None or mock.status != "running":
                return False
            poll_id = mock.current_poll_id
            question_number = mock.current_question_number
        if poll_id:
            await self.close_quiz_and_explain(0, poll_id)
        if question_number >= mock.question_count:
            return False
        return await self.send_next_mock_round(mock_id)

    async def close_quiz_and_explain(self, history_id: int, poll_id: str) -> None:
        async with self.database.session_factory() as session:
            repo = Repository(session)
            history = await repo.get_quiz_by_poll(poll_id)
            if not history or history.closed:
                return
            question = await repo.get_question(history.question_id)
            settings = await repo.get_settings(history.group_id)
            sent_explanation = False
            try:
                await self.bot.stop_poll(chat_id=history.group_id, message_id=history.message_id)
            except BadRequest as exc:
                if "closed" not in str(exc).lower():
                    logger.warning("Could not close poll %s: %s", poll_id, exc)
            except TelegramError as exc:
                logger.warning("Could not close poll %s: %s", poll_id, exc)
            await repo.close_quiz(poll_id, sent_explanation)
            await repo.commit()

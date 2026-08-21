"""Database repository layer. Keeps SQL out of handlers and services."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import and_, case, delete, desc, func, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import DEFAULT_LANGUAGE, DEFAULT_SUBJECTS, DEFAULT_XP_MAP, GSI_HONOR_TAG, UNIFIED_EXAM_LEVEL
from bot.database.models import (
    DailyChallenge, DeliveryCampaign, DeliveryReceipt, Group, GroupSettings, MockTest, MockTestParticipant, MockTestResult,
    OfficialQuiz, OfficialQuizDraft, OfficialQuizParticipant, OfficialQuizResult, Question, QuizHistory,
    SourceChunk, SourceDocument, User, UserAnswer,
)
from bot.services.question_validator import normalize_text


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_group(self, group_id: int, title: str, chat_type: str = "group") -> GroupSettings:
        group = await self.session.get(Group, group_id)
        if group is None:
            group = Group(telegram_chat_id=group_id, title=title or "Study Group", chat_type=chat_type)
            self.session.add(group)
            await self.session.flush()
        elif title and group.title != title:
            group.title = title
        settings = await self.session.get(GroupSettings, group_id)
        if settings is None:
            settings = GroupSettings(
                group_id=group_id, subjects=DEFAULT_SUBJECTS.copy(), xp_map=DEFAULT_XP_MAP.copy()
            )
            self.session.add(settings)
        settings.rotation_enabled = True
        settings.explanation_enabled = True
        await self.session.flush()
        return settings

    async def get_settings(self, group_id: int) -> GroupSettings | None:
        return await self.session.get(GroupSettings, group_id)

    async def update_settings(self, group_id: int, **values: object) -> GroupSettings:
        settings = await self.session.get(GroupSettings, group_id)
        if settings is None:
            raise ValueError("Group settings do not exist")
        for field, value in values.items():
            setattr(settings, field, value)
        await self.session.flush()
        return settings

    async def audience_chat_ids(self, audience: str, state: str | None = None) -> list[int]:
        """Return active bot-reachable private chats and/or groups, optionally filtered by saved state."""
        allowed_types: list[str] = []
        if audience in {"users", "both"}:
            allowed_types.append("private")
        if audience in {"groups", "both"}:
            allowed_types.extend(["group", "supergroup"])
        if not allowed_types:
            return []
        conditions = [Group.is_active.is_(True), Group.chat_type.in_(allowed_types)]
        if state:
            conditions.append(GroupSettings.state == state)
        result = await self.session.execute(
            select(Group.telegram_chat_id)
            .join(GroupSettings, GroupSettings.group_id == Group.telegram_chat_id)
            .where(and_(*conditions))
            .order_by(Group.telegram_chat_id)
        )
        return list(result.scalars())

    async def audience_chat_summaries(self, audience: str, state: str | None = None) -> list[tuple[int, str, str]]:
        """Return eligible chat IDs with stored titles for the admin confirmation preview."""
        allowed_types: list[str] = []
        if audience in {"users", "both"}:
            allowed_types.append("private")
        if audience in {"groups", "both"}:
            allowed_types.extend(["group", "supergroup"])
        if not allowed_types:
            return []
        conditions = [Group.is_active.is_(True), Group.chat_type.in_(allowed_types)]
        if state:
            conditions.append(GroupSettings.state == state)
        result = await self.session.execute(
            select(Group.telegram_chat_id, Group.title, Group.chat_type)
            .join(GroupSettings, GroupSettings.group_id == Group.telegram_chat_id)
            .where(and_(*conditions))
            .order_by(Group.title, Group.telegram_chat_id)
        )
        return [(int(chat_id), title, chat_type) for chat_id, title, chat_type in result.all()]

    async def create_delivery_campaign(
        self, *, created_by: int, mode: str, audience: str, state: str | None,
        content_type: str, content_text: str | None, payload: dict[str, object], recipient_count: int,
    ) -> DeliveryCampaign:
        campaign = DeliveryCampaign(
            created_by=created_by, mode=mode, audience=audience, state=state,
            content_type=content_type, content_text=content_text, payload=payload,
            status="sending", recipient_count=recipient_count,
        )
        self.session.add(campaign)
        await self.session.flush()
        return campaign

    async def create_delivery_receipts(self, campaign_id: int, chat_ids: list[int]) -> list[DeliveryReceipt]:
        receipts = [DeliveryReceipt(campaign_id=campaign_id, chat_id=chat_id, status="pending") for chat_id in chat_ids]
        self.session.add_all(receipts)
        await self.session.flush()
        return receipts

    async def update_delivery_receipt(
        self, receipt_id: int, *, status: str, telegram_message_id: int | None = None, error: str | None = None
    ) -> None:
        receipt = await self.session.get(DeliveryReceipt, receipt_id)
        if receipt is None:
            raise ValueError("Delivery receipt does not exist")
        receipt.status = status
        receipt.telegram_message_id = telegram_message_id
        receipt.error = error[:512] if error else None
        await self.session.flush()

    async def complete_delivery_campaign(self, campaign_id: int, *, sent_count: int, failed_count: int) -> None:
        campaign = await self.session.get(DeliveryCampaign, campaign_id)
        if campaign is None:
            raise ValueError("Delivery campaign does not exist")
        campaign.sent_count = sent_count
        campaign.failed_count = failed_count
        campaign.status = "completed" if failed_count == 0 else "completed_with_errors"
        await self.session.flush()

    async def active_group_settings(self) -> list[GroupSettings]:
        result = await self.session.execute(select(GroupSettings).where(GroupSettings.quiz_active.is_(True)))
        return list(result.scalars())

    async def active_group_settings_for_types(self, chat_types: list[str]) -> list[GroupSettings]:
        result = await self.session.execute(
            select(GroupSettings).join(Group, Group.telegram_chat_id == GroupSettings.group_id)
            .where(and_(GroupSettings.quiz_active.is_(True), Group.chat_type.in_(chat_types)))
        )
        return list(result.scalars())

    async def due_group_settings(self, now: datetime) -> list[GroupSettings]:
        result = await self.session.execute(
            select(GroupSettings).where(GroupSettings.quiz_active.is_(True))
        )
        due: list[GroupSettings] = []
        for settings in result.scalars():
            last_quiz_at = settings.last_quiz_at
            if last_quiz_at is not None and last_quiz_at.tzinfo is None:
                last_quiz_at = last_quiz_at.replace(tzinfo=timezone.utc)
            if last_quiz_at is None or now - last_quiz_at >= timedelta(minutes=settings.interval_minutes):
                due.append(settings)
        return due

    async def groups_awaiting_bot_admin(self) -> list[GroupSettings]:
        """Return active group chats where the bot has not yet received admin rights."""
        result = await self.session.execute(
            select(GroupSettings)
            .join(Group, Group.telegram_chat_id == GroupSettings.group_id)
            .where(
                and_(
                    Group.is_active.is_(True),
                    Group.chat_type.in_(["group", "supergroup"]),
                    GroupSettings.bot_is_admin.is_(False),
                    GroupSettings.bot_joined_at.is_not(None),
                )
            )
            .order_by(GroupSettings.bot_joined_at.asc(), GroupSettings.group_id.asc())
        )
        return list(result.scalars())

    async def upsert_user(self, telegram_user_id: int, username: str | None, display_name: str) -> User:
        user = await self.session.get(User, telegram_user_id)
        if user is None:
            user = User(telegram_user_id=telegram_user_id, username=username, display_name=display_name or "Student")
            self.session.add(user)
        else:
            user.username = username
            user.display_name = display_name or user.display_name
        await self.session.flush()
        return user

    async def get_user(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def set_user_language(self, user_id: int, language: str) -> None:
        user = await self.session.get(User, user_id)
        if user is None:
            raise ValueError("User must exist before setting a language")
        user.preferred_language = language
        await self.session.flush()

    async def update_user_onboarding(
        self, user_id: int, *, exam_preparation: str | None = None, completed: bool | None = None
    ) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise ValueError("User must exist before updating onboarding")
        if exam_preparation is not None:
            user.exam_preparation = exam_preparation
        if completed is not None:
            user.onboarding_completed = completed
        await self.session.flush()
        return user

    async def create_source_document(
        self, *, telegram_file_id: str, telegram_chat_id: int, telegram_message_id: int, uploaded_by: int,
        filename: str, storage_path: str,
    ) -> SourceDocument:
        document = SourceDocument(
            telegram_file_id=telegram_file_id, telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id, uploaded_by=uploaded_by,
            filename=filename, storage_path=storage_path, title=filename,
        )
        self.session.add(document)
        await self.session.flush()
        return document

    async def get_source_document(self, document_id: int) -> SourceDocument | None:
        return await self.session.get(SourceDocument, document_id)

    async def source_document_by_hash(self, content_hash: str) -> SourceDocument | None:
        result = await self.session.execute(
            select(SourceDocument).where(SourceDocument.content_hash == content_hash).limit(1)
        )
        return result.scalar_one_or_none()

    async def update_source_document(self, document_id: int, **values: object) -> SourceDocument:
        document = await self.session.get(SourceDocument, document_id)
        if document is None:
            raise ValueError("Source document does not exist")
        for field, value in values.items():
            setattr(document, field, value)
        await self.session.flush()
        return document

    async def replace_source_chunks(self, document_id: int, *, state: str, subject: str, chunks: list[dict[str, object]]) -> int:
        await self.session.execute(delete(SourceChunk).where(SourceChunk.document_id == document_id))
        await self.session.flush()
        return await self.add_source_chunks(document_id, state=state, subject=subject, chunks=chunks)

    async def add_source_chunks(self, document_id: int, *, state: str, subject: str, chunks: list[dict[str, object]]) -> int:
        inserted = 0
        for chunk in chunks:
            row = SourceChunk(document_id=document_id, state=state, subject=subject, **chunk)
            try:
                async with self.session.begin_nested():
                    self.session.add(row)
                    await self.session.flush()
                inserted += 1
            except IntegrityError:
                continue
        return inserted

    async def source_chunks_for_scope(
        self, *, state: str, subject: str, topic: str | None = None, limit: int = 3,
    ) -> list[SourceChunk]:
        conditions = [SourceChunk.state.in_([state, "All India", "General"]), SourceChunk.subject == subject]
        if topic:
            conditions.append(SourceChunk.topic == topic)
        result = await self.session.execute(
            select(SourceChunk).where(and_(*conditions)).order_by(SourceChunk.chunk_index.asc()).limit(limit)
        )
        return list(result.scalars())

    async def source_document_count(self, *, state: str | None = None, subject: str | None = None) -> int:
        conditions = [SourceDocument.status == "ready"]
        if state:
            conditions.append(SourceDocument.state == state)
        if subject:
            conditions.append(SourceDocument.subject == subject)
        result = await self.session.execute(select(func.count(SourceDocument.id)).where(and_(*conditions)))
        return int(result.scalar_one() or 0)

    async def source_document_summaries(self, *, state: str | None = None, limit: int = 20) -> list[SourceDocument]:
        conditions = []
        if state:
            conditions.append(SourceDocument.state == state)
        result = await self.session.execute(
            select(SourceDocument).where(and_(*conditions) if conditions else True)
            .order_by(desc(SourceDocument.created_at)).limit(limit)
        )
        return list(result.scalars())

    async def add_question(
        self, *, question_text: str, options: list[str], correct_option: int, explanation: str,
        key_point: str, state: str, subject: str, topic: str, difficulty: str,
        question_type: str, language: str = DEFAULT_LANGUAGE, source: str = "ai", source_group_id: int | None = None, ai_model: str | None = None,
        source_document_id: int | None = None, source_title: str | None = None,
        source_page_start: int | None = None, source_page_end: int | None = None,
    ) -> Question:
        question = Question(
            question_text=question_text, normalized_text=normalize_text(question_text), options=options,
            correct_option=correct_option, explanation=explanation, key_point=key_point,
            state=state, subject=subject, topic=topic, difficulty=difficulty,
            question_type=question_type, language=language, source=source, source_group_id=source_group_id, ai_model=ai_model,
            source_document_id=source_document_id, source_title=source_title,
            source_page_start=source_page_start, source_page_end=source_page_end,
        )
        self.session.add(question)
        await self.session.flush()
        return question

    async def get_question(self, question_id: int) -> Question | None:
        return await self.session.get(Question, question_id)

    async def similar_question_texts(self, state: str, subject: str, language: str = DEFAULT_LANGUAGE, limit: int = 250) -> list[str]:
        result = await self.session.execute(
            select(Question.question_text)
            .where(and_(
                Question.state == state, Question.subject == subject, Question.language == language,
                Question.is_active.is_(True), Question.source != "official_quiz",
            ))
            .order_by(desc(Question.created_at)).limit(limit)
        )
        return list(result.scalars())

    async def existing_question(self, normalized: str) -> bool:
        result = await self.session.execute(select(Question.id).where(Question.normalized_text == normalized))
        return result.scalar_one_or_none() is not None

    async def question_by_normalized(self, normalized: str) -> Question | None:
        result = await self.session.execute(select(Question).where(Question.normalized_text == normalized).limit(1))
        return result.scalar_one_or_none()

    async def question_pool_count(self, state: str, subject: str, difficulty: str, language: str = DEFAULT_LANGUAGE) -> int:
        conditions = [
            Question.state.in_([state, "India", "General", "World"]),
            Question.subject == subject,
            Question.language == language,
            Question.is_active.is_(True), Question.source != "official_quiz",
            Question.question_type != "Application-based",
            or_(Question.question_type != "Assertion-Reason", Question.subject == "Reasoning"),
        ]
        if difficulty != UNIFIED_EXAM_LEVEL:
            conditions.append(Question.difficulty == difficulty)
        result = await self.session.execute(select(func.count(Question.id)).where(and_(*conditions)))
        return int(result.scalar_one() or 0)

    async def list_questions_for_scope(
        self, state: str, subjects: list[str], difficulty: str, limit: int, language: str = DEFAULT_LANGUAGE,
        topic: str | None = None, exclude_question_ids: set[int] | None = None, source: str | None = None,
        question_type: str | None = None,
    ) -> list[Question]:
        subject_filter = Question.subject.in_(subjects) if subjects else True
        state_filter = Question.state.in_([state, "India", "General", "World"])
        conditions = [
            state_filter, subject_filter, Question.language == language,
            Question.is_used.is_(False), Question.is_active.is_(True),
            Question.question_type != "Application-based",
            or_(Question.question_type != "Assertion-Reason", Question.subject == "Reasoning"),
        ]
        if difficulty != UNIFIED_EXAM_LEVEL:
            conditions.append(Question.difficulty == difficulty)
        if topic:
            conditions.append(Question.topic == topic)
        if question_type:
            conditions.append(Question.question_type == question_type)
        if exclude_question_ids:
            conditions.append(~Question.id.in_(exclude_question_ids))
        if source == "non-source":
            conditions.append(Question.source != "source")
        elif source:
            conditions.append(Question.source == source)
        result = await self.session.execute(
            select(Question).where(and_(*conditions))
            .order_by(Question.used_count.asc(), Question.created_at.asc()).limit(limit)
        )
        return list(result.scalars())

    async def fallback_question_for_scope(
        self,         state: str, subjects: list[str], language: str = DEFAULT_LANGUAGE,
        topic: str | None = None, exclude_question_ids: set[int] | None = None, source: str | None = None,
        question_type: str | None = None,

    ) -> Question | None:
        """Return the least-used compatible stored MCQ, including previously used items as a last resort."""
        state_scopes = ([state], ["General", "India", "World"])
        # When the chat has an explicit subject selection, never broaden the
        # fallback to an unselected subject. A broad subject fallback is only
        # valid for callers that intentionally pass an empty subject list.
        subject_scopes: tuple[list[str] | None, ...] = (subjects,) if subjects else (None,)
        for states in state_scopes:
            for subject_scope in subject_scopes:
                conditions = [
                    Question.state.in_(states), Question.language == language, Question.is_active.is_(True),
                    Question.source != "official_quiz",
                    Question.question_type != "Application-based",
                    or_(Question.question_type != "Assertion-Reason", Question.subject == "Reasoning"),
                ]
                if subject_scope:
                    conditions.append(Question.subject.in_(subject_scope))
                if topic:
                    conditions.append(Question.topic == topic)
                if question_type:
                    conditions.append(Question.question_type == question_type)
                if exclude_question_ids:
                    conditions.append(~Question.id.in_(exclude_question_ids))
                if source == "non-source":
                    conditions.append(Question.source != "source")
                elif source:
                    conditions.append(Question.source == source)
                result = await self.session.execute(
                    select(Question)
                    .where(and_(*conditions))
                    .order_by(Question.used_count.asc(), Question.created_at.asc())
                    .limit(1)
                )
                question = result.scalar_one_or_none()
                if question is not None:
                    return question
        return None

    async def mark_question_used(self, question_id: int) -> None:
        await self.session.execute(
            update(Question).where(Question.id == question_id).values(used_count=Question.used_count + 1, is_used=True)
        )

    async def record_quiz(
        self, *, group_id: int, question_id: int, poll_id: str, message_id: int, quiz_kind: str,
        closes_at: datetime | None, mock_test_id: int | None = None,
        official_quiz_id: int | None = None, official_question_number: int | None = None,
    ) -> QuizHistory:
        history = QuizHistory(
            group_id=group_id, question_id=question_id, telegram_poll_id=poll_id, message_id=message_id,
            quiz_kind=quiz_kind, closes_at=closes_at, mock_test_id=mock_test_id,
            official_quiz_id=official_quiz_id, official_question_number=official_question_number,
        )
        self.session.add(history)
        await self.mark_question_used(question_id)
        await self.session.flush()
        return history

    async def get_quiz_by_poll(self, poll_id: str) -> QuizHistory | None:
        result = await self.session.execute(select(QuizHistory).where(QuizHistory.telegram_poll_id == poll_id))
        return result.scalar_one_or_none()

    async def delivered_question_history(self, chat_id: int) -> tuple[set[int], list[str]]:
        """Return every question ID and text previously delivered to this chat."""
        result = await self.session.execute(
            select(QuizHistory.question_id, Question.question_text)
            .join(Question, Question.id == QuizHistory.question_id)
            .where(QuizHistory.group_id == chat_id)
            .order_by(QuizHistory.created_at.asc())
        )
        rows = result.all()
        return {int(question_id) for question_id, _ in rows}, [text for _, text in rows]

    async def unanswered_open_quizzes(self, now: datetime) -> list[QuizHistory]:
        result = await self.session.execute(
            select(QuizHistory).where(
                and_(
                    QuizHistory.closed.is_(False), QuizHistory.quiz_kind == "mock_test",
                    QuizHistory.closes_at.is_not(None), QuizHistory.closes_at <= now,
                )
            )
        )
        return list(result.scalars())

    async def close_quiz(self, poll_id: str, explanation_sent: bool) -> None:
        await self.session.execute(
            update(QuizHistory).where(QuizHistory.telegram_poll_id == poll_id).values(
                closed=True, explanation_sent=explanation_sent
            )
        )

    async def record_answer(
        self, *, poll_id: str, group_id: int, question_id: int, user_id: int,
        selected_option: int, is_correct: bool, xp_awarded: int, points_awarded: int,
    ) -> bool:
        """Insert one answer. Returns False when Telegram redelivers an existing answer."""
        answer = UserAnswer(
            poll_id=poll_id, group_id=group_id, question_id=question_id, user_id=user_id,
            selected_option=selected_option, is_correct=is_correct, xp_awarded=xp_awarded,
            points_awarded=points_awarded,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(answer)
                await self.session.flush()
        except IntegrityError:
            return False
        user = await self.session.get(User, user_id, with_for_update=True)
        if user is None:
            raise ValueError("User must be created before recording an answer")
        user.total_attempts += 1
        if is_correct:
            user.correct_answers += 1
            user.xp += xp_awarded
            user.total_points += points_awarded
            user.current_streak += 1
            user.best_streak = max(user.best_streak, user.current_streak)
        else:
            user.wrong_answers += 1
            user.current_streak = 0
        await self.session.flush()
        return True

    async def leaderboard(self, group_id: int | None, period_start: datetime | None, limit: int = 15) -> list[dict]:
        conditions = []
        if group_id is not None:
            conditions.append(UserAnswer.group_id == group_id)
        if period_start:
            conditions.append(UserAnswer.created_at >= period_start)
        correct_expr = func.sum(case((UserAnswer.is_correct.is_(True), 1), else_=0))
        attempts_expr = func.count(UserAnswer.id)
        aggregate = select(
            UserAnswer.user_id.label("user_id"),
            func.sum(UserAnswer.xp_awarded).label("xp"),
            correct_expr.label("correct"),
            attempts_expr.label("attempts"),
            (correct_expr * 100.0 / func.nullif(attempts_expr, 0)).label("accuracy"),
        ).group_by(UserAnswer.user_id)
        if conditions:
            aggregate = aggregate.where(and_(*conditions))
        totals = aggregate.subquery()
        result = await self.session.execute(
            select(
                User.telegram_user_id, User.username, User.display_name, User.honor_tag,
                User.gsi_wins, User.gsi_achievements, User.star_count, User.star_title,
                totals.c.xp, totals.c.correct, totals.c.attempts, totals.c.accuracy,
            )
            .join(totals, totals.c.user_id == User.telegram_user_id)
            .order_by(desc(totals.c.xp), desc(totals.c.accuracy), desc(totals.c.correct), desc(totals.c.attempts))
            .limit(limit)
        )
        return [dict(row._mapping) for row in result]

    async def group_rank(self, group_id: int, user_id: int) -> int | None:
        rows = await self.leaderboard(group_id=group_id, period_start=None, limit=100000)
        return next((index for index, row in enumerate(rows, 1) if row["telegram_user_id"] == user_id), None)

    async def group_stats(self, group_id: int) -> dict[str, int]:
        result = await self.session.execute(
            select(
                func.count(QuizHistory.id).label("quizzes"),
                func.count(func.distinct(UserAnswer.user_id)).label("players"),
                func.count(UserAnswer.id).label("attempts"),
                func.sum(case((UserAnswer.is_correct.is_(True), 1), else_=0)).label("correct"),
            ).select_from(QuizHistory).outerjoin(UserAnswer, UserAnswer.poll_id == QuizHistory.telegram_poll_id)
            .where(QuizHistory.group_id == group_id)
        )
        return {key: int(value or 0) for key, value in result.one()._mapping.items()}

    async def create_daily_challenge(self, group_id: int, question_id: int, bonus_xp: int) -> DailyChallenge:
        challenge = DailyChallenge(group_id=group_id, challenge_date=date.today(), question_id=question_id, bonus_xp=bonus_xp)
        self.session.add(challenge)
        await self.session.flush()
        return challenge

    async def today_challenge(self, group_id: int) -> DailyChallenge | None:
        result = await self.session.execute(
            select(DailyChallenge).where(and_(DailyChallenge.group_id == group_id, DailyChallenge.challenge_date == date.today()))
        )
        return result.scalar_one_or_none()

    async def set_daily_poll_id(self, challenge_id: int, poll_id: str) -> None:
        await self.session.execute(update(DailyChallenge).where(DailyChallenge.id == challenge_id).values(poll_id=poll_id))

    async def daily_bonus_for_poll(self, poll_id: str) -> int:
        result = await self.session.execute(select(DailyChallenge.bonus_xp).where(DailyChallenge.poll_id == poll_id))
        return int(result.scalar_one_or_none() or 0)

    async def create_mock_test(
        self, *, group_id: int, title: str, count: int, round_seconds: int, subjects: list[str], state: str,
        difficulty: str, starts_at: datetime, ends_at: datetime, lobby_closes_at: datetime, created_by: int,
    ) -> MockTest:
        mock = MockTest(
            group_id=group_id, title=title, question_count=count, duration_minutes=max(1, round_seconds * count // 60),
            subjects=subjects, state=state, difficulty=difficulty, starts_at=starts_at, ends_at=ends_at,
            lobby_closes_at=lobby_closes_at, round_seconds=round_seconds, status="lobby", created_by=created_by,
        )
        self.session.add(mock)
        await self.session.flush()
        return mock

    async def get_mock_test(self, mock_id: int) -> MockTest | None:
        return await self.session.get(MockTest, mock_id)

    async def join_mock_test(self, mock_id: int, user_id: int) -> int:
        for attempt in range(4):
            participant = MockTestParticipant(mock_test_id=mock_id, user_id=user_id)
            try:
                async with self.session.begin_nested():
                    self.session.add(participant)
                    await self.session.flush()
                break
            except IntegrityError:
                break
            except OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 3:
                    raise
                await self.session.rollback()
                await asyncio.sleep(0.25 * (attempt + 1))
        return await self.mock_participant_count(mock_id)

    async def mock_participant_count(self, mock_id: int) -> int:
        result = await self.session.execute(
            select(func.count(MockTestParticipant.id)).where(MockTestParticipant.mock_test_id == mock_id)
        )
        return int(result.scalar_one() or 0)

    async def is_mock_participant(self, mock_id: int, user_id: int) -> bool:
        result = await self.session.execute(
            select(MockTestParticipant.id).where(and_(MockTestParticipant.mock_test_id == mock_id, MockTestParticipant.user_id == user_id))
        )
        return result.scalar_one_or_none() is not None

    async def start_mock_test(self, mock_id: int, *, starts_at: datetime, ends_at: datetime) -> bool:
        result = await self.session.execute(
            update(MockTest).where(and_(MockTest.id == mock_id, MockTest.status == "lobby"))
            .values(status="running", starts_at=starts_at, ends_at=ends_at)
        )
        return bool(result.rowcount)

    async def set_mock_round(self, mock_id: int, *, question_number: int, poll_id: str, round_ends_at: datetime) -> None:
        mock = await self.session.get(MockTest, mock_id)
        if mock is None:
            return
        current_end = mock.ends_at
        if current_end is None:
            current_end = round_ends_at
        elif current_end.tzinfo is None:
            current_end = current_end.replace(tzinfo=timezone.utc)
        extended_end = round_ends_at + timedelta(seconds=60)
        mock.current_question_number = question_number
        mock.current_poll_id = poll_id
        mock.round_ends_at = round_ends_at
        mock.ends_at = max(current_end, extended_end)
        await self.session.flush()

    async def active_mock_for_group(self, group_id: int) -> MockTest | None:
        result = await self.session.execute(
            select(MockTest)
            .where(and_(MockTest.group_id == group_id, MockTest.status.in_(["lobby", "running"])))
            .order_by(desc(MockTest.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def mock_question_ids(self, mock_id: int) -> set[int]:
        result = await self.session.execute(
            select(QuizHistory.question_id).where(QuizHistory.mock_test_id == mock_id)
        )
        return {int(question_id) for question_id in result.scalars()}

    async def active_mock_group_ids(self) -> set[int]:
        result = await self.session.execute(
            select(MockTest.group_id).where(MockTest.status.in_(["lobby", "running"]))
        )
        return {int(group_id) for group_id in result.scalars()}

    async def due_mock_lobbies(self, now: datetime) -> list[MockTest]:
        result = await self.session.execute(
            select(MockTest).where(and_(MockTest.status == "lobby", MockTest.lobby_closes_at.is_not(None), MockTest.lobby_closes_at <= now))
        )
        return list(result.scalars())

    async def due_mock_rounds(self, now: datetime) -> list[MockTest]:
        result = await self.session.execute(
            select(MockTest).where(and_(MockTest.status == "running", MockTest.round_ends_at.is_not(None), MockTest.round_ends_at <= now))
        )
        return list(result.scalars())

    async def set_mock_lobby_message(self, mock_id: int, message_id: int) -> None:
        await self.session.execute(
            update(MockTest).where(MockTest.id == mock_id).values(lobby_message_id=message_id)
        )

    async def cancel_mock_test(self, mock_id: int) -> None:
        await self.session.execute(update(MockTest).where(MockTest.id == mock_id).values(status="cancelled"))

    async def has_mock_started_on(self, group_id: int, title_prefix: str, day: date) -> bool:
        start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        result = await self.session.execute(
            select(MockTest.id).where(and_(MockTest.group_id == group_id, MockTest.title.like(f"{title_prefix}%"), MockTest.starts_at >= start, MockTest.starts_at < end))
        )
        return result.scalar_one_or_none() is not None

    async def due_mock_tests(self, now: datetime) -> list[MockTest]:
        result = await self.session.execute(
            select(MockTest).where(and_(MockTest.status == "running", MockTest.ends_at <= now))
        )
        return list(result.scalars())

    async def complete_mock_test(self, mock_id: int) -> None:
        await self.session.execute(update(MockTest).where(MockTest.id == mock_id).values(status="completed"))

    async def mock_results(self, mock_id: int) -> list[dict]:
        answer_totals = (
            select(
                UserAnswer.user_id.label("user_id"),
                func.sum(case((UserAnswer.is_correct.is_(True), 1), else_=0)).label("correct"),
                func.sum(case((UserAnswer.is_correct.is_(False), 1), else_=0)).label("wrong"),
            )
            .join(QuizHistory, QuizHistory.telegram_poll_id == UserAnswer.poll_id)
            .where(QuizHistory.mock_test_id == mock_id)
            .group_by(UserAnswer.user_id)
            .subquery()
        )
        result = await self.session.execute(
            select(
                MockTestParticipant.user_id,
                User.display_name,
                User.honor_tag,
                User.star_count, User.star_title,
                func.coalesce(answer_totals.c.correct, 0).label("correct"),
                func.coalesce(answer_totals.c.wrong, 0).label("wrong"),
            )
            .join(User, User.telegram_user_id == MockTestParticipant.user_id)
            .outerjoin(answer_totals, answer_totals.c.user_id == MockTestParticipant.user_id)
            .where(MockTestParticipant.mock_test_id == mock_id)
            .order_by(desc("correct"), answer_totals.c.wrong.asc().nullsfirst(), User.display_name)
        )
        return [dict(row._mapping) for row in result]

    async def save_mock_results(self, mock_id: int, total: int, results: list[dict]) -> list[dict]:
        await self.session.execute(delete(MockTestResult).where(MockTestResult.mock_test_id == mock_id))
        saved: list[dict] = []
        for rank, result in enumerate(results, 1):
            correct = int(result["correct"] or 0)
            wrong = int(result["wrong"] or 0)
            percentage = round(correct * 100 / total, 2) if total else 0.0
            item = MockTestResult(mock_test_id=mock_id, user_id=result["user_id"], correct=correct, wrong=wrong, percentage=percentage, rank=rank)
            self.session.add(item)
            saved.append({**result, "rank": rank, "percentage": percentage})
        await self.session.flush()
        return saved

    async def save_official_draft(self, created_by: int, step: str, payload: dict) -> OfficialQuizDraft:
        draft = await self.session.execute(select(OfficialQuizDraft).where(OfficialQuizDraft.created_by == created_by))
        item = draft.scalar_one_or_none()
        if item is None:
            item = OfficialQuizDraft(created_by=created_by, step=step, payload=payload)
            self.session.add(item)
        else:
            item.step = step
            item.payload = payload
        await self.session.flush()
        return item

    async def get_official_draft(self, created_by: int) -> OfficialQuizDraft | None:
        result = await self.session.execute(select(OfficialQuizDraft).where(OfficialQuizDraft.created_by == created_by))
        return result.scalar_one_or_none()

    async def delete_official_draft(self, created_by: int) -> None:
        await self.session.execute(delete(OfficialQuizDraft).where(OfficialQuizDraft.created_by == created_by))

    async def available_official_question_ids(
        self, *, count: int, source_group_id: int | None = None, state: str | None = None,
    ) -> list[int]:
        conditions = [Question.is_active.is_(True), Question.language == "Hindi"]
        if state:
            conditions.append(or_(Question.state == state, Question.state.in_(["All India", "General"])))
        preferred = list(conditions)
        if source_group_id is not None:
            preferred.append(Question.source_group_id == source_group_id)
        result = await self.session.execute(
            select(Question.id).where(and_(*preferred)).order_by(Question.used_count.asc(), Question.created_at.asc(), Question.id.asc()).limit(count)
        )
        ids = [int(item) for item in result.scalars()]
        if len(ids) < count and source_group_id is not None:
            result = await self.session.execute(
                select(Question.id).where(and_(*conditions)).order_by(Question.used_count.asc(), Question.created_at.asc(), Question.id.asc()).limit(count)
            )
            ids = [int(item) for item in result.scalars()]
        return ids

    async def create_official_quiz(
        self, *, slug: str, quiz_type: str, title: str, rules: str, month_key: str,
        config_group_id: int, play_group_id: int, source_group_id: int | None, question_count: int,
        round_seconds: int, question_ids: list[int], created_by: int,
    ) -> OfficialQuiz:
        quiz = OfficialQuiz(
            slug=slug, quiz_type=quiz_type, title=title, rules=rules, month_key=month_key,
            config_group_id=config_group_id, play_group_id=play_group_id, source_group_id=source_group_id,
            question_count=question_count, round_seconds=round_seconds, question_ids=question_ids,
            created_by=created_by, status="lobby",
        )
        self.session.add(quiz)
        await self.session.flush()
        return quiz

    async def get_official_quiz(self, quiz_id: int) -> OfficialQuiz | None:
        return await self.session.get(OfficialQuiz, quiz_id)

    async def get_official_quiz_by_slug(self, slug: str) -> OfficialQuiz | None:
        result = await self.session.execute(select(OfficialQuiz).where(OfficialQuiz.slug == slug))
        return result.scalar_one_or_none()

    async def join_official_quiz(self, quiz_id: int, user_id: int) -> int:
        participant = OfficialQuizParticipant(quiz_id=quiz_id, user_id=user_id)
        try:
            async with self.session.begin_nested():
                self.session.add(participant)
                await self.session.flush()
        except IntegrityError:
            pass
        result = await self.session.execute(select(func.count(OfficialQuizParticipant.id)).where(OfficialQuizParticipant.quiz_id == quiz_id))
        return int(result.scalar_one() or 0)

    async def clear_active_gsi_honor(self, keep_user_id: int) -> None:
        await self.session.execute(
            update(User).where(
                User.honor_tag == GSI_HONOR_TAG,
                User.telegram_user_id != keep_user_id,
            ).values(honor_tag=None)
        )

    async def clear_active_star_title(self, keep_user_id: int) -> None:
        await self.session.execute(
            update(User).where(
                User.star_title.is_not(None),
                User.telegram_user_id != keep_user_id,
            ).values(star_title=None)
        )

    async def is_official_participant(self, quiz_id: int, user_id: int) -> bool:
        result = await self.session.execute(
            select(OfficialQuizParticipant.id).where(
                and_(OfficialQuizParticipant.quiz_id == quiz_id, OfficialQuizParticipant.user_id == user_id)
            )
        )
        return result.scalar_one_or_none() is not None

    async def official_participant_count(self, quiz_id: int) -> int:
        result = await self.session.execute(select(func.count(OfficialQuizParticipant.id)).where(OfficialQuizParticipant.quiz_id == quiz_id))
        return int(result.scalar_one() or 0)

    async def due_official_countdowns(self, now: datetime) -> list[OfficialQuiz]:
        result = await self.session.execute(
            select(OfficialQuiz).where(and_(OfficialQuiz.status == "countdown", OfficialQuiz.countdown_ends_at.is_not(None), OfficialQuiz.countdown_ends_at <= now))
        )
        return list(result.scalars())

    async def due_official_rounds(self, now: datetime) -> list[OfficialQuiz]:
        result = await self.session.execute(
            select(OfficialQuiz).where(and_(OfficialQuiz.status == "running", OfficialQuiz.round_ends_at.is_not(None), OfficialQuiz.round_ends_at <= now))
        )
        return list(result.scalars())

    async def due_official_tests(self, now: datetime) -> list[OfficialQuiz]:
        result = await self.session.execute(select(OfficialQuiz).where(and_(OfficialQuiz.status == "running", OfficialQuiz.ends_at <= now)))
        return list(result.scalars())

    async def start_official_countdown(self, quiz_id: int, countdown_ends_at: datetime) -> bool:
        result = await self.session.execute(
            update(OfficialQuiz).where(and_(OfficialQuiz.id == quiz_id, OfficialQuiz.status == "lobby")).values(
                status="countdown", countdown_ends_at=countdown_ends_at
            )
        )
        return bool(result.rowcount)

    async def start_official_quiz(self, quiz_id: int, starts_at: datetime, ends_at: datetime) -> bool:
        result = await self.session.execute(
            update(OfficialQuiz).where(and_(OfficialQuiz.id == quiz_id, OfficialQuiz.status == "countdown")).values(
                status="running", starts_at=starts_at, ends_at=ends_at
            )
        )
        return bool(result.rowcount)

    async def official_question_id(self, quiz_id: int, number: int) -> int | None:
        quiz = await self.session.get(OfficialQuiz, quiz_id)
        if quiz is None or number < 1 or number > len(quiz.question_ids):
            return None
        return int(quiz.question_ids[number - 1])

    async def set_official_round(self, quiz_id: int, *, question_number: int, poll_id: str, round_ends_at: datetime) -> None:
        await self.session.execute(
            update(OfficialQuiz).where(OfficialQuiz.id == quiz_id).values(
                current_question_number=question_number, current_poll_id=poll_id, round_ends_at=round_ends_at
            )
        )

    async def mark_official_halfway(self, quiz_id: int) -> bool:
        result = await self.session.execute(
            update(OfficialQuiz).where(and_(OfficialQuiz.id == quiz_id, OfficialQuiz.halfway_sent.is_(False))).values(halfway_sent=True)
        )
        return bool(result.rowcount)

    async def official_results(self, quiz_id: int) -> list[dict]:
        answer_totals = (
            select(
                UserAnswer.user_id.label("user_id"),
                func.sum(case((UserAnswer.is_correct.is_(True), 1), else_=0)).label("correct"),
                func.sum(case((UserAnswer.is_correct.is_(False), 1), else_=0)).label("wrong"),
                func.sum(UserAnswer.points_awarded).label("score"),
            )
            .join(QuizHistory, QuizHistory.telegram_poll_id == UserAnswer.poll_id)
            .where(QuizHistory.official_quiz_id == quiz_id)
            .group_by(UserAnswer.user_id)
            .subquery()
        )
        result = await self.session.execute(
            select(
                OfficialQuizParticipant.user_id, User.display_name, User.username, User.honor_tag,
                User.gsi_wins, User.gsi_achievements, User.star_count, User.star_title,
                func.coalesce(answer_totals.c.correct, 0).label("correct"),
                func.coalesce(answer_totals.c.wrong, 0).label("wrong"),
                func.coalesce(answer_totals.c.score, 0).label("score"),
            )
            .join(User, User.telegram_user_id == OfficialQuizParticipant.user_id)
            .outerjoin(answer_totals, answer_totals.c.user_id == OfficialQuizParticipant.user_id)
            .where(OfficialQuizParticipant.quiz_id == quiz_id)
            .order_by(desc("score"), desc("correct"), User.display_name)
        )
        return [dict(row._mapping) for row in result]

    async def save_official_results(self, quiz_id: int, total: int, results: list[dict], quiz_type: str) -> list[dict]:
        await self.session.execute(delete(OfficialQuizResult).where(OfficialQuizResult.quiz_id == quiz_id))
        saved: list[dict] = []
        for rank, result in enumerate(results, 1):
            correct = int(result["correct"] or 0)
            wrong = int(result["wrong"] or 0)
            score = int(result["score"] or correct)
            percentage = round(correct * 100 / total, 2) if total else 0.0
            award = f"{GSI_HONOR_TAG} Grand Scholar of India" if quiz_type == "gsi" and rank == 1 else ("⭐ Star Quizzer" if quiz_type == "star" and rank == 1 else None)
            item = OfficialQuizResult(quiz_id=quiz_id, user_id=result["user_id"], correct=correct, wrong=wrong, score=score, percentage=percentage, rank=rank, award=award)
            self.session.add(item)
            saved.append({**result, "rank": rank, "percentage": percentage, "award": award})
        await self.session.flush()
        return saved

    async def complete_official_quiz(self, quiz_id: int, winner_user_id: int | None) -> None:
        await self.session.execute(update(OfficialQuiz).where(OfficialQuiz.id == quiz_id).values(status="completed", winner_user_id=winner_user_id))

    async def get_user(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def remove_question(self, question_id: int) -> bool:
        question = await self.session.get(Question, question_id)
        if question is None:
            return False
        await self.session.delete(question)
        return True

    async def commit(self) -> None:
        for attempt in range(4):
            try:
                await self.session.commit()
                return
            except OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 3:
                    raise
                await self.session.rollback()
                await asyncio.sleep(0.25 * (attempt + 1))

    async def rollback(self) -> None:
        await self.session.rollback()

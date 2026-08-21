"""Official GSI and Star Quiz lifecycle service."""
from __future__ import annotations

import asyncio
import html
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.constants import PollType
from sqlalchemy import and_, select, update

from bot.config import (
    GSI_HONOR_MEANING,
    GSI_HONOR_TAG,
    OFFICIAL_QUIZ_CONFIG_GROUP_ID,
    OFFICIAL_QUIZ_PLAY_GROUP_ID,
    STAR_TITLE,
    get_settings,
)
from bot.database.database import Database
from bot.database.models import OfficialQuiz
from bot.database.repositories import Repository
from bot.services.question_validator import normalize_text
from bot.services.quiz import QuizService

logger = logging.getLogger(__name__)


def _language_for_official(question: str, options: list[str]) -> str:
    import re
    return "Hindi" if re.search(r"[\u0900-\u097F]", question + " " + " ".join(options)) else "English"


def _question_type_for_official(question: str) -> str:
    import re
    return "Statement-based" if re.search(r"\bstatements?\b|कथनों|कथन\s*[१२३४1-4]", question, re.IGNORECASE) else "Conceptual"


class OfficialQuizService:
    """Coordinates admin-created official competitions in one configured play group."""

    MIN_COUNT = 2
    MAX_COUNT = 100
    MIN_TIMER = 5
    MAX_TIMER = 180
    COUNTDOWN_SECONDS = 15

    def __init__(self, bot: Bot, database: Database, quiz_service: QuizService) -> None:
        self.bot = bot
        self.database = database
        self.quiz_service = quiz_service
        self._lock = asyncio.Lock()

    @staticmethod
    def config_group_id() -> int:
        return int(get_settings().official_quiz_config_group_id or OFFICIAL_QUIZ_CONFIG_GROUP_ID)

    @staticmethod
    def play_group_id() -> int:
        return int(get_settings().official_quiz_play_group_id or OFFICIAL_QUIZ_PLAY_GROUP_ID)

    @staticmethod
    def lobby_text(quiz, participants: int, language: str = "Hindi") -> str:
        kind = "GSI Quiz" if quiz.quiz_type == "gsi" else "Star Quiz"
        if language == "Hindi":
            return (
                f"🏆 *{kind} — लॉबी खुली है*\n\n"
                f"🎯 *{quiz.title}*\n"
                f"🆔 Quiz ID: `{quiz.slug}`\n"
                f"📝 कुल प्रश्न: *{quiz.question_count}*\n"
                f"⏱ प्रत्येक प्रश्न: *{quiz.round_seconds} सेकंड*\n"
                f"👥 Joined: *{participants}*\n\n"
                f"📜 *Rules*\n{quiz.rules}\n\n"
                "नीचे *Join Quiz* दबाएँ। Admin के *Start Quiz* दबाने के बाद 15 सेकंड countdown होगा।"
            )
        return (
            f"🏆 *{kind} — Lobby Open*\n\n"
            f"🎯 *{quiz.title}*\n"
            f"🆔 Quiz ID: `{quiz.slug}`\n"
            f"📝 Total questions: *{quiz.question_count}*\n"
            f"⏱ Time per question: *{quiz.round_seconds} seconds*\n"
            f"👥 Joined: *{participants}*\n\n"
            f"📜 *Rules*\n{quiz.rules}\n\n"
            "Tap *Join Quiz*. After the admin presses *Start Quiz*, a 15-second countdown will begin."
        )

    @staticmethod
    def lobby_keyboard(quiz_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Join Quiz", callback_data=f"official:join:{quiz_id}"),
            InlineKeyboardButton("🚀 Start Quiz", callback_data=f"official:start:{quiz_id}"),
        ]])

    async def create_quiz(
        self, *, created_by: int, quiz_type: str, slug: str, title: str, rules: str,
        count: int, round_seconds: int, question_items: list[dict],
    ):
        if quiz_type not in {"gsi", "star"}:
            raise ValueError("Quiz type must be GSI or Star")
        if not self.MIN_COUNT <= count <= self.MAX_COUNT:
            raise ValueError(f"Question count must be {self.MIN_COUNT}-{self.MAX_COUNT}")
        if not self.MIN_TIMER <= round_seconds <= self.MAX_TIMER:
            raise ValueError(f"Timer must be {self.MIN_TIMER}-{self.MAX_TIMER} seconds")
        slug = slug.strip().replace(" ", "")
        if not slug or len(slug) > 96:
            raise ValueError("Quiz ID is invalid")
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        async with self.database.session_factory() as session:
            repo = Repository(session)
            if await repo.get_official_quiz_by_slug(slug):
                raise ValueError("This unique Quiz ID already exists")
            if len(question_items) != count:
                raise ValueError(f"Exactly {count} admin-supplied MCQs are required")
            question_ids: list[int] = []
            for item in question_items:
                question = str(item.get("question", "")).strip()
                options = [str(option).strip() for option in item.get("options", [])]
                correct_option = int(item.get("correct_option", -1))
                if not question or len(options) != 4 or any(not option for option in options) or not 0 <= correct_option < 4:
                    raise ValueError("Every supplied MCQ must contain question, exactly 4 options, and a valid answer")
                existing = await repo.question_by_normalized(normalize_text(question))
                if existing is not None:
                    if list(existing.options) != options or int(existing.correct_option) != correct_option:
                        raise ValueError("The supplied MCQ matches an existing question but its options or answer differ")
                    question_ids.append(existing.id)
                    continue
                saved = await repo.add_question(
                    question_text=question, options=options, correct_option=correct_option,
                    explanation=f"Official quiz answer: option {chr(ord('A') + correct_option)}",
                    key_point="Answer preserved exactly from the admin-supplied official MCQ.",
                    state="All India", subject="General Knowledge", topic=title.strip(),
                    difficulty="Exam", question_type=_question_type_for_official(question),
                    language=_language_for_official(question, options), source="official_quiz",
                    source_group_id=self.config_group_id(),
                )
                question_ids.append(saved.id)
            await repo.ensure_group(self.play_group_id(), "Official Quiz Group", "supergroup")
            quiz = await repo.create_official_quiz(
                slug=slug, quiz_type=quiz_type, title=title.strip(), rules=rules.strip(), month_key=month_key,
                config_group_id=self.config_group_id(), play_group_id=self.play_group_id(), source_group_id=self.config_group_id(),
                question_count=count, round_seconds=round_seconds, question_ids=question_ids, created_by=created_by,
            )
            await repo.commit()
            return quiz

    async def launch(self, slug: str) -> tuple[bool, str]:
        async with self.database.session_factory() as session:
            repo = Repository(session)
            quiz = await repo.get_official_quiz_by_slug(slug.strip())
            if quiz is None:
                return False, "यह Quiz ID नहीं मिली। पहले /createquiz से quiz बनाएँ।"
            if quiz.status != "lobby":
                return False, "यह quiz पहले ही launch या complete हो चुकी है।"
            participants = await repo.official_participant_count(quiz.id)
            await repo.commit()
        await self._send_message_retry(
            chat_id=quiz.play_group_id,
            text=self.lobby_text(quiz, participants),
            reply_markup=self.lobby_keyboard(quiz.id),
            parse_mode=ParseMode.MARKDOWN,
        )
        return True, f"✅ {quiz.title} की lobby official play group में खोल दी गई है।"

    async def join(self, quiz_id: int, user_id: int, username: str | None, display_name: str) -> tuple[object | None, int]:
        async with self.database.session_factory() as session:
            repo = Repository(session)
            quiz = await repo.get_official_quiz(quiz_id)
            if quiz is None or quiz.status != "lobby":
                return None, 0
            await repo.upsert_user(user_id, username, display_name)
            count = await repo.join_official_quiz(quiz_id, user_id)
            await repo.commit()
            return quiz, count

    async def begin_countdown(self, quiz_id: int) -> tuple[object | None, int, str | None]:
        async with self.database.session_factory() as session:
            repo = Repository(session)
            quiz = await repo.get_official_quiz(quiz_id)
            if quiz is None or quiz.status != "lobby":
                return None, 0, "यह lobby अब उपलब्ध नहीं है।"
            participants = await repo.official_participant_count(quiz_id)
            if participants < 1:
                return quiz, participants, "कम से कम एक participant के Join करने के बाद Start करें।"
            ends = datetime.now(timezone.utc) + timedelta(seconds=self.COUNTDOWN_SECONDS)
            if not await repo.start_official_countdown(quiz_id, ends):
                return quiz, participants, "Quiz पहले ही start process में है।"
            await repo.commit()
            return quiz, participants, None

    async def start_after_countdown(self, quiz_id: int) -> bool:
        async with self._lock:
            async with self.database.session_factory() as session:
                repo = Repository(session)
                quiz = await repo.get_official_quiz(quiz_id)
                if quiz is None or quiz.status != "countdown":
                    return False
                now = datetime.now(timezone.utc)
                ends = now + timedelta(seconds=quiz.question_count * quiz.round_seconds + 60)
                await repo.start_official_quiz(quiz_id, now, ends)
                await repo.commit()
        await self._send_message_retry(
            chat_id=quiz.play_group_id,
            text=(
                f"🚀 *{('GSI Quiz' if quiz.quiz_type == 'gsi' else 'Star Quiz')} शुरू हो गया!*\n\n"
                f"🎯 {quiz.title}\n📝 कुल प्रश्न: *{quiz.question_count}*\n"
                f"⏱ प्रत्येक प्रश्न: *{quiz.round_seconds} सेकंड*\n\n"
                "हर प्रश्न में progress number दिखाई देगा। शुभकामनाएँ!"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return await self.send_next_round(quiz_id)

    async def send_next_round(self, quiz_id: int) -> bool:
        async with self._lock:
            async with self.database.session_factory() as session:
                repo = Repository(session)
                quiz = await repo.get_official_quiz(quiz_id)
                if quiz is None or quiz.status != "running":
                    return False
                number = quiz.current_question_number + 1
                if number > quiz.question_count:
                    return False
                question_id = await repo.official_question_id(quiz_id, number)
                question = await repo.get_question(question_id) if question_id else None
                if question is None:
                    await repo.complete_official_quiz(quiz_id, None)
                    await repo.commit()
                    await self._send_message_retry(chat_id=quiz.play_group_id, text="⚠️ इस official quiz का प्रश्न उपलब्ध नहीं मिला, इसलिए quiz रोक दी गई।")
                    return False
                closes_at = datetime.now(timezone.utc) + timedelta(seconds=quiz.round_seconds)
                poll_question, poll_options = self.quiz_service.poll_content(question, "Hindi", (number, quiz.question_count))
                if not self.quiz_service.uses_single_poll_layout(question):
                    await self._send_message_retry(
                        chat_id=quiz.play_group_id,
                        text=self.quiz_service.full_question_card(question, "Hindi", (number, quiz.question_count)),
                    )
                message = await self._send_poll_retry(
                    chat_id=quiz.play_group_id, question=poll_question, options=poll_options,
                    type=PollType.QUIZ, is_anonymous=False, correct_option_id=question.correct_option,
                    open_period=quiz.round_seconds,
                )
                await repo.record_quiz(
                    group_id=quiz.play_group_id, question_id=question.id, poll_id=message.poll.id,
                    message_id=message.message_id, quiz_kind=f"official_{quiz.quiz_type}", closes_at=closes_at,
                    official_quiz_id=quiz.id, official_question_number=number,
                )
                await repo.set_official_round(quiz.id, question_number=number, poll_id=message.poll.id, round_ends_at=closes_at)
                # If the scheduler was delayed, do not let the old overall deadline
                # finalize the quiz immediately after this recovered round starts.
                deadline = closes_at + timedelta(seconds=60)
                await session.execute(
                    update(OfficialQuiz).where(OfficialQuiz.id == quiz.id).values(ends_at=deadline)
                )
                await repo.commit()
                return True

    @staticmethod
    def _standings_text(quiz, standings: list[dict], completed_questions: int, halfway: bool = True) -> str:
        kind = "GSI Quiz" if quiz.quiz_type == "gsi" else "Star Quiz"
        title = "50% Live Standings" if halfway else "Final Live Standings"
        lines = [
            f"📊 <b>{html.escape(kind)} — {title}</b>",
            f"🎯 <b>{html.escape(quiz.title)}</b>",
            f"✅ Questions completed: <b>{completed_questions}/{quiz.question_count}</b>",
            f"👥 Participants: <b>{len(standings)}</b>",
            "",
        ]
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        if not standings:
            lines.append("अभी किसी participant का answer record नहीं हुआ है।")
        else:
            for rank, row in enumerate(standings[:10], 1):
                correct = int(row.get("correct") or 0)
                wrong = int(row.get("wrong") or 0)
                prefix = OfficialQuizService._honor_prefix(row)
                mention = OfficialQuizService._mention(row)
                name = f"{prefix} {mention}".strip() if prefix else mention
                lines.append(
                    f"{medals.get(rank, f'{rank}.')} {name} — "
                    f"<b>{int(row.get('score') or 0)} pts</b>  •  सही: {correct}  •  गलत: {wrong}"
                )
            if len(standings) > 10:
                lines.append(f"\n… और {len(standings) - 10} participants")
        lines.extend(["", "🔥 आगे रहने के लिए accuracy और speed दोनों बनाए रखें!"])
        return "\n".join(lines)

    async def advance_round(self, quiz_id: int) -> bool:
        async with self.database.session_factory() as session:
            repo = Repository(session)
            quiz = await repo.get_official_quiz(quiz_id)
            if quiz is None or quiz.status != "running":
                return False
            poll_id = quiz.current_poll_id
            number = quiz.current_question_number
        if poll_id:
            await self.quiz_service.close_quiz_and_explain(0, poll_id)
        halfway_text: str | None = None
        if number >= max(1, (quiz.question_count + 1) // 2):
            async with self.database.session_factory() as session:
                repo = Repository(session)
                current = await repo.get_official_quiz(quiz_id)
                if current is not None and not current.halfway_sent and await repo.mark_official_halfway(quiz_id):
                    standings = await repo.official_results(quiz_id)
                    halfway_text = self._standings_text(current, standings, number, halfway=True)
                    await repo.commit()
        if halfway_text:
            await self._send_message_retry(chat_id=quiz.play_group_id, text=halfway_text, parse_mode=ParseMode.HTML)
        if number >= quiz.question_count:
            return False
        return await self.send_next_round(quiz_id)

    async def finalize(self, quiz_id: int) -> None:
        async with self.database.session_factory() as session:
            repo = Repository(session)
            quiz = await repo.get_official_quiz(quiz_id)
            # Finalization is a one-shot operation. Once the scheduler has
            # marked the quiz completed, duplicate ticks must not resend media
            # or the winner announcement.
            if quiz is None or quiz.status != "running":
                return
            was_running = True
            results = await repo.official_results(quiz_id)
            ranked = await repo.save_official_results(quiz_id, quiz.question_count, results, quiz.quiz_type)
            winner_id = int(ranked[0]["user_id"]) if ranked else None
            if was_running:
                await repo.complete_official_quiz(quiz_id, winner_id)
            winner = await repo.get_user(winner_id) if winner_id else None
            if was_running and winner and ranked:
                if quiz.quiz_type == "gsi":
                    # GSI is an active current-winner tag; the achievement list
                    # below remains permanent for every previous winner.
                    await repo.clear_active_gsi_honor(winner.telegram_user_id)
                    winner.honor_tag = GSI_HONOR_TAG
                    winner.gsi_wins += 1
                    achievements = list(winner.gsi_achievements or [])
                    if quiz.slug not in achievements:
                        achievements.append(quiz.slug)
                    winner.gsi_achievements = achievements
                else:
                    # Star Quizzer is an active current-winner title. The
                    # cumulative star_count remains permanent on every winner.
                    await repo.clear_active_star_title(winner.telegram_user_id)
                    winner.star_count += 1
                    winner.star_title = f"{STAR_TITLE} ×{winner.star_count}"
            await repo.commit()
        await self._send_result(quiz, ranked, winner)

    async def _send_message_retry(self, **kwargs):
        for attempt in range(4):
            try:
                return await self.bot.send_message(**kwargs)
            except RetryAfter as exc:
                if attempt == 3:
                    raise
                await asyncio.sleep(max(0.5, min(float(exc.retry_after), 60.0)))
            except (TimedOut, NetworkError, TelegramError):
                if attempt == 3:
                    raise
                await asyncio.sleep(1.0 + attempt)
        return None

    async def _send_poll_retry(self, **kwargs):
        for attempt in range(4):
            try:
                return await self.bot.send_poll(**kwargs)
            except RetryAfter as exc:
                if attempt == 3:
                    raise
                await asyncio.sleep(max(0.5, min(float(exc.retry_after), 60.0)))
            except (TimedOut, NetworkError, TelegramError):
                if attempt == 3:
                    raise
                await asyncio.sleep(1.0 + attempt)
        return None

    async def _send_photo_file_retry(self, path: Path, **kwargs):
        for attempt in range(3):
            try:
                with path.open("rb") as photo:
                    return await self.bot.send_photo(photo=photo, **kwargs)
            except RetryAfter as exc:
                if attempt == 2:
                    raise
                await asyncio.sleep(max(0.5, min(float(exc.retry_after), 60.0)))
            except (TimedOut, NetworkError, TelegramError):
                if attempt == 2:
                    raise
                await asyncio.sleep(1.0 + attempt)
        return None

    async def _send_sticker_file_retry(self, path: Path, send_sticker, **kwargs):
        for attempt in range(3):
            try:
                with path.open("rb") as sticker:
                    return await send_sticker(sticker=sticker, **kwargs)
            except RetryAfter as exc:
                if attempt == 2:
                    raise
                await asyncio.sleep(max(0.5, min(float(exc.retry_after), 60.0)))
            except (TimedOut, NetworkError, TelegramError):
                if attempt == 2:
                    raise
                await asyncio.sleep(1.0 + attempt)
        return None

    @staticmethod
    def _mention(row: dict) -> str:
        name = html.escape(str(row.get("display_name") or "Student"))
        return f'<a href="tg://user?id={int(row["user_id"])}">{name}</a>'

    @staticmethod
    def _render_gsi_winner_card(template_path: Path, display_name: str) -> Path | None:
        """Render the exact winner display name into the supplied GSI card."""
        try:
            from PIL import Image, ImageDraw, ImageFont

            image = Image.open(template_path).convert("RGBA")
            draw = ImageDraw.Draw(image)
            width, height = image.size
            scale_x, scale_y = width / 1198, height / 1313
            left, top, right, bottom = (
                int(300 * scale_x), int(645 * scale_y), int(900 * scale_x), int(770 * scale_y)
            )
            for y in range(top, bottom):
                ratio = (y - top) / max(1, bottom - top - 1)
                color = (int(250 - 7 * ratio), int(235 - 10 * ratio), int(198 - 12 * ratio), 255)
                draw.line((left, y, right, y), fill=color, width=1)

            font_candidates = (
                "/usr/share/fonts/truetype/noto/NotoSansDevanagari-CondensedBlack.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            )
            font_path = next((path for path in font_candidates if Path(path).exists()), None)
            if not font_path:
                raise RuntimeError("No suitable winner-name font is installed")
            clean_name = " ".join(str(display_name or "GSI Winner").split()) or "GSI Winner"
            max_width = right - left - int(40 * scale_x)
            font = None
            for size in range(int(82 * scale_y), int(30 * scale_y) - 1, -2):
                candidate = ImageFont.truetype(font_path, size)
                bbox = draw.textbbox((0, 0), clean_name, font=candidate)
                if bbox[2] - bbox[0] <= max_width:
                    font = candidate
                    break
            font = font or ImageFont.truetype(font_path, int(30 * scale_y))
            draw.text(
                ((left + right) // 2, int(704 * scale_y)), clean_name, font=font, anchor="mm",
                fill=(6, 24, 53, 255), stroke_width=max(1, int(scale_x)),
                stroke_fill=(6, 24, 53, 255),
            )
            with tempfile.NamedTemporaryFile(prefix="gsi_winner_", suffix=".png", delete=False) as temp_file:
                output = Path(temp_file.name)
            image.save(output, format="PNG")
            return output
        except Exception:
            logger.warning("Could not render GSI winner name into congratulations template", exc_info=True)
            return None

    @staticmethod
    def _honor_prefix(row: dict, fallback: str | None = None) -> str:
        items: list[str] = []
        if row.get("honor_tag"):
            items.append(str(row["honor_tag"]))
        star_title = str(row.get("star_title") or "").strip()
        if star_title:
            items.append(f"⭐ {star_title}")
        if not items and fallback:
            items.append(fallback)
        return " ".join(html.escape(item) for item in items)

    async def _send_result(self, quiz, ranked: list[dict], winner) -> None:
        winner_row = ranked[0] if ranked else None
        star_count = int(getattr(winner, "star_count", 0) or 0) if winner is not None else 1
        tag = GSI_HONOR_TAG if quiz.quiz_type == "gsi" else f"⭐ {STAR_TITLE} ×{max(1, star_count)}"
        kind = "GSI Quiz" if quiz.quiz_type == "gsi" else "Star Quiz"
        lines = [
            f"🏆 <b>{html.escape(kind)} — ELITE CHAMPIONSHIP SCOREBOARD</b>",
            f"🎯 <b>{html.escape(quiz.title)}</b>",
            f"🆔 Quiz ID: <code>{html.escape(quiz.slug)}</code>",
            "",
            f"📊 <b>Final Summary</b>  •  Questions: <b>{quiz.question_count}</b>  •  Participants: <b>{len(ranked)}</b>",
            f"🏅 Maximum score: <b>{quiz.question_count} points</b>",
            "",
            "<b>RANKING</b>",
        ]
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for row in ranked[:20]:
            row_tag = OfficialQuizService._honor_prefix(row, tag if row["rank"] == 1 else None)
            row_tag = f"{row_tag} " if row_tag else ""
            correct = int(row.get("correct") or 0)
            wrong = int(row.get("wrong") or 0)
            lines.append(
                f"{medals.get(row['rank'], str(row['rank']) + '.')} {row_tag}{self._mention(row)}\n"
                f"   🎯 Score: <b>{row['score']}/{quiz.question_count}</b>  •  Accuracy: <b>{row['percentage']}%</b>\n"
                f"   ✅ Correct: <b>{correct}</b>  •  ❌ Wrong: <b>{wrong}</b>"
            )
        if len(ranked) > 20:
            lines.append(f"\n… and {len(ranked) - 20} more participants")
        if winner_row:
            lines.extend([
                "",
                f"👑 <b>ELITE WINNER</b>",
                f"🎉 {tag} {self._mention(winner_row)}",
                "Congratulations on leading the official competition!",
            ])
        else:
            lines.extend(["", "No participant submitted an answer."])
        await self._send_message_retry(chat_id=quiz.play_group_id, text="\n".join(lines), parse_mode=ParseMode.HTML)
        if winner_row:
            await self._send_winner_media(quiz, winner_row, winner)

    async def _send_winner_media(self, quiz, winner_row: dict, winner=None) -> None:
        winner_mention = self._mention(winner_row)
        if quiz.quiz_type == "gsi":
            caption = f"🎉 Congratulations {winner_mention}!\n\n{GSI_HONOR_TAG} — {GSI_HONOR_MEANING}"
            destinations = self._winner_media_destinations()
        else:
            star_count = int(getattr(winner, "star_count", 0) or 1) if winner is not None else 1
            caption = (
                f"🎉 Congratulations {winner_mention}!\n\n"
                f"⭐ You earned Star #{star_count} and the title <b>{STAR_TITLE} ×{star_count}</b>."
            )
            destinations = self._winner_media_destinations()
        root = Path(__file__).resolve().parents[2] / "assets"
        image_path = root / ("gsi_winner_congratulations.png" if quiz.quiz_type == "gsi" else "star_winner_congratulations.png")
        rendered_image_path: Path | None = None
        if quiz.quiz_type == "gsi":
            template_path = root / "gsi_winner_template.png"
            if template_path.exists():
                winner_name = (
                    getattr(winner, "display_name", None) if winner is not None else None
                ) or winner_row.get("display_name") or "GSI Winner"
                rendered_image_path = self._render_gsi_winner_card(template_path, str(winner_name))
                if rendered_image_path:
                    image_path = rendered_image_path
        sticker_path = root / ("gsi_winner_sticker.webm" if quiz.quiz_type == "gsi" else "star_winner_sticker.webm")
        for chat_id in destinations:
            if image_path.exists():
                try:
                    await self._send_photo_file_retry(
                        image_path, chat_id=chat_id, caption=caption, parse_mode=ParseMode.HTML,
                    )
                except TelegramError:
                    logger.warning("Could not deliver official winner card to %s", chat_id, exc_info=True)
            else:
                try:
                    await self._send_message_retry(chat_id=chat_id, text=caption, parse_mode=ParseMode.HTML)
                except TelegramError:
                    logger.warning("Could not deliver official winner caption to %s", chat_id, exc_info=True)
            send_sticker = getattr(self.bot, "send_sticker", None)
            if sticker_path.exists() and callable(send_sticker):
                try:
                    await self._send_sticker_file_retry(sticker_path, send_sticker, chat_id=chat_id)
                except TelegramError:
                    logger.warning("Sticker delivery failed for %s; no animation fallback is configured", chat_id, exc_info=True)
            try:
                await self._send_message_retry(
                    chat_id=chat_id,
                    text=self._participant_congratulations_text(quiz.quiz_type),
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                logger.warning("Participant congratulations message failed for %s", chat_id, exc_info=True)
            if chat_id == self.play_group_id():
                try:
                    await self._send_message_retry(
                        chat_id=chat_id,
                        text=self._title_transfer_announcement_text(quiz.quiz_type, winner_row, winner),
                        parse_mode=ParseMode.HTML,
                    )
                except TelegramError:
                    logger.warning("Title-transfer announcement failed for %s", chat_id, exc_info=True)
            await asyncio.sleep(0.05)
        if rendered_image_path:
            rendered_image_path.unlink(missing_ok=True)

    @staticmethod
    def _title_transfer_announcement_text(quiz_type: str, winner_row: dict, winner=None) -> str:
        winner_name = OfficialQuizService._mention(winner_row)
        if quiz_type == "gsi":
            return (
                "<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
                "<b>✨ OFFICIAL TITLE TRANSFER ✨</b>\n"
                "<b>━━━━━━━━━━━━━━━━━━━━</b>\n\n"
                f"🎖️ <b>नया GSI सम्मान अब {winner_name} के नाम है!</b>\n\n"
                f"👑 <b>{html.escape(GSI_HONOR_TAG)}</b>\n"
                f"<b>{html.escape(GSI_HONOR_MEANING)}</b>\n\n"
                "यह tag अब पूरे bot में नए विजेता के नाम के आगे दिखाई देगा।\n"
                "पिछले विजेता की जीत और achievement सुरक्षित रहेगी।\n\n"
                "<b>🏆 Official GSI Quiz Champion</b>"
            )
        star_count = int(getattr(winner, "star_count", 0) or winner_row.get("star_count") or 1)
        return (
            "<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
            "<b>✨ OFFICIAL TITLE TRANSFER ✨</b>\n"
            "<b>━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            f"🎖️ <b>Star Quizzer का नया title अब {winner_name} के नाम है!</b>\n\n"
            f"⭐ <b>{html.escape(STAR_TITLE)} ×{star_count}</b>\n\n"
            "यह title अब पूरे bot में नए विजेता की profile के साथ दिखाई देगा।\n"
            "पिछले विजेता के earned stars और achievements सुरक्षित रहेंगे।\n\n"
            "<b>🏆 Official Star Quiz Champion</b>"
        )

    @staticmethod
    def _participant_congratulations_text(quiz_type: str) -> str:
        label = "GSI QUIZ" if quiz_type == "gsi" else "STAR ⭐ QUIZ"
        return (
            f"<b>🏆 {label} में भाग लेने वाले सभी प्रतिभागियों को हार्दिक बधाई! 🎉</b>\n"
            "<b>🌟 सीखते रहिए • प्रयास करते रहिए • आगे बढ़ते रहिए</b>"
        )

    def _winner_media_destinations(self) -> list[int]:
        """Automatic official media recipients; later admin broadcast remains separate."""
        admin_ids = get_settings().global_admin_ids
        return sorted({self.play_group_id(), *admin_ids})

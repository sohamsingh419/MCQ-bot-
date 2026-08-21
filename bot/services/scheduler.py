"""Async scheduler that isolates failures to a group or job."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError

from bot.config import STAR_TITLE, Settings
from bot.database.database import Database
from bot.database.repositories import Repository
from bot.services.quiz import QuizService

logger = logging.getLogger(__name__)

ADMIN_REMINDER_DELAYS_MINUTES = (10, 60, 120, 360, 720, 1440, 2880)


def admin_readiness_reminder_text(language: str = "Hindi") -> str:
    hindi = (
        "⚠️ <b>Bot को Admin बनाना आवश्यक है!</b>\n"
        "इस ग्रुप में bot अभी तक Admin नहीं है। कृपया bot को Admin बनाइए, तभी quiz और सभी features काम करेंगे।"
    )
    english = (
        "⚠️ <b>Bot needs Admin permissions!</b>\n"
        "The bot is not an admin in this group yet. Please make the bot an admin to enable quizzes and all features."
    )
    return f"{hindi}\n\n{english}" if language != "English" else f"{english}\n\n{hindi}"


DAILY_MOTIVATIONS = (
    "हर छोटा प्रयास आपकी बड़ी सफलता की नींव बनता है।",
    "आज की मेहनत ही कल की पहचान बनेगी—सीखते रहिए।",
    "ज्ञान की दिशा में उठाया गया हर कदम आपको मंज़िल के करीब लाता है।",
    "धीमी प्रगति भी प्रगति है—बस रुकना मत।",
    "आपका अनुशासन आपकी सबसे बड़ी ताकत है।",
    "जो आज सीखते हैं, वही कल आत्मविश्वास से आगे बढ़ते हैं।",
    "सपने तभी सच होते हैं जब प्रयास रोज़ किया जाए।",
    "गलतियाँ रुकावट नहीं, बेहतर तैयारी का रास्ता हैं।",
    "हर प्रश्न आपको परीक्षा और सफलता दोनों के लिए मजबूत बनाता है।",
    "मेहनत का कोई सही समय नहीं—लेकिन शुरुआत का समय अभी है।",
    "अपने लक्ष्य पर विश्वास रखिए और रोज़ एक कदम आगे बढ़िए।",
    "आज का एक घंटा आपकी कल की जीत बदल सकता है।",
    "ज्ञान बाँटने और सीखने से सफलता और भी सुंदर बनती है।",
    "आप जितना प्रयास करेंगे, उतना ही आत्मविश्वास बढ़ेगा।",
)


class SchedulerService:
    def __init__(self, database: Database, quiz_service: QuizService, settings: Settings, official_quiz_service=None) -> None:
        self.database = database
        self.quiz_service = quiz_service
        self.settings = settings
        self.official_quiz_service = official_quiz_service
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._daily_seen: set[tuple[int, str]] = set()
        self._weekly_seen: set[tuple[int, str]] = set()
        self._pool_running: set[int] = set()
        self._pool_cursor = 0
        self._routine_seen: set[tuple[str, str]] = set()

    @staticmethod
    def _mock_round_has_expired(mock, now: datetime) -> bool:
        round_ends_at = mock.round_ends_at
        if round_ends_at is None:
            return True
        if round_ends_at.tzinfo is None:
            round_ends_at = round_ends_at.replace(tzinfo=timezone.utc)
        return round_ends_at <= now

    async def start(self) -> None:
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="quiz-scheduler")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._pool_running.clear()

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.tick()
            except Exception:
                logger.exception("Scheduler tick failed without stopping the bot")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.settings.scheduler_tick_seconds)
            except asyncio.TimeoutError:
                pass

    def _local_now(self, now: datetime) -> datetime:
        try:
            zone = ZoneInfo(self.settings.timezone)
        except (ZoneInfoNotFoundError, AttributeError):
            zone = timezone.utc
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(zone)

    @staticmethod
    def is_quiet_hours(local_now: datetime) -> bool:
        return 0 <= local_now.hour < 7

    @staticmethod
    def _motivation_for_date(local_date) -> str:
        return DAILY_MOTIVATIONS[local_date.toordinal() % len(DAILY_MOTIVATIONS)]

    @classmethod
    def _routine_message(cls, slot: str, local_date) -> str:
        motivation = cls._motivation_for_date(local_date)
        if slot == "night":
            return (
                "🌙✨ <b>आज की प्रेरणा</b> ✨🌙\n\n"
                f"<b>“{motivation}”</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🌌 <b>Good night, all friends!</b> 🌌"
            )
        return (
            "🌅✨ <b>आज की प्रेरणा</b> ✨🌅\n\n"
            f"<b>“{motivation}”</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "☀️ <b>Good morning, friends!</b> ☀️"
        )

    async def _send_routine_message_if_due(self, local_now: datetime) -> None:
        slot: str | None = None
        if local_now.hour == 0 and local_now.minute == 0:
            slot = "night"
        elif local_now.hour == 7 and local_now.minute == 0:
            slot = "morning"
        if slot is None:
            return
        key = (local_now.date().isoformat(), slot)
        if key in self._routine_seen:
            return
        async with self.database.session_factory() as session:
            recipients = await Repository(session).audience_chat_ids("both")
        message = self._routine_message(slot, local_now.date())
        for chat_id in recipients:
            try:
                await self.quiz_service.bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
            except TelegramError:
                logger.warning("Could not send %s routine message to %s", slot, chat_id, exc_info=True)
            await asyncio.sleep(0.05)
        self._routine_seen.add(key)
        # Keep the in-memory idempotency set bounded across long-running uptime.
        if len(self._routine_seen) > 10:
            self._routine_seen = {item for item in self._routine_seen if item[0] >= local_now.date().isoformat()}

    async def _send_admin_readiness_reminders(self, now: datetime) -> None:
        """Send at most the latest due reminder per group and persist its stage."""
        async with self.database.session_factory() as session:
            repo = Repository(session)
            waiting = await repo.groups_awaiting_bot_admin()
            reminder_jobs: list[tuple[int, str]] = []
            for group_settings in waiting:
                joined_at = group_settings.bot_joined_at
                if joined_at is None:
                    continue
                if joined_at.tzinfo is None:
                    joined_at = joined_at.replace(tzinfo=timezone.utc)
                try:
                    bot_user = await self.quiz_service.bot.get_me()
                    member = await self.quiz_service.bot.get_chat_member(group_settings.group_id, bot_user.id)
                    if member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}:
                        group_settings.bot_is_admin = True
                        group_settings.admin_reminder_stage = 8
                        group_settings.admin_reminder_sent_at = now
                        continue
                except Exception:
                    # A failed rights check is non-fatal; the bot may still be
                    # able to send a reminder, and membership updates correct
                    # the cache when Telegram delivers them.
                    pass
                elapsed_minutes = max(0, int((now - joined_at).total_seconds() // 60))
                due_stage = min(
                    sum(elapsed_minutes >= delay for delay in ADMIN_REMINDER_DELAYS_MINUTES),
                    len(ADMIN_REMINDER_DELAYS_MINUTES),
                )
                current_stage = max(0, int(group_settings.admin_reminder_stage or 0))
                if due_stage <= current_stage or due_stage <= 0:
                    continue
                # If the process was offline, skip stale intermediate sends and
                # issue only the latest due reminder. Stage 7 is the final one.
                group_settings.admin_reminder_stage = due_stage
                group_settings.admin_reminder_sent_at = now
                reminder_jobs.append((group_settings.group_id, group_settings.language or "Hindi"))
            await repo.commit()

        for group_id, language in reminder_jobs:
            try:
                await self.quiz_service.bot.send_message(
                    chat_id=group_id,
                    text=admin_readiness_reminder_text(language),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except TelegramError:
                logger.warning("Could not send bot-admin reminder to %s", group_id, exc_info=True)

    async def tick(self) -> None:
        now = datetime.now(timezone.utc)
        local_now = self._local_now(now)
        await self._send_admin_readiness_reminders(now)
        await self._send_routine_message_if_due(local_now)
        async with self.database.session_factory() as session:
            repo = Repository(session)
            active_mock_groups = await repo.active_mock_group_ids()
            due = [item for item in await repo.due_group_settings(now) if item.group_id not in active_mock_groups]
            closing = await repo.unanswered_open_quizzes(now)
            expiring_mocks = await repo.due_mock_tests(now)
            starting_lobbies = await repo.due_mock_lobbies(now)
            advancing_rounds = await repo.due_mock_rounds(now)
        quiet_hours = self.is_quiet_hours(local_now)
        if quiet_hours:
            # Regular automatic questions, including private-DM practice,
            # are paused until 07:00 local time. Official competitions and
            # already-running Mock Tests retain their own lifecycle handling.
            due = []
            closing = []

        # Official competitions and active Mock Tests must advance before
        # regular groups, because regular AI generation can take many seconds.
        if self.official_quiz_service is not None:
            await self._tick_official_quizzes(now)
        for mock in starting_lobbies:
            await self.quiz_service.start_mock_test(mock.id)
        advanced_mock_ids: set[int] = set()
        for mock in advancing_rounds:
            advanced = await self.quiz_service.advance_mock_round(mock.id)
            if advanced:
                advanced_mock_ids.add(mock.id)
            elif mock.current_question_number >= mock.question_count:
                await self.finalize_mock_test(mock.id)
        for mock in expiring_mocks:
            if mock.id in advanced_mock_ids:
                continue
            # If a delayed round has not reached the configured question count,
            # keep the mock alive; the next tick will retry delivery.
            if mock.current_question_number < mock.question_count:
                continue
            # The overall deadline can be older than the final poll deadline
            # after a slow delivery. Never post results while that final timer
            # is still open.
            if not self._mock_round_has_expired(mock, now):
                continue
            await self.finalize_mock_test(mock.id)

        await asyncio.gather(*(self.quiz_service.send_quiz(item.group_id) for item in due), return_exceptions=True)
        if getattr(self.settings, "question_pool_enabled", True):
            async with self.database.session_factory() as session:
                active_for_pool = await Repository(session).active_group_settings_for_types(["group", "supergroup"])
            active_for_pool.sort(key=lambda item: item.group_id)
            if active_for_pool:
                start = self._pool_cursor % len(active_for_pool)
                ordered = active_for_pool[start:] + active_for_pool[:start]
                self._pool_cursor = (start + int(getattr(self.settings, "question_pool_max_groups_per_tick", 2))) % len(active_for_pool)
                for item in ordered[: int(getattr(self.settings, "question_pool_max_groups_per_tick", 2))]:
                    if item.group_id in self._pool_running:
                        continue
                    self._pool_running.add(item.group_id)
                    asyncio.create_task(self._warm_pool_group(item.group_id), name=f"pool-warm-{item.group_id}")
        for history in closing:
            await self.quiz_service.close_quiz_and_explain(history.id, history.telegram_poll_id)
            await asyncio.sleep(0.08)
        await self._launch_periodic_specials(now)

    async def _tick_official_quizzes(self, now: datetime) -> None:
        service = self.official_quiz_service
        async with self.database.session_factory() as session:
            repo = Repository(session)
            countdowns = await repo.due_official_countdowns(now)
            rounds = await repo.due_official_rounds(now)
            expiring = await repo.due_official_tests(now)
        for quiz in countdowns:
            await service.start_after_countdown(quiz.id)
        finalized_ids: set[int] = set()
        advanced_ids: set[int] = set()
        for quiz in rounds:
            advanced = await service.advance_round(quiz.id)
            if advanced:
                advanced_ids.add(quiz.id)
            elif quiz.current_question_number >= quiz.question_count:
                await service.finalize(quiz.id)
                finalized_ids.add(quiz.id)
        for quiz in expiring:
            # The expiration snapshot may have been taken before a delayed round
            # advanced. Never finalize that quiz in the same scheduler tick.
            if quiz.id in advanced_ids or quiz.id in finalized_ids:
                continue
            await service.finalize(quiz.id)

    async def _warm_pool_group(self, group_id: int) -> None:
        try:
            await self.quiz_service.warm_question_pool(group_id)
        except Exception:
            logger.exception("Question pool warm task failed for group %s", group_id)
        finally:
            self._pool_running.discard(group_id)

    async def _launch_periodic_specials(self, now: datetime) -> None:
        """Daily at 08:00 UTC and weekly Sunday 10:00 UTC; database uniqueness prevents duplicate daily items."""
        if now.hour == 8 and now.minute == 0:
            async with self.database.session_factory() as session:
                repo = Repository(session)
                settings = await repo.active_group_settings_for_types(["group", "supergroup"])
            for setting in settings:
                key = (setting.group_id, now.date().isoformat())
                if key not in self._daily_seen:
                    self._daily_seen.add(key)
                    asyncio.create_task(self.quiz_service.send_daily_challenge(setting.group_id), name=f"daily-{setting.group_id}")
        if now.weekday() == 6 and now.hour == 10 and now.minute == 0:
            async with self.database.session_factory() as session:
                repo = Repository(session)
                groups = await repo.active_group_settings_for_types(["group", "supergroup"])
                eligible = [(item.group_id, not await repo.has_mock_started_on(item.group_id, "Weekly Mega Mock Test", now.date())) for item in groups]
            for group_id, not_started in eligible:
                key = (group_id, now.date().isoformat())
                if not_started and key not in self._weekly_seen:
                    self._weekly_seen.add(key)
                    asyncio.create_task(
                        self.quiz_service.create_mock_lobby(
                            group_id, count=20, round_seconds=30, title="Weekly Mega Mock Test", created_by=0
                        ), name=f"weekly-{group_id}",
                    )

    async def finalize_mock_test(self, mock_id: int) -> None:
        async with self.database.session_factory() as session:
            repo = Repository(session)
            mock = await session.get(__import__("bot.database.models", fromlist=["MockTest"]).MockTest, mock_id)
            if mock is None or mock.status != "running":
                return
            results = await repo.mock_results(mock_id)
            ranked = await repo.save_mock_results(mock_id, mock.question_count, results)
            settings = await repo.get_settings(mock.group_id)
            ui_language = settings.language if settings is not None else "Hindi"
            await repo.complete_mock_test(mock_id)
            await repo.commit()
        try:
            if not ranked:
                text = (
                    f"{mock.title} समाप्त। किसी participant का result record नहीं हुआ।"
                    if ui_language == "Hindi" else f"{mock.title} ended. No participant result was recorded."
                )
            elif ui_language == "Hindi":
                lines = [
                    f"🏆 {mock.title} — अंतिम परिणाम",
                    f"📚 कुल प्रश्न: {mock.question_count}  •  👥 प्रतिभागी: {len(ranked)}",
                    "",
                    "🏅 रैंकिंग",
                ]
                medals = {1: "🥇", 2: "🥈", 3: "🥉"}
                for row in ranked:
                    name = row.get("display_name") or f"Student {row['user_id']}"
                    honor = row.get("honor_tag") or ""
                    star_title = str(row.get("star_title") or "").strip()
                    if star_title:
                        honor = f"{honor} ⭐ {star_title}".strip()
                    display_name = f"{honor} {name}".strip()
                    medal = medals.get(row["rank"], f"{row['rank']}.")
                    lines.append(
                        f"{medal} {display_name}\n   Score: {row['correct']}/{mock.question_count}  •  Accuracy: {row['percentage']}%\n"
                        f"   सही: {row['correct']}  •  गलत: {row['wrong']}"
                    )
                winner = ranked[0].get("display_name") or f"Student {ranked[0]['user_id']}"
                winner_honor = ranked[0].get('honor_tag') or ''
                winner_star_title = str(ranked[0].get('star_title') or '').strip()
                if winner_star_title:
                    winner_honor = f"{winner_honor} ⭐ {winner_star_title}".strip()
                winner = f"{winner_honor} {winner}".strip()
                lines.extend(["", f"🎉 विजेता: {winner}"])
                text = "\n".join(lines)
            else:
                lines = [
                    f"🏆 {mock.title} — Final Results",
                    f"📚 Questions: {mock.question_count}  •  👥 Participants: {len(ranked)}",
                    "",
                    "🏅 Final Standings",
                ]
                medals = {1: "🥇", 2: "🥈", 3: "🥉"}
                for row in ranked:
                    name = row.get("display_name") or f"Student {row['user_id']}"
                    honor = row.get("honor_tag") or ""
                    star_title = str(row.get("star_title") or "").strip()
                    if star_title:
                        honor = f"{honor} ⭐ {star_title}".strip()
                    display_name = f"{honor} {name}".strip()
                    medal = medals.get(row["rank"], f"{row['rank']}.")
                    lines.append(
                        f"{medal} {display_name}\n   Score: {row['correct']}/{mock.question_count}  •  Accuracy: {row['percentage']}%\n"
                        f"   Correct: {row['correct']}  •  Wrong: {row['wrong']}"
                    )
                winner = ranked[0].get("display_name") or f"Student {ranked[0]['user_id']}"
                winner_honor = ranked[0].get('honor_tag') or ''
                winner_star_title = str(ranked[0].get('star_title') or '').strip()
                if winner_star_title:
                    winner_honor = f"{winner_honor} ⭐ {winner_star_title}".strip()
                winner = f"{winner_honor} {winner}".strip()
                lines.extend(["", f"🎉 Winner: {winner}"])
                text = "\n".join(lines)
            await self.quiz_service.bot.send_message(chat_id=mock.group_id, text=text)
        except TelegramError:
            logger.exception("Could not send mock result for test %s", mock_id)

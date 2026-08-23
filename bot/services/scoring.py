"""Score non-anonymous quiz answers once and update XP/streak state atomically."""
from __future__ import annotations

import logging

from telegram import Bot, PollAnswer
from telegram.error import TelegramError

from bot.config import STREAK_BONUSES, UNIFIED_EXAM_LEVEL, XP_DEFAULTS
from bot.database.database import Database
from bot.database.repositories import Repository

logger = logging.getLogger(__name__)


class ScoringService:
    def __init__(self, database: Database, bot: Bot) -> None:
        self.database = database
        self.bot = bot

    async def process_poll_answer(self, poll_answer: PollAnswer) -> None:
        if not poll_answer.option_ids:
            return
        async with self.database.session_factory() as session:
            repo = Repository(session)
            history = await repo.get_quiz_by_poll(poll_answer.poll_id)
            if history is None or history.closed:
                return
            # Participation is answer-driven: pressing Join is optional. Any user
            # who answers an open mock/official poll is registered automatically,
            # so halfway standings and final results include late joiners too.
            user = await repo.upsert_user(
                telegram_user_id=poll_answer.user.id,
                username=poll_answer.user.username,
                display_name=poll_answer.user.full_name,
            )
            if history.quiz_kind == "mock_test" and history.mock_test_id is not None:
                await repo.join_mock_test(history.mock_test_id, poll_answer.user.id)
            if history.official_quiz_id is not None:
                await repo.join_official_quiz(history.official_quiz_id, poll_answer.user.id)
            question = await repo.get_question(history.question_id)
            settings = await repo.get_settings(history.group_id)
            if question is None or settings is None:
                return
            selected_option = poll_answer.option_ids[0]
            is_correct = selected_option == question.correct_option
            base_xp = int((settings.xp_map or XP_DEFAULTS).get(UNIFIED_EXAM_LEVEL, XP_DEFAULTS[UNIFIED_EXAM_LEVEL]))
            daily_bonus = await repo.daily_bonus_for_poll(poll_answer.poll_id) if is_correct and history.quiz_kind == "daily_challenge" else 0
            if history.official_quiz_id is not None:
                xp = 0
                points = 1 if is_correct else 0
            else:
                xp = base_xp + daily_bonus if is_correct else 0
                points = xp
            saved = await repo.record_answer(
                poll_id=poll_answer.poll_id, group_id=history.group_id, question_id=question.id,
                user_id=user.telegram_user_id, selected_option=selected_option, is_correct=is_correct,
                xp_awarded=xp, points_awarded=points,
            )
            if not saved:
                return
            streak_bonus = 0
            if is_correct and history.official_quiz_id is None:
                streak_bonus = int(STREAK_BONUSES.get(user.current_streak, 0))
                if streak_bonus:
                    user.xp += streak_bonus
                    user.total_points += streak_bonus
            await repo.commit()
            try:
                if is_correct and user.current_streak in STREAK_BONUSES and await repo.private_chat_is_available(user.telegram_user_id):
                    # Never announce streaks in the group. Only users who have
                    # started the bot privately can receive this notification.
                    prefix = f"{user.honor_tag} " if user.honor_tag else ""
                    if user.preferred_language == "English":
                        text = f"✅ {prefix}{user.current_streak} correct answers in a row! Keep going."
                    else:
                        text = f"✅ {prefix}{user.current_streak} प्रश्न लगातार सही! ऐसे ही आगे बढ़ते रहिए।"
                    await self.bot.send_message(chat_id=user.telegram_user_id, text=text)
            except (TelegramError, RuntimeError):
                logger.exception("Private streak notification failed")

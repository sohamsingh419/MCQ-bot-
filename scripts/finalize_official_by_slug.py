from __future__ import annotations

import asyncio
import sys

from telegram import Bot
from telegram.request import HTTPXRequest

from bot.config import get_settings
from bot.database.database import Database
from bot.database.repositories import Repository
from bot.services.ai_generator import AIQuestionGenerator
from bot.services.official_quiz import OfficialQuizService
from bot.services.quiz import QuizService


async def main(slug: str) -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    request = HTTPXRequest(connect_timeout=10, read_timeout=15, write_timeout=10, pool_timeout=10)
    bot = Bot(settings.bot_token, request=request)
    generator = AIQuestionGenerator(settings)
    quiz_service = QuizService(bot, db, settings, generator)
    official = OfficialQuizService(bot, db, quiz_service)
    try:
        async with db.session_factory() as session:
            quiz = await Repository(session).get_official_quiz_by_slug(slug)
            if quiz is None:
                raise SystemExit(f"Quiz {slug} not found")
            if quiz.status not in {"running", "completed"}:
                raise SystemExit(f"Quiz {slug} is not running or completed: {quiz.status}")
            if quiz.current_question_number < quiz.question_count:
                raise SystemExit(
                    f"Quiz {slug} is still at question {quiz.current_question_number}/{quiz.question_count}; do not finalize it."
                )
            action = "finalize" if quiz.status == "running" else "resend_result"
            print({"quiz_id": quiz.id, "slug": quiz.slug, "type": quiz.quiz_type, "action": action})
        await official.finalize(quiz.id)
        print({"finalized": True, "quiz_id": quiz.id})
    finally:
        await generator.close()
        await db.dispose()
        await bot.shutdown()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 scripts/finalize_official_by_slug.py <quiz-slug>")
    asyncio.run(main(sys.argv[1]))

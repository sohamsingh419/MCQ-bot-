import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from telegram import Bot
from telegram.request import HTTPXRequest

from bot.config import get_settings
from bot.database.database import Database
from bot.database.models import OfficialQuiz
from bot.database.repositories import Repository
from bot.services.ai_generator import AIQuestionGenerator
from bot.services.official_quiz import OfficialQuizService
from bot.services.quiz import QuizService


async def main() -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    request = HTTPXRequest(
        connect_timeout=10,
        read_timeout=15,
        write_timeout=10,
        pool_timeout=10,
    )
    bot = Bot(settings.bot_token, request=request)
    generator = AIQuestionGenerator(settings)
    quiz_service = QuizService(bot, db, settings, generator)
    official = OfficialQuizService(bot, db, quiz_service)
    try:
        async with db.session_factory() as session:
            repo = Repository(session)
            quizzes = await repo.get_official_quiz_by_slug("Master45")
            if quizzes is None:
                raise SystemExit("Quiz Master45 not found")
            quiz = quizzes
            now = datetime.now(timezone.utc)
            if quiz.status != "running":
                raise SystemExit(f"Quiz Master45 is not running: {quiz.status}")
            remaining = max(1, quiz.question_count - quiz.current_question_number)
            await session.execute(
                update(OfficialQuiz).where(OfficialQuiz.id == quiz.id).values(
                    ends_at=now + timedelta(seconds=remaining * quiz.round_seconds + 60)
                )
            )
            await repo.commit()
            print({
                "quiz_id": quiz.id,
                "slug": quiz.slug,
                "old_question_number": quiz.current_question_number,
                "new_deadline": (now + timedelta(seconds=remaining * quiz.round_seconds + 60)).isoformat(),
            })
        advanced = await official.advance_round(quiz.id)
        print({"advanced": advanced})
    finally:
        await generator.close()
        await db.dispose()
        await bot.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

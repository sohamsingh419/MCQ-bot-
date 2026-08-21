from __future__ import annotations

import asyncio

from bot.config import get_settings
from bot.database.database import Database
from bot.database.repositories import Repository
from bot.services.ai_generator import AIQuestionGenerator
from bot.services.quiz import QuizService

GROUP_ID = -1003799884627


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    generator = AIQuestionGenerator(settings)
    service = QuizService(bot=None, database=database, settings=settings, generator=generator)
    try:
        async with database.session_factory() as session:
            repo = Repository(session)
            group_settings = await repo.get_settings(GROUP_ID)
            if group_settings is None:
                print("NO_SETTINGS")
                return
            print({"state": group_settings.state, "subjects": group_settings.subjects, "difficulty": group_settings.difficulty})
            try:
                question = await service._question_for_settings(repo, group_settings)
                print({
                    "success": True,
                    "subject": question.subject,
                    "topic": question.topic,
                    "source": question.source,
                    "source_title": question.source_title,
                    "pages": (question.source_page_start, question.source_page_end),
                    "text": question.question_text,
                })
            except Exception as exc:
                print({"success": False, "exception": type(exc).__name__, "message": str(exc)})
            await session.rollback()
    finally:
        await generator.close()
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())


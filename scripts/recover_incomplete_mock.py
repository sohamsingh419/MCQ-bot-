from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone

from telegram import Bot
from telegram.request import HTTPXRequest

from bot.config import get_settings
from bot.database.database import Database
from bot.database.repositories import Repository
from bot.services.ai_generator import AIQuestionGenerator
from bot.services.quiz import QuizService


async def main(mock_id: int) -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    request = HTTPXRequest(connect_timeout=10, read_timeout=15, write_timeout=10, pool_timeout=10)
    bot = Bot(settings.bot_token, request=request)
    generator = AIQuestionGenerator(settings)
    await bot.initialize()
    service = QuizService(bot, database, settings, generator)
    try:
        async with database.session_factory() as session:
            repo = Repository(session)
            mock = await repo.get_mock_test(mock_id)
            if mock is None:
                raise SystemExit(f"Mock {mock_id} not found")
            if mock.current_question_number >= mock.question_count:
                raise SystemExit(f"Mock {mock_id} already delivered all questions")
            if mock.status == "completed":
                now = datetime.now(timezone.utc)
                mock.status = "running"
                mock.ends_at = now + timedelta(seconds=mock.round_seconds * (mock.question_count - mock.current_question_number) + 60)
                mock.round_ends_at = now
                await repo.commit()
            elif mock.status != "running":
                raise SystemExit(f"Mock {mock_id} cannot be recovered from status {mock.status}")
            print({"mock_id": mock_id, "resume_from": mock.current_question_number + 1})
        recovered = await service.send_next_mock_round(mock_id)
        print({"recovered": recovered, "mock_id": mock_id})
    finally:
        await generator.close()
        await database.dispose()
        await bot.shutdown()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 scripts/recover_incomplete_mock.py <mock-id>")
    asyncio.run(main(int(sys.argv[1])))

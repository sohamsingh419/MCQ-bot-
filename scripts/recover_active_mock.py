from __future__ import annotations

import asyncio

from telegram import Bot

from bot.config import get_settings
from bot.database.database import Database
from bot.services.ai_generator import AIQuestionGenerator
from bot.services.quiz import QuizService

MOCK_ID = 15


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    bot = Bot(settings.bot_token)
    generator = AIQuestionGenerator(settings)
    await bot.initialize()
    service = QuizService(bot, database, settings, generator)
    try:
        result = await service.send_next_mock_round(MOCK_ID)
        print(f"RECOVERED={result}")
    finally:
        await generator.close()
        await bot.shutdown()
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())


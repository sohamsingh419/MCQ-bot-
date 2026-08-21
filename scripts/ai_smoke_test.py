"""Run one real configured AI-generation request without printing secrets."""
from __future__ import annotations

import asyncio

from bot.config import get_settings
from bot.services.ai_generator import AIQuestionGenerator


async def run() -> None:
    settings = get_settings()
    generator = AIQuestionGenerator(settings)
    try:
        question = await generator.generate(
            state="General",
            subject="Indian Polity",
            topic="Fundamental Rights and Duties",
            question_type="Conceptual",
            language="English",
            previous_questions=[],
            similarity_threshold=0.86,
        )
        print(f"AI smoke test passed: language={question.language}; subject={question.subject}; difficulty={question.difficulty}; options={len(question.options)}")
    finally:
        await generator.close()


if __name__ == "__main__":
    asyncio.run(run())

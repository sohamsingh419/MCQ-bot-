"""Validate one real Hindi AI-generated MCQ without printing secrets or content."""
from __future__ import annotations

import asyncio
import re

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
            language="Hindi",
            previous_questions=[],
            similarity_threshold=0.86,
        )
        has_devanagari = bool(re.search(r"[\u0900-\u097F]", question.question))
        if question.language != "Hindi" or not has_devanagari:
            raise RuntimeError("AI did not return a usable Hindi question")
        print(f"Hindi AI smoke test passed: language={question.language}; options={len(question.options)}")
    finally:
        await generator.close()


if __name__ == "__main__":
    asyncio.run(run())

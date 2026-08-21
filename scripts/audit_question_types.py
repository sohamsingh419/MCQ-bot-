from __future__ import annotations

import asyncio
from collections import Counter

from sqlalchemy import select

from bot.config import get_settings
from bot.database.database import Database
from bot.database.models import Question


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    async with database.session_factory() as session:
        questions = list((await session.execute(select(Question))).scalars())
        print(f"TOTAL={len(questions)}")
        active_questions = [question for question in questions if question.is_active]
        print("BY_TYPE", dict(Counter(question.question_type for question in questions)))
        print("ACTIVE_TOTAL", len(active_questions))
        print("ACTIVE_BY_TYPE", dict(Counter(question.question_type for question in active_questions)))
        print("ACTIVE_AR_BY_SUBJECT", dict(Counter(question.subject for question in active_questions if question.question_type == "Assertion-Reason")))
        print("ACTIVE_APPLICATION_BY_SUBJECT", dict(Counter(question.subject for question in active_questions if question.question_type == "Application-based")))
        print("ACTIVE_MATCHING_SAMPLES", [
            {"id": question.id, "subject": question.subject, "options": question.options, "question": question.question_text}
            for question in active_questions if question.question_type == "Match-the-following"
        ][:5])
        print("AR_BY_SUBJECT", dict(Counter(question.subject for question in questions if question.question_type == "Assertion-Reason")))
        print("AR_BY_SOURCE", dict(Counter(question.source for question in questions if question.question_type == "Assertion-Reason")))
        print("AR_BY_SCOPE", [
            {
                "id": question.id,
                "state": question.state,
                "subject": question.subject,
                "difficulty": question.difficulty,
                "source": question.source,
                "question": question.question_text,
            }
            for question in questions if question.question_type == "Assertion-Reason"
        ])
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())


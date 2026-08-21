from __future__ import annotations

import asyncio

from sqlalchemy import desc, select

from bot.config import get_settings
from bot.database.database import Database
from bot.database.models import GroupSettings, MockTest, MockTestParticipant, Question, QuizHistory

GROUP_ID = -1003799884627


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    async with database.session_factory() as session:
        group_settings = await session.get(GroupSettings, GROUP_ID)
        print("GROUP_SETTINGS", {
            "state": group_settings.state if group_settings else None,
            "subjects": group_settings.subjects if group_settings else None,
            "difficulty": group_settings.difficulty if group_settings else None,
            "quiz_active": group_settings.quiz_active if group_settings else None,
        })
        mocks = list((await session.execute(
            select(MockTest).where(MockTest.group_id == GROUP_ID).order_by(desc(MockTest.created_at)).limit(10)
        )).scalars())
        for mock in mocks:
            participants = list((await session.execute(
                select(MockTestParticipant).where(MockTestParticipant.mock_test_id == mock.id)
            )).scalars())
            histories = list((await session.execute(
                select(QuizHistory, Question)
                .join(Question, Question.id == QuizHistory.question_id)
                .where(QuizHistory.mock_test_id == mock.id)
                .order_by(QuizHistory.opened_at.asc())
            )).all())
            print("MOCK", {
                "id": mock.id,
                "title": mock.title,
                "status": mock.status,
                "subjects": mock.subjects,
                "state": mock.state,
                "difficulty": mock.difficulty,
                "question_count": mock.question_count,
                "current_question_number": mock.current_question_number,
                "round_seconds": mock.round_seconds,
                "current_poll_id": mock.current_poll_id,
                "participants": len(participants),
                "used_questions": [question.id for _, question in histories],
            })
            for history, question in histories:
                print("  ROUND", {
                    "number": history.id,
                    "question_id": question.id,
                    "subject": question.subject,
                    "state": question.state,
                    "topic": question.topic,
                    "source": question.source,
                    "source_document_id": question.source_document_id,
                    "source_title": question.source_title,
                    "closed": history.closed,
                })
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())


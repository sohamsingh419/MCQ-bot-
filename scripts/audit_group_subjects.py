from __future__ import annotations

import asyncio

from sqlalchemy import desc, select

from bot.config import get_settings
from bot.database.database import Database
from bot.database.models import Group, GroupSettings, Question, QuizHistory

GROUP_ID = -1003799884627


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    async with database.session_factory() as session:
        group = await session.get(Group, GROUP_ID)
        group_settings = await session.get(GroupSettings, GROUP_ID)
        print({
            "group_id": GROUP_ID,
            "title": group.title if group else None,
            "state": group_settings.state if group_settings else None,
            "subjects": group_settings.subjects if group_settings else None,
            "difficulty": group_settings.difficulty if group_settings else None,
            "rotation_enabled": group_settings.rotation_enabled if group_settings else None,
            "current_rotation_index": group_settings.current_rotation_index if group_settings else None,
            "topic_rotation_state": group_settings.topic_rotation_state if group_settings else None,
        })
        rows = list((await session.execute(
            select(QuizHistory, Question)
            .join(Question, Question.id == QuizHistory.question_id)
            .where(QuizHistory.group_id == GROUP_ID)
            .order_by(desc(QuizHistory.opened_at))
            .limit(30)
        )).all())
        print(f"RECENT_COUNT={len(rows)}")
        for history, question in rows:
            print({
                "quiz_id": history.id,
                "opened_at": str(history.opened_at),
                "question_id": question.id,
                "subject": question.subject,
                "state": question.state,
                "topic": question.topic,
                "source": question.source,
                "source_document_id": question.source_document_id,
                "source_title": question.source_title,
            })
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())


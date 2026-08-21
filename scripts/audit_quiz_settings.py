from __future__ import annotations

import asyncio

from sqlalchemy import select

from bot.config import get_settings
from bot.database.database import Database
from bot.database.models import GroupSettings, Group


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    async with database.session_factory() as session:
        rows = (await session.execute(
            select(GroupSettings, Group.title)
            .join(Group, Group.telegram_chat_id == GroupSettings.group_id)
            .order_by(GroupSettings.updated_at.desc())
        )).all()
        for row, title in rows:
            print({
                "group_id": row.group_id,
                "title": title,
                "state": row.state,
                "subjects": row.subjects,
                "difficulty": row.difficulty,
                "rotation_enabled": row.rotation_enabled,
                "rotation_index": row.current_rotation_index,
                "topic_rotation_state": row.topic_rotation_state,
                "last_quiz_at": str(row.last_quiz_at),
            })
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())


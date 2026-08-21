from __future__ import annotations

import asyncio

from sqlalchemy import select

from bot.config import get_settings, syllabus_topics_for
from bot.database.database import Database
from bot.database.models import SourceChunk
from bot.services.quiz import _topic_relevant_source_chunks


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    topics = syllabus_topics_for("Rajasthan", "State History")
    print(f"TOPIC_COUNT={len(topics)}")
    print(f"FIRST_TOPICS={topics[:10]}")
    async with database.session_factory() as session:
        chunks = list((await session.execute(
            select(SourceChunk).where(SourceChunk.document_id == 4).order_by(SourceChunk.chunk_index.asc())
        )).scalars())
        for topic in topics[:10]:
            matched = _topic_relevant_source_chunks(chunks, topic, limit=3)
            print(f"TOPIC={topic!r} MATCHES={len(matched)}")
            for chunk in matched:
                print(f"  chunk={chunk.chunk_index} stored_topic={chunk.topic!r} pages={chunk.page_start}-{chunk.page_end}")
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())


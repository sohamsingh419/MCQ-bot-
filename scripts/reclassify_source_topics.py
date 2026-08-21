from __future__ import annotations

import asyncio

from sqlalchemy import select

from bot.config import get_settings, syllabus_topics_for
from bot.database.database import Database
from bot.database.models import SourceChunk, SourceDocument
from bot.services.source import _topic_for_text


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    async with database.session_factory() as session:
        documents = list((await session.execute(
            select(SourceDocument).where(SourceDocument.state.is_not(None), SourceDocument.subject.is_not(None))
        )).scalars())
        total = 0
        for document in documents:
            topics = syllabus_topics_for(document.state or "General", document.subject or "General Knowledge")
            chunks = list((await session.execute(
                select(SourceChunk).where(SourceChunk.document_id == document.id)
            )).scalars())
            changed = 0
            for chunk in chunks:
                topic = _topic_for_text(chunk.text, topics)
                if topic != chunk.topic:
                    chunk.topic = topic
                    changed += 1
            total += changed
            print(f"document_id={document.id} filename={document.filename} changed={changed} chunks={len(chunks)}")
        await session.commit()
        print(f"TOTAL_CHANGED={total}")
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())


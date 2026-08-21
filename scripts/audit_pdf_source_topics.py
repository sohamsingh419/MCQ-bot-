from __future__ import annotations

import asyncio
from collections import Counter

from sqlalchemy import select

from bot.config import get_settings
from bot.database.database import Database
from bot.database.models import SourceChunk, SourceDocument


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    async with database.session_factory() as session:
        documents = list((await session.execute(
            select(SourceDocument).where(SourceDocument.filename.ilike("%Rajasthan History%"))
        )).scalars())
        for document in documents:
            chunks = list((await session.execute(
                select(SourceChunk).where(SourceChunk.document_id == document.id).order_by(SourceChunk.chunk_index.asc())
            )).scalars())
            print(f"DOCUMENT id={document.id} status={document.status} state={document.state} subject={document.subject} pages={document.page_count} chunks={len(chunks)}")
            print("TOPICS")
            for topic, count in Counter(chunk.topic for chunk in chunks).most_common():
                print(f"  {count}x {topic!r}")
            print("SAMPLE_CHUNKS")
            for chunk in chunks[:8]:
                print(f"  index={chunk.chunk_index} topic={chunk.topic!r} pages={chunk.page_start}-{chunk.page_end} chars={len(chunk.text)} text={chunk.text[:180]!r}")
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())


from __future__ import annotations

import asyncio

from sqlalchemy import select

from bot.config import get_settings
from bot.database.database import Database
from bot.database.models import SourceChunk, SourceDocument


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    async with database.session_factory() as session:
        documents = list((await session.execute(
            select(SourceDocument).where(SourceDocument.filename == "Raj_geo.pdf")
        )).scalars())
        if not documents:
            print("No Raj_geo.pdf document found")
            return
        for document in documents:
            chunks = list((await session.execute(
                select(SourceChunk)
                .where(SourceChunk.document_id == document.id)
                .order_by(SourceChunk.chunk_index.asc())
            )).scalars())
            print(f"DOCUMENT id={document.id} filename={document.filename} status={document.status} state={document.state} subject={document.subject} pages={document.page_count} chunks={len(chunks)}")
            for chunk in chunks:
                print(f"CHUNK id={chunk.id} index={chunk.chunk_index} topic={chunk.topic!r} pages={chunk.page_start}-{chunk.page_end} chars={len(chunk.text)}")
                print(f"TEXT {chunk.text}")
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select

from bot.config import get_settings
from bot.database.database import Database
from bot.database.models import SourceDocument, SourceChunk


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    async with database.session_factory() as session:
        rows = list((await session.execute(select(SourceDocument).order_by(SourceDocument.id.desc()))).scalars())
        for row in rows:
            path = Path(row.storage_path)
            chunks = (await session.execute(select(SourceChunk.id).where(SourceChunk.document_id == row.id))).all()
            print({
                "id": row.id,
                "filename": row.filename,
                "status": row.status,
                "state": row.state,
                "subject": row.subject,
                "pages": row.page_count,
                "chunks": len(chunks),
                "size": path.stat().st_size if path.exists() else None,
                "path": str(path),
                "error": row.extraction_error,
            })
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())


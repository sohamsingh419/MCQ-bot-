from __future__ import annotations

import asyncio

from bot.config import get_settings
from bot.database.database import Database
from bot.database.repositories import Repository
from bot.services.source import ingest_source_document


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        documents = await repo.source_document_summaries()
        targets = [item for item in documents if item.status != "cancelled" and item.state and item.subject]
    for document in targets:
        ok, text = await ingest_source_document(
            database, settings, document.id, state=document.state, subject=document.subject
        )
        print(f"document_id={document.id} filename={document.filename} ok={ok} result={text}")
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())

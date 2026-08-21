from __future__ import annotations

import asyncio
from pathlib import Path

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
        target = next(
            (item for item in documents if "4342424852" in str(getattr(item, "telegram_chat_id", ""))),
            None,
        )
        if target is None:
            target = next((item for item in documents if Path(item.filename).suffix.casefold() == ".pdf"), None)
        if target is None:
            raise RuntimeError("No source PDF was found in the database")
        document_id = target.id
        state = target.state or "Rajasthan"
        subject = target.subject or "State History"
    ok, text = await ingest_source_document(database, settings, document_id, state=state, subject=subject)
    print(f"ok={ok} document_id={document_id} state={state} subject={subject} result={text}")
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())

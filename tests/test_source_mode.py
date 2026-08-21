from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from bot.database.database import Database
from bot.database.repositories import Repository
from bot.services.source import _topic_for_text, build_chunks, extract_pages, ingest_source_document


def _make_pdf(path: Path) -> None:
    writer = canvas.Canvas(str(path))
    writer.drawString(72, 760, "Rivers and drainage are important topics in Indian geography.")
    writer.drawString(72, 740, "The Ganga is a major river system used in syllabus-based study.")
    writer.showPage()
    writer.drawString(72, 760, "Fundamental Rights are part of the Indian Constitution.")
    writer.save()


def test_hindi_source_text_maps_to_unicode_topic() -> None:
    topic = "Rajasthan: प्राचीन सभ्यताएं एवं पुरातात्विक स्थल"
    text = "राजस्थान के प्राचीन सभ्यताएं एवं पुरातात्विक स्थल का इतिहास।"
    assert _topic_for_text(text, (topic,)) == topic


def test_text_pdf_extracts_pages_and_builds_topic_chunks(tmp_path: Path) -> None:
    pdf_path = tmp_path / "NCERT_Geography.pdf"
    _make_pdf(pdf_path)
    page_count, pages = extract_pages(pdf_path)
    assert page_count == 2
    assert len(pages) == 2
    chunks = build_chunks(pages, state="All India", subject="Geography")
    assert chunks
    assert chunks[0]["page_start"] == 1
    assert "rivers" in str(chunks[0]["text"]).casefold()


@pytest.mark.asyncio
async def test_ingest_source_document_marks_ready_and_persists_chunks(tmp_path: Path) -> None:
    pdf_path = tmp_path / "NCERT_Geography.pdf"
    _make_pdf(pdf_path)
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        document = await repo.create_source_document(
            telegram_file_id="file-ingest", telegram_chat_id=-1000, telegram_message_id=12,
            uploaded_by=99, filename=pdf_path.name, storage_path=str(pdf_path),
        )
        await repo.commit()
        document_id = document.id
    settings = type("SourceSettings", (), {"source_ocr_enabled": False})()
    ok, message = await ingest_source_document(
        database, settings, document_id, state="All India", subject="Geography"
    )
    assert ok and "sections" in message
    async with database.session_factory() as session:
        repo = Repository(session)
        saved = await repo.get_source_document(document_id)
        assert saved and saved.status == "ready" and saved.chunk_count > 0 and saved.page_count == 2
    await database.dispose()


@pytest.mark.asyncio
async def test_source_documents_and_chunks_are_filtered_by_state_and_subject() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        document = await repo.create_source_document(
            telegram_file_id="file-1", telegram_chat_id=-1001, telegram_message_id=10,
            uploaded_by=99, filename="Rajasthan_Geography.pdf", storage_path="/tmp/file.pdf",
        )
        await repo.update_source_document(document.id, state="Rajasthan", subject="State Geography", status="ready")
        await repo.add_source_chunks(
            document.id, state="Rajasthan", subject="State Geography",
            chunks=[{
                "topic": "Rivers and drainage", "page_start": 1, "page_end": 1,
                "chunk_index": 0, "text": "Rajasthan rivers and drainage source text.", "content_hash": "hash-1",
            }],
        )
        await repo.commit()

    async with database.session_factory() as session:
        repo = Repository(session)
        selected = await repo.source_chunks_for_scope(
            state="Rajasthan", subject="State Geography", topic="Rivers and drainage"
        )
        excluded = await repo.source_chunks_for_scope(
            state="Kerala", subject="State Geography", topic="Rivers and drainage"
        )
        assert len(selected) == 1
        assert excluded == []
    await database.dispose()

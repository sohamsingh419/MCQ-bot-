import pytest

from bot.database.database import Database
from bot.database.repositories import Repository
from bot.services.source import build_chunks, extract_mcq_questions


def test_build_chunks_removes_nul_characters_before_hashing() -> None:
    chunks = build_chunks(
        [(1, "राजस्थान \x00 की कृषि और प्रमुख फसलें महत्वपूर्ण हैं।")],
        state="Rajasthan",
        subject="State Geography",
    )
    assert chunks
    assert "\x00" not in chunks[0]["text"]
    assert "कृषि" in chunks[0]["text"]


def test_extract_mcq_questions_removes_nul_characters() -> None:
    pages = [(1, "1. राजस्थान का राज्य पशु कौन सा है?\x00\nA. ऊँट\x00\nB. बाघ\nC. चीतल\nD. नीलगाय\nAnswer: A")]
    questions = extract_mcq_questions(pages)
    assert questions
    assert all("\x00" not in str(value) for value in questions[0].values())


@pytest.mark.asyncio
async def test_repository_source_and_question_writes_strip_nuls() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        document = await repo.create_source_document(
            telegram_file_id="nul-file", telegram_chat_id=-500, telegram_message_id=1,
            uploaded_by=1, filename="nul.pdf", storage_path="/tmp/nul.pdf",
        )
        await repo.add_source_chunks(
            document.id,
            state="Rajasthan",
            subject="State Geography",
            chunks=[{
                "topic": "कृषि\x00",
                "page_start": 1,
                "page_end": 1,
                "chunk_index": 0,
                "text": "साफ text\x00 और Hindi",
                "content_hash": "original-hash",
            }],
        )
        question = await repo.add_question(
            question_text="राज्य पशु कौन सा है?\x00",
            options=["ऊँट\x00", "बाघ", "चीतल", "नीलगाय"],
            correct_option=0,
            explanation="उत्तर\x00",
            key_point="मुख्य बिंदु\x00",
            state="Rajasthan",
            subject="State Geography",
            topic="कृषि\x00",
            difficulty="Exam",
            question_type="Conceptual",
        )
        await repo.commit()
        chunks = await repo.source_chunks_for_scope(state="Rajasthan", subject="State Geography", limit=5)
        assert chunks and "\x00" not in chunks[0].text and "\x00" not in chunks[0].topic
        assert "\x00" not in question.question_text
        assert all("\x00" not in option for option in question.options)
        assert "\x00" not in question.explanation
        assert "\x00" not in question.key_point
    await database.dispose()

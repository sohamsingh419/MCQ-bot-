from datetime import datetime, timezone

import pytest

from bot.database.database import Database
from bot.database.repositories import Repository
from bot.services.question_validator import validate_question


HINDI_QUESTION = {
    "question": "भारतीय संविधान के किस अनुच्छेद में निर्वाचन आयोग के कार्यों का उल्लेख है?",
    "options": ["अनुच्छेद 324", "अनुच्छेद 280", "अनुच्छेद 315", "अनुच्छेद 148"],
    "correct_option": 0,
    "explanation": "अनुच्छेद 324 निर्वाचन आयोग को चुनावों के अधीक्षण, निर्देशन और नियंत्रण की शक्ति देता है।",
    "key_point": "निर्वाचन आयोग का संवैधानिक आधार अनुच्छेद 324 है।",
    "subject": "Indian Polity",
    "topic": "Constitutional bodies",
    "difficulty": "Exam",
    "question_type": "Conceptual",
    "language": "Hindi",
}


def test_hindi_question_passes_language_validation() -> None:
    question = validate_question(HINDI_QUESTION, expected_language="Hindi")
    assert question.language == "Hindi"
    assert len(question.options) == 4


@pytest.mark.asyncio
async def test_private_chat_settings_are_scheduled_independently() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.upsert_user(7001, "dm_student", "DM Student")
        settings = await repo.ensure_group(7001, "DM Student", "private")
        await repo.update_settings(7001, language="Hindi", quiz_active=True, last_quiz_at=None, interval_minutes=10)
        await repo.commit()

    async with database.session_factory() as session:
        repo = Repository(session)
        due = await repo.due_group_settings(datetime.now(timezone.utc))
        private_active = await repo.active_group_settings_for_types(["private"])
        assert any(item.group_id == 7001 and item.language == "Hindi" for item in due)
        assert [item.group_id for item in private_active] == [7001]
    await database.dispose()

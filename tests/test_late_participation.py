from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from bot.database.database import Database
from bot.database.repositories import Repository
from bot.services.scoring import ScoringService


class SilentBot:
    async def send_message(self, **kwargs):
        return SimpleNamespace(message_id=1)


@pytest.mark.asyncio
async def test_answering_without_join_registers_official_and_mock_participants() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    now = datetime.now(timezone.utc)
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-901, "Mock Group", "supergroup")
        await repo.ensure_group(-902, "Official Group", "supergroup")
        question = await repo.add_question(
            question_text="राजस्थान की राजधानी कौन-सी है?",
            options=["जयपुर", "जोधपुर", "उदयपुर", "कोटा"],
            correct_option=0,
            explanation="जयपुर राजस्थान की राजधानी है।",
            key_point="राजस्थान की राजधानी जयपुर है।",
            state="Rajasthan", subject="State GK", topic="राजधानी", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        mock = await repo.create_mock_test(
            group_id=-901, title="Late Mock", count=1, round_seconds=5,
            subjects=["State GK"], state="Rajasthan", difficulty="Exam",
            starts_at=now, lobby_closes_at=now - timedelta(seconds=1),
            ends_at=now + timedelta(minutes=2), created_by=1,
        )
        official = await repo.create_official_quiz(
            slug="late-star-test", quiz_type="star", title="Late Star", rules="Rules",
            month_key="2026-08", config_group_id=-902, play_group_id=-902,
            source_group_id=-902, question_count=1, round_seconds=5,
            question_ids=[question.id], created_by=1,
        )
        await repo.record_quiz(
            group_id=-901, question_id=question.id, poll_id="late-mock-poll",
            message_id=1, quiz_kind="mock_test", closes_at=now + timedelta(seconds=5),
            mock_test_id=mock.id,
        )
        await repo.record_quiz(
            group_id=-902, question_id=question.id, poll_id="late-official-poll",
            message_id=2, quiz_kind="official_star", closes_at=now + timedelta(seconds=5),
            official_quiz_id=official.id, official_question_number=1,
        )
        await repo.commit()

    scorer = ScoringService(database, SilentBot())
    await scorer.process_poll_answer(SimpleNamespace(
        poll_id="late-mock-poll", option_ids=[0],
        user=SimpleNamespace(id=901, username=None, full_name="Late Mock User"),
    ))
    await scorer.process_poll_answer(SimpleNamespace(
        poll_id="late-official-poll", option_ids=[0],
        user=SimpleNamespace(id=902, username=None, full_name="Late Official User"),
    ))

    async with database.session_factory() as session:
        repo = Repository(session)
        mock_results = await repo.mock_results(mock.id)
        official_results = await repo.official_results(official.id)
        assert [(row["user_id"], row["correct"]) for row in mock_results] == [(901, 1)]
        assert [(row["user_id"], row["correct"]) for row in official_results] == [(902, 1)]
    await database.dispose()

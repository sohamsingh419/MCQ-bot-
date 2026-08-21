from datetime import datetime, timedelta, timezone

import pytest

from bot.database.database import Database
from bot.database.repositories import Repository


@pytest.mark.asyncio
async def test_mock_lobby_requires_registered_participants_and_includes_zero_answer_results() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    now = datetime.now(timezone.utc)
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-4100, "Timed Mock Group", "group")
        await repo.upsert_user(101, "one", "Student One")
        await repo.upsert_user(102, "two", "Student Two")
        mock = await repo.create_mock_test(
            group_id=-4100, title="Timed Mock", count=2, round_seconds=15,
            subjects=["State GK"], state="Rajasthan", difficulty="Exam",
            starts_at=now, lobby_closes_at=now + timedelta(seconds=60),
            ends_at=now + timedelta(minutes=5), created_by=101,
        )
        assert await repo.join_mock_test(mock.id, 101) == 1
        assert await repo.join_mock_test(mock.id, 102) == 2
        assert await repo.is_mock_participant(mock.id, 101) is True
        assert await repo.is_mock_participant(mock.id, 999) is False
        assert await repo.start_mock_test(mock.id, starts_at=now, ends_at=now + timedelta(minutes=1)) is True
        question = await repo.add_question(
            question_text="राजस्थान की राजधानी कौन सी है?",
            options=["जयपुर", "उदयपुर", "जोधपुर", "कोटा"], correct_option=0,
            explanation="जयपुर राजस्थान की राजधानी है।", key_point="राजस्थान की राजधानी जयपुर है।",
            state="Rajasthan", subject="State GK", topic="राजस्थान", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        await repo.record_quiz(
            group_id=-4100, question_id=question.id, poll_id="timed-poll", message_id=1,
            quiz_kind="mock_test", closes_at=now + timedelta(seconds=15), mock_test_id=mock.id,
        )
        assert await repo.record_answer(
            poll_id="timed-poll", group_id=-4100, question_id=question.id, user_id=101,
            selected_option=0, is_correct=True, xp_awarded=0, points_awarded=0,
        ) is True
        results = await repo.mock_results(mock.id)
        assert [(row["user_id"], row["correct"], row["wrong"]) for row in results] == [(101, 1, 0), (102, 0, 0)]
        saved = await repo.save_mock_results(mock.id, total=2, results=results)
        assert [(row["rank"], row["percentage"]) for row in saved] == [(1, 50.0), (2, 0.0)]
        await repo.commit()
    await database.dispose()

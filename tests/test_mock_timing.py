from datetime import datetime, timedelta, timezone

import pytest

from bot.database.database import Database
from bot.database.repositories import Repository


@pytest.mark.asyncio
async def test_mock_round_extends_overall_deadline() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    now = datetime.now(timezone.utc)
    async with database.session_factory() as session:
        repo = Repository(session)
        mock = await repo.create_mock_test(
            group_id=-910, title="Timing Mock", count=4, round_seconds=10,
            subjects=["State GK"], state="Rajasthan", difficulty="Exam",
            starts_at=now, lobby_closes_at=now - timedelta(seconds=1),
            ends_at=now + timedelta(seconds=20), created_by=1,
        )
        await repo.set_mock_round(
            mock.id, question_number=2, poll_id="timing-poll",
            round_ends_at=now + timedelta(seconds=30),
        )
        saved = await repo.get_mock_test(mock.id)
        assert saved is not None
        assert saved.current_question_number == 2
        assert saved.current_poll_id == "timing-poll"
        assert saved.ends_at >= now + timedelta(seconds=90)
    await database.dispose()

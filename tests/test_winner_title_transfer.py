import pytest

from bot.config import GSI_HONOR_TAG
from bot.database.database import Database
from bot.database.repositories import Repository


@pytest.mark.asyncio
async def test_active_winner_titles_transfer_without_erasing_history() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        previous = await repo.upsert_user(1001, "old", "Previous Winner")
        previous.honor_tag = GSI_HONOR_TAG
        previous.gsi_wins = 2
        previous.gsi_achievements = ["January2026", "February2026"]
        previous.star_count = 2
        previous.star_title = "Star Quizzer ×2"
        current = await repo.upsert_user(1002, "new", "Current Winner")
        await repo.commit()

        await repo.clear_active_gsi_honor(current.telegram_user_id)
        current.honor_tag = GSI_HONOR_TAG
        await repo.clear_active_star_title(current.telegram_user_id)
        current.star_count = 1
        current.star_title = "Star Quizzer ×1"
        await repo.commit()

    async with database.session_factory() as session:
        repo = Repository(session)
        old = await repo.get_user(1001)
        new = await repo.get_user(1002)
        assert old and old.honor_tag is None and old.star_title is None
        assert old.gsi_wins == 2
        assert old.gsi_achievements == ["January2026", "February2026"]
        assert old.star_count == 2
        assert new and new.honor_tag == GSI_HONOR_TAG and new.star_title == "Star Quizzer ×1"
    await database.dispose()

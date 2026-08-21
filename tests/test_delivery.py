from types import SimpleNamespace

import pytest
from sqlalchemy import select
from telegram.error import TelegramError

from bot.database.database import Database
from bot.handlers import delivery
from bot.database.models import DeliveryCampaign, DeliveryReceipt
from bot.database.repositories import Repository
from bot.services.delivery import DeliveryService


class FakeBot:
    def __init__(self) -> None:
        self.sent_to: list[int] = []
        self.copied: list[tuple[int, int, int]] = []

    async def send_message(self, *, chat_id: int, text: str) -> SimpleNamespace:
        self.sent_to.append(chat_id)
        if chat_id == -22:
            raise TelegramError("bot was removed from this group")
        return SimpleNamespace(message_id=1000 + len(self.sent_to))

    async def copy_message(self, *, chat_id: int, from_chat_id: int, message_id: int) -> SimpleNamespace:
        self.copied.append((chat_id, from_chat_id, message_id))
        return SimpleNamespace(message_id=2000 + len(self.copied))


def test_delivery_requires_configured_global_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(delivery, "get_settings", lambda: SimpleNamespace(global_admin_ids={999}))
    assert delivery._is_bot_admin(999) is True
    assert delivery._is_bot_admin(1000) is False


@pytest.mark.asyncio
async def test_targeted_audience_filters_state_and_chat_type() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(11, "Rajasthan Student", "private")
        await repo.update_settings(11, state="Rajasthan")
        await repo.ensure_group(-22, "Rajasthan Group", "group")
        await repo.update_settings(-22, state="Rajasthan")
        await repo.ensure_group(33, "UP Student", "private")
        await repo.update_settings(33, state="Uttar Pradesh")
        await repo.commit()

    service = DeliveryService(FakeBot(), database)
    assert await service.audience_preview("users", "Rajasthan") == [11]
    assert await service.audience_preview("groups", "Rajasthan") == [-22]
    assert await service.audience_preview("both", "Rajasthan") == [-22, 11]
    details = await service.audience_preview_details("both", "Rajasthan")
    assert {(title, chat_type) for _, title, chat_type in details} == {
        ("Rajasthan Student", "private"), ("Rajasthan Group", "group")
    }
    await database.dispose()


@pytest.mark.asyncio
async def test_quiz_poll_is_copied_without_original_sender_label() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(11, "Rajasthan Student", "private")
        await repo.update_settings(11, state="Rajasthan")
        await repo.commit()

    fake_bot = FakeBot()
    service = DeliveryService(fake_bot, database)
    summary = await service.send(
        created_by=999, mode="broadcast", audience="users", state=None,
        content_type="poll", content_text="Who founded the Maurya Empire?",
        payload={"source_chat_id": 999, "source_message_id": 777},
    )
    assert summary.sent == 1 and summary.failed == 0
    assert fake_bot.copied == [(11, 999, 777)]
    await database.dispose()


@pytest.mark.asyncio
async def test_delivery_records_success_and_individual_failure() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(11, "Rajasthan Student", "private")
        await repo.update_settings(11, state="Rajasthan")
        await repo.ensure_group(-22, "Rajasthan Group", "group")
        await repo.update_settings(-22, state="Rajasthan")
        await repo.commit()

    fake_bot = FakeBot()
    service = DeliveryService(fake_bot, database)
    summary = await service.send(
        created_by=999, mode="targeted", audience="both", state="Rajasthan",
        content_type="text", content_text="Daily practice update", payload={},
    )
    assert summary.recipients == 2
    assert summary.sent == 1
    assert summary.failed == 1
    assert set(fake_bot.sent_to) == {-22, 11}

    async with database.session_factory() as session:
        campaign = (await session.execute(select(DeliveryCampaign))).scalar_one()
        receipts = list((await session.execute(select(DeliveryReceipt))).scalars())
        assert campaign.status == "completed_with_errors"
        assert campaign.recipient_count == 2 and campaign.sent_count == 1 and campaign.failed_count == 1
        assert {receipt.status for receipt in receipts} == {"sent", "failed"}
        assert any(receipt.error for receipt in receipts if receipt.status == "failed")
    await database.dispose()

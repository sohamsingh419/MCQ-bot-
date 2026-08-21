from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from telegram.constants import ChatMemberStatus

from bot.config import get_settings
from bot.database.database import Database
from bot.database.repositories import Repository
from bot.handlers import admin
from bot.handlers.group_setup import group_welcome_on_join
from bot.main import post_init
from bot.services.scheduler import SchedulerService


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[dict] = []

    async def reply_text(self, text, **kwargs) -> None:
        self.replies.append({"text": text, **kwargs})


class FakeBot:
    def __init__(self, status=ChatMemberStatus.MEMBER) -> None:
        self.status = status
        self.sent: list[dict] = []
        self.commands = None

    async def send_message(self, **kwargs) -> None:
        self.sent.append(kwargs)

    async def get_me(self):
        return SimpleNamespace(id=99999)

    async def get_chat_member(self, chat_id: int, user_id: int):
        return SimpleNamespace(status=self.status)

    async def set_my_commands(self, commands, scope=None) -> None:
        self.commands = (commands, scope)


@pytest.mark.asyncio
async def test_status_is_admin_only_and_reports_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_USER_IDS", "7028236763")
    get_settings.cache_clear()
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.upsert_user(11, "hidden_username", "Learner One")
        await repo.ensure_group(-11, "Admin Group", "supergroup")
        await repo.update_settings(-11, bot_is_admin=True, quiz_active=True)
        await repo.ensure_group(-12, "Needs Admin", "group")
        await repo.update_settings(-12, bot_is_admin=False)
        await repo.commit()

    message = FakeMessage()
    update = SimpleNamespace(effective_user=SimpleNamespace(id=7028236763), effective_message=message)
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": database, "scheduler": None}))
    await admin.status_command(update, context)
    assert message.replies
    text = message.replies[0]["text"]
    assert "Total users:</b> 1" in text
    assert "Total groups:" in text and "Bot is admin:" in text and "Bot is not admin:" in text
    assert "Stored questions:" in text

    denied = FakeMessage()
    denied_update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=denied)
    await admin.status_command(denied_update, context)
    assert "केवल configured bot admin" in denied.replies[0]["text"]
    await database.dispose()


@pytest.mark.asyncio
async def test_admin_readiness_reminders_progress_and_stop_after_48_hours() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    now = datetime.now(timezone.utc)
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-101, "Reminder Group", "supergroup")
        await repo.update_settings(
            -101,
            bot_is_admin=False,
            bot_joined_at=now - timedelta(minutes=10),
            admin_reminder_stage=0,
        )
        await repo.commit()

    bot = FakeBot(ChatMemberStatus.MEMBER)
    service = SchedulerService(
        database,
        SimpleNamespace(bot=bot),
        SimpleNamespace(timezone="UTC", scheduler_tick_seconds=60, question_pool_enabled=False),
    )
    await service._send_admin_readiness_reminders(now)
    assert len(bot.sent) == 1
    assert "Bot needs Admin permissions" in bot.sent[0]["text"]
    async with database.session_factory() as session:
        settings = await Repository(session).get_settings(-101)
        assert settings and settings.admin_reminder_stage == 1
        settings.bot_joined_at = now - timedelta(hours=1, minutes=1)
        await session.commit()

    await service._send_admin_readiness_reminders(now)
    assert len(bot.sent) == 2
    async with database.session_factory() as session:
        settings = await Repository(session).get_settings(-101)
        assert settings and settings.admin_reminder_stage == 2
        settings.bot_joined_at = now - timedelta(days=3)
        await session.commit()

    await service._send_admin_readiness_reminders(now + timedelta(days=3))
    assert len(bot.sent) == 3
    async with database.session_factory() as session:
        settings = await Repository(session).get_settings(-101)
        assert settings and settings.admin_reminder_stage == 7
    await service._send_admin_readiness_reminders(now + timedelta(days=3, minutes=5))
    assert len(bot.sent) == 3
    await database.dispose()


@pytest.mark.asyncio
async def test_membership_promotion_marks_bot_admin_and_stops_reminders() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-202, "Promotion Group", "supergroup")
        await repo.update_settings(
            -202,
            bot_is_admin=False,
            bot_joined_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            admin_reminder_stage=1,
        )
        await repo.commit()

    bot = FakeBot(ChatMemberStatus.OWNER)
    update = SimpleNamespace(
        my_chat_member=SimpleNamespace(
            chat=SimpleNamespace(id=-202, title="Promotion Group", type="supergroup"),
            old_chat_member=SimpleNamespace(status=ChatMemberStatus.MEMBER),
            new_chat_member=SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR),
        )
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": database}), bot=bot)
    await group_welcome_on_join(update, context)
    async with database.session_factory() as session:
        settings = await Repository(session).get_settings(-202)
        assert settings and settings.bot_is_admin is True and settings.admin_reminder_stage == 8
    assert not bot.sent
    await database.dispose()


@pytest.mark.asyncio
async def test_post_init_registers_supported_command_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    get_settings.cache_clear()
    database = Database("sqlite+aiosqlite:///:memory:")
    scheduler = SimpleNamespace(start=lambda: None)
    scheduler.start = _async_noop
    bot = FakeBot()
    application = SimpleNamespace(
        bot_data={"database": database, "scheduler": scheduler},
        bot=bot,
    )
    await post_init(application)
    names = {command.command for command in bot.commands[0]}
    assert {"start", "help", "profile", "rules", "settings", "setstate", "setsubjects", "mocktest", "status"}.issubset(names)
    assert "testquestion" not in names and "setrotation" not in names and "setexplanation" not in names
    await database.dispose()


async def _async_noop() -> None:
    return None


def teardown_module() -> None:
    get_settings.cache_clear()

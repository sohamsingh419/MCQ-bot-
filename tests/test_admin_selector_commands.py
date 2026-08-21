from types import SimpleNamespace

import pytest

from bot.database.database import Database
from bot.database.repositories import Repository
from bot.handlers.admin import setinterval_command, setstate_command, setsubject_command


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[dict] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append({"text": text, **kwargs})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "expected_prefix"),
    [
        ("setstate_command", "gset:stateval:"),
        ("setsubject_command", "gset:subj:"),
        ("setinterval_command", "gset:intval:"),
    ],
)
async def test_admin_setting_commands_open_inline_selectors(handler_name: str, expected_prefix: str) -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-7711, title="Selector Group", type="supergroup"),
        effective_user=SimpleNamespace(id=7028236763, username="botadmin", full_name="Bot Admin"),
        effective_message=message,
    )
    context = SimpleNamespace(
        args=[],
        bot=None,
        application=SimpleNamespace(bot_data={"database": database}),
    )
    handlers = {
        "setstate_command": setstate_command,
        "setsubject_command": setsubject_command,
        "setinterval_command": setinterval_command,
    }
    await handlers[handler_name](update, context)
    assert len(message.replies) == 1
    callback_data = [
        button.callback_data
        for row in message.replies[0]["reply_markup"].inline_keyboard
        for button in row
    ]
    assert any(data.startswith(expected_prefix) for data in callback_data)
    await database.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "expected_prefix"),
    [
        ("setstate_command", "dset:stateval:"),
        ("setsubject_command", "dset:subj:"),
        ("setinterval_command", "dset:intval:"),
    ],
)
async def test_private_setting_commands_open_inline_selectors(handler_name: str, expected_prefix: str) -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=7711, title=None, type="private"),
        effective_user=SimpleNamespace(id=7028236763, username="botadmin", full_name="Bot Admin", first_name="Bot"),
        effective_message=message,
    )
    context = SimpleNamespace(
        args=[],
        bot=None,
        application=SimpleNamespace(bot_data={"database": database}),
    )
    handlers = {
        "setstate_command": setstate_command,
        "setsubject_command": setsubject_command,
        "setinterval_command": setinterval_command,
    }
    await handlers[handler_name](update, context)
    assert len(message.replies) == 1
    callback_data = [
        button.callback_data
        for row in message.replies[0]["reply_markup"].inline_keyboard
        for button in row
    ]
    assert any(data.startswith(expected_prefix) for data in callback_data)
    await database.dispose()


@pytest.mark.asyncio
async def test_private_setlanguage_opens_language_buttons() -> None:
    from bot.handlers.dm import setlanguage_command

    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=7712, title=None, type="private"),
        effective_user=SimpleNamespace(id=7028236763, username="botadmin", full_name="Bot Admin", first_name="Bot"),
        effective_message=message,
    )
    context = SimpleNamespace(args=[], application=SimpleNamespace(bot_data={"database": database}))
    await setlanguage_command(update, context)
    callback_data = [
        button.callback_data
        for row in message.replies[0]["reply_markup"].inline_keyboard
        for button in row
    ]
    assert {"dset:langval:Hindi", "dset:langval:English"}.issubset(callback_data)
    await database.dispose()


def test_private_dm_settings_interval_matches_group_button_labels() -> None:
    from bot.handlers.dm import dm_interval_selector_keyboard
    from bot.handlers.group_setup import interval_selector_keyboard

    dm_labels = [
        button.text
        for row in dm_interval_selector_keyboard().inline_keyboard
        for button in row
    ]
    group_labels = [
        button.text
        for row in interval_selector_keyboard().inline_keyboard
        for button in row
    ]
    assert dm_labels == group_labels


from types import SimpleNamespace


@pytest.mark.asyncio
async def test_mocktest_defaults_to_five_questions_and_thirty_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot.handlers import admin

    captured: dict[str, object] = {}

    async def allow_admin(*args, **kwargs) -> bool:
        return True

    class FakeQuizService:
        async def create_mock_lobby(self, group_id: int, **kwargs):
            captured.update(group_id=group_id, **kwargs)
            return 9001

    monkeypatch.setattr(admin, "_admin_group", allow_admin)
    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-7713, title="Mock Group", type="supergroup"),
        effective_user=SimpleNamespace(id=7028236763, username="botadmin", full_name="Bot Admin"),
        effective_message=message,
    )
    context = SimpleNamespace(args=[], application=SimpleNamespace(bot_data={"quiz_service": FakeQuizService()}))

    await admin.mocktest_admin_command(update, context)

    assert captured["count"] == 5
    assert captured["round_seconds"] == 30
    assert message.replies == []


@pytest.mark.asyncio
async def test_private_startquiz_first_activation_sends_immediate_question() -> None:
    from bot.handlers.dm import dmstart_command

    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    message = FakeMessage()
    calls: list[int] = []

    class FakeQuizService:
        async def send_quiz(self, group_id: int, **kwargs):
            calls.append(group_id)
            return object()

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=8801, title=None, type="private"),
        effective_user=SimpleNamespace(id=8801, username="private_student", full_name="Private Student", first_name="Private"),
        effective_message=message,
    )
    context = SimpleNamespace(
        args=[], application=SimpleNamespace(bot_data={"database": database, "quiz_service": FakeQuizService()})
    )

    await dmstart_command(update, context)

    assert calls == [8801]
    assert "Private Automatic Quiz शुरू हो गया है" in message.replies[0]["text"]
    assert "हर 10 मिनट" in message.replies[0]["text"]
    await database.dispose()


@pytest.mark.asyncio
async def test_private_startquiz_when_active_only_reports_schedule() -> None:
    from bot.handlers.dm import dmstart_command

    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(8802, "Private Student", "private")
        await repo.update_settings(8802, quiz_active=True, interval_minutes=20, language="Hindi")
        await repo.commit()
    message = FakeMessage()
    calls: list[int] = []

    class FakeQuizService:
        async def send_quiz(self, group_id: int, **kwargs):
            calls.append(group_id)
            return object()

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=8802, title=None, type="private"),
        effective_user=SimpleNamespace(id=8802, username="private_student", full_name="Private Student", first_name="Private"),
        effective_message=message,
    )
    context = SimpleNamespace(
        args=[], application=SimpleNamespace(bot_data={"database": database, "quiz_service": FakeQuizService()})
    )

    await dmstart_command(update, context)

    assert calls == []
    assert "पहले से ON" in message.replies[0]["text"]
    assert "हर 20 मिनट" in message.replies[0]["text"]
    assert "/stopquiz" in message.replies[0]["text"]
    await database.dispose()


@pytest.mark.asyncio
async def test_group_stopquiz_requires_confirmation_and_reports_already_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot.handlers import admin

    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-8810, "Stop Group", "supergroup")
        await repo.update_settings(-8810, quiz_active=True, language="Hindi")
        await repo.commit()

    async def allow_admin(*args, **kwargs) -> bool:
        return True

    monkeypatch.setattr(admin, "_admin_group", allow_admin)
    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-8810, title="Stop Group", type="supergroup"),
        effective_user=SimpleNamespace(id=7028236763, full_name="Bot Admin"), effective_message=message,
    )
    context = SimpleNamespace(args=[], application=SimpleNamespace(bot_data={"database": database}))

    await admin.stopquiz_command(update, context)
    assert "बंद करने की पुष्टि" in message.replies[0]["text"]
    callbacks = [button.callback_data for row in message.replies[0]["reply_markup"].inline_keyboard for button in row]
    assert callbacks == ["gset:stopconfirm", "gset:stopcancel"]
    async with database.session_factory() as session:
        settings = await Repository(session).get_settings(-8810)
        assert settings and settings.quiz_active is True

    async with database.session_factory() as session:
        await Repository(session).update_settings(-8810, quiz_active=False)
        await session.commit()
    message = FakeMessage()
    update.effective_message = message
    await admin.stopquiz_command(update, context)
    assert "पहले से OFF" in message.replies[0]["text"]
    assert "/startquiz" in message.replies[0]["text"]
    assert "reply_markup" not in message.replies[0]
    await database.dispose()


@pytest.mark.asyncio
async def test_private_stopquiz_requires_confirmation_and_reports_already_off() -> None:
    from bot.handlers.dm import dmstop_command

    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(8811, "Private Stop", "private")
        await repo.update_settings(8811, quiz_active=True, language="Hindi")
        await repo.commit()

    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=8811, title=None, type="private"),
        effective_user=SimpleNamespace(id=8811, username="private", full_name="Private Stop", first_name="Private"),
        effective_message=message,
    )
    context = SimpleNamespace(args=[], application=SimpleNamespace(bot_data={"database": database}))

    await dmstop_command(update, context)
    assert "बंद करने की पुष्टि" in message.replies[0]["text"]
    callbacks = [button.callback_data for row in message.replies[0]["reply_markup"].inline_keyboard for button in row]
    assert callbacks == ["dset:stopconfirm", "dset:stopcancel"]

    async with database.session_factory() as session:
        await Repository(session).update_settings(8811, quiz_active=False)
        await session.commit()
    message = FakeMessage()
    update.effective_message = message
    await dmstop_command(update, context)
    assert "पहले से OFF" in message.replies[0]["text"]
    assert "/startquiz" in message.replies[0]["text"]
    assert "reply_markup" not in message.replies[0]
    await database.dispose()


@pytest.mark.asyncio
async def test_mocktest_reports_already_running_without_creating_lobby(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot.handlers import admin

    async def allow_admin(*args, **kwargs) -> bool:
        return True

    class FakeQuizService:
        async def create_mock_lobby(self, *args, **kwargs):
            return -1

    monkeypatch.setattr(admin, "_admin_group", allow_admin)
    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-7714, title="Mock Group", type="supergroup"),
        effective_user=SimpleNamespace(id=7028236763, username="botadmin", full_name="Bot Admin"),
        effective_message=message,
    )
    context = SimpleNamespace(args=[], application=SimpleNamespace(bot_data={"quiz_service": FakeQuizService()}))

    await admin.mocktest_admin_command(update, context)

    assert "Mock Test पहले से तैयार या चल रहा है" in message.replies[0]["text"]
    assert "थोड़ी देर बाद फिर प्रयास करें" in message.replies[0]["text"]
    assert "reply_markup" not in message.replies[0]

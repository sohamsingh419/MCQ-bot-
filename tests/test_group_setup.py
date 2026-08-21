from types import SimpleNamespace

import pytest
from telegram.constants import ChatMemberStatus

from bot.database.database import Database
from bot.database.repositories import Repository
from bot.handlers.group_setup import (
    group_welcome_on_join,
    settings_callback,
    settings_panel_keyboard,
    welcome_keyboard,
    welcome_text,
)


class FakeGroupBot:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, *args, **kwargs) -> None:
        self.sent.append(kwargs if kwargs else {"chat_id": args[0], "text": args[1]})

    async def get_chat_member(self, chat_id: int, user_id: int):
        return SimpleNamespace(status=ChatMemberStatus.OWNER)


class FakeSettingsQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.message = SimpleNamespace(chat=SimpleNamespace(id=-401, title="Study Group", type="supergroup"))
        self.from_user = SimpleNamespace(id=51, full_name="Group Owner", username="owner")
        self.answers: list[tuple[tuple, dict]] = []
        self.edits: list[tuple[tuple, dict]] = []

    async def answer(self, *args, **kwargs) -> None:
        self.answers.append((args, kwargs))

    async def edit_message_text(self, *args, **kwargs) -> None:
        self.edits.append((args, kwargs))

    async def edit_message_reply_markup(self, *args, **kwargs) -> None:
        self.edits.append((args, kwargs))


@pytest.mark.asyncio
async def test_group_join_sends_welcome_with_group_settings_panel() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    bot = FakeGroupBot()
    update = SimpleNamespace(
        my_chat_member=SimpleNamespace(
            chat=SimpleNamespace(id=-401, title="Study Group", type="supergroup"),
            old_chat_member=SimpleNamespace(status=ChatMemberStatus.LEFT),
            new_chat_member=SimpleNamespace(status=ChatMemberStatus.MEMBER),
        )
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": database}), bot=bot)
    await group_welcome_on_join(update, context)
    assert len(bot.sent) == 1
    assert "मुझे इस ग्रुप में जोड़ने के लिए धन्यवाद" in bot.sent[0]["text"]
    buttons = [button.callback_data for row in bot.sent[0]["reply_markup"].inline_keyboard for button in row]
    assert {"gset:state", "gset:subjects", "gset:language", "gset:interval", "gset:quiz"}.issubset(buttons)
    assert "gset:difficulty" not in buttons
    await database.dispose()


@pytest.mark.asyncio
async def test_owner_can_change_language_from_settings_panel() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    bot = FakeGroupBot()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": database}), bot=bot)
    query = FakeSettingsQuery("gset:langval:English")
    await settings_callback(SimpleNamespace(callback_query=query), context)
    assert query.edits
    async with database.session_factory() as session:
        settings = await Repository(session).get_settings(-401)
        assert settings and settings.language == "English"
    await database.dispose()


def test_welcome_and_settings_panel_are_complete_and_user_friendly() -> None:
    text = welcome_text("Study Group")
    assert "मैं क्या कर सकता हूँ" in text and "/settings" in text
    settings = SimpleNamespace(
        quiz_active=False, state="All India", language="Hindi", difficulty="Exam",
        interval_minutes=15, rotation_enabled=True, explanation_enabled=True,
    )
    buttons = [button.text for row in settings_panel_keyboard(settings).inline_keyboard for button in row]
    callbacks = [button.callback_data for row in settings_panel_keyboard(settings).inline_keyboard for button in row]
    assert "🔙 वापस" in buttons
    assert "✖️ बंद करें" not in buttons
    assert "gset:back" in callbacks and "gset:close" not in callbacks
    assert "🗺️ क्षेत्र / राज्य" in buttons
    assert "📚 विषय" in buttons
    assert not any("कठिनाई" in button for button in buttons)
    assert "🌐 भाषा" in buttons
    assert "⏱️ क्विज़ अंतराल" in buttons
    assert "▶️ क्विज़ शुरू करें" in buttons
    assert not any("विषय क्रम" in button or "व्याख्या" in button or "टेस्ट प्रश्न" in button for button in buttons)
    assert "gset:rotation" not in callbacks and "gset:explain" not in callbacks and "gset:test" not in callbacks

    welcome = welcome_keyboard(settings)
    assert len(welcome.inline_keyboard) == 6
    assert all(len(row) == 2 for row in welcome.inline_keyboard)
    assert sum(len(row) for row in welcome.inline_keyboard) == 12
    welcome_buttons = [button.text for row in welcome.inline_keyboard for button in row]
    welcome_callbacks = [button.callback_data for row in welcome.inline_keyboard for button in row]
    welcome_urls = {button.text: button.url for row in welcome.inline_keyboard for button in row if button.url}
    assert "⚙️ Settings" in welcome_buttons and "❓ Help" in welcome_buttons
    assert "gset:home" in welcome_callbacks and "hact:help" in welcome_callbacks
    assert welcome_urls["💬 Support Group"] == "https://t.me/+OzztqZ23h8AxYWZl"
    assert welcome_urls["📢 Support Channel"] == "https://t.me/GSI_QUIZ"
    assert welcome_urls["👤 Owner Contact"] == "https://t.me/Global_X_SohaN"

    from bot.handlers.start import private_quick_actions_keyboard
    private_urls = {
        button.text: button.url
        for row in private_quick_actions_keyboard("Hindi").inline_keyboard
        for button in row
        if button.url
    }
    assert private_urls == welcome_urls


@pytest.mark.asyncio
async def test_group_start_returns_welcome_keyboard_with_settings_and_help() -> None:
    from bot.handlers.start import start_command

    class StartMessage:
        def __init__(self) -> None:
            self.replies: list[dict] = []

        async def reply_text(self, text, **kwargs) -> None:
            self.replies.append({"text": text, **kwargs})

    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    message = StartMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-402, type="supergroup", title="Study Group"),
        effective_user=SimpleNamespace(id=52, username="owner", full_name="Group Owner", first_name="Owner"),
        effective_message=message,
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": database}))

    await start_command(update, context)

    assert message.replies
    callbacks = [
        button.callback_data
        for row in message.replies[0]["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "gset:home" in callbacks and "hact:help" in callbacks
    await database.dispose()


@pytest.mark.asyncio
async def test_regular_member_cannot_change_group_settings_from_panel() -> None:
    class MemberBot(FakeGroupBot):
        async def get_chat_member(self, chat_id: int, user_id: int):
            return SimpleNamespace(status=ChatMemberStatus.MEMBER)

    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": database}), bot=MemberBot())
    query = FakeSettingsQuery("gset:langval:English")
    await settings_callback(SimpleNamespace(callback_query=query), context)
    assert query.answers and query.answers[-1][1].get("show_alert") is True
    async with database.session_factory() as session:
        settings = await Repository(session).get_settings(-401)
        assert settings is None
    await database.dispose()


def test_private_and_group_state_selectors_use_direct_paginated_state_names() -> None:
    from bot.handlers.group_setup import state_selector_keyboard
    from bot.handlers.start import INDIAN_STATES, state_menu_keyboard, state_page_count

    private_page_0 = state_menu_keyboard("Hindi", 0)
    private_page_1 = state_menu_keyboard("Hindi", 1)
    private_page_last = state_menu_keyboard("Hindi", state_page_count() - 1)
    group_page_0 = state_selector_keyboard(0)
    group_page_1 = state_selector_keyboard(1)

    private_data_0 = [button.callback_data for row in private_page_0.inline_keyboard for button in row]
    private_data_1 = [button.callback_data for row in private_page_1.inline_keyboard for button in row]
    private_data_last = [button.callback_data for row in private_page_last.inline_keyboard for button in row]
    group_data_0 = [button.callback_data for row in group_page_0.inline_keyboard for button in row]
    group_data_1 = [button.callback_data for row in group_page_1.inline_keyboard for button in row]

    assert "onb:state:All India" in private_data_0
    assert "onb:statepage:1" in private_data_0 and "onb:statepage:0" in private_data_1
    assert not any(data.startswith("onb:region:") for data in private_data_0)
    assert not any(data.startswith("onb:statepage:") and data.endswith(str(state_page_count())) for data in private_data_last)
    assert "gset:stateval:All India" in group_data_0
    assert "gset:statepage:1" in group_data_0 and "gset:statepage:0" in group_data_1
    assert all(f"onb:state:{state}" in [button.callback_data for row in state_menu_keyboard("Hindi", index // 10).inline_keyboard for button in row] for index, state in enumerate(INDIAN_STATES))


@pytest.mark.asyncio
async def test_group_state_page_navigation_and_direct_state_selection_persist() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    bot = FakeGroupBot()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": database}), bot=bot)

    page_query = FakeSettingsQuery("gset:statepage:1")
    await settings_callback(SimpleNamespace(callback_query=page_query), context)
    assert page_query.edits
    assert "राज्य सूची: 2/3" in page_query.edits[-1][0][0]

    selection_query = FakeSettingsQuery("gset:stateval:Karnataka")
    await settings_callback(SimpleNamespace(callback_query=selection_query), context)
    async with database.session_factory() as session:
        settings = await Repository(session).get_settings(-401)
        assert settings and settings.state == "Karnataka"
    await database.dispose()



def test_group_details_are_group_name_first_and_advanced() -> None:
    from bot.utils.helpers import settings_text

    settings = SimpleNamespace(
        state="Rajasthan", language="Hindi", subjects=["State GK", "Indian History", "Indian Geography"],
        quiz_active=True, interval_minutes=10, rotation_enabled=True, explanation_enabled=True,
    )
    text = settings_text(settings, "Work")
    assert text.startswith("⚙️ <b>Work — Quiz Settings</b>")
    assert "🏷 <b>Group:</b> Work" in text
    assert "📍 <b>State:</b> Rajasthan" in text
    assert "📚 <b>Subjects:</b> Rajasthan GK • History • Geography" in text
    assert "📡 <b>Automatic Quiz:</b> 🟢 Running" in text
    assert "Subject Rotation:</b> 🟢 ALWAYS ON" in text
    assert "Explanation:</b> 🟢 ALWAYS ON" in text


@pytest.mark.asyncio
async def test_startquiz_first_activation_sends_one_immediate_question(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot.handlers import admin

    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        settings = await repo.ensure_group(-402, "Work", "supergroup")
        await repo.update_settings(-402, quiz_active=False, interval_minutes=15, language="Hindi")
        await repo.commit()

    class FakeMessage:
        def __init__(self) -> None:
            self.replies: list[dict] = []

        async def reply_text(self, text: str, **kwargs) -> None:
            self.replies.append({"text": text, **kwargs})

    class FakeQuizService:
        def __init__(self) -> None:
            self.calls = 0

        async def send_quiz(self, group_id: int, **kwargs):
            self.calls += 1
            return object()

    async def allow_admin(*args, **kwargs) -> bool:
        return True

    monkeypatch.setattr(admin, "_admin_group", allow_admin)
    message = FakeMessage()
    service = FakeQuizService()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-402, title="Work", type="supergroup"),
        effective_user=SimpleNamespace(id=51, full_name="Owner"), effective_message=message,
    )
    context = SimpleNamespace(args=[], bot=None, application=SimpleNamespace(bot_data={"database": database, "quiz_service": service}))

    await admin.startquiz_command(update, context)

    assert service.calls == 1
    assert "Automatic Quiz शुरू हो गया है" in message.replies[0]["text"]
    assert "हर 15 मिनट" in message.replies[0]["text"]
    async with database.session_factory() as session:
        settings = await Repository(session).get_settings(-402)
        assert settings and settings.quiz_active is True
    await database.dispose()


@pytest.mark.asyncio
async def test_startquiz_when_already_active_does_not_send_immediate_question(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot.handlers import admin

    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-403, "Existing Group", "supergroup")
        await repo.update_settings(-403, quiz_active=True, interval_minutes=20, language="Hindi")
        await repo.commit()

    class FakeMessage:
        def __init__(self) -> None:
            self.replies: list[dict] = []

        async def reply_text(self, text: str, **kwargs) -> None:
            self.replies.append({"text": text, **kwargs})

    class FakeQuizService:
        def __init__(self) -> None:
            self.calls = 0

        async def send_quiz(self, *args, **kwargs):
            self.calls += 1
            return object()

    async def allow_admin(*args, **kwargs) -> bool:
        return True

    monkeypatch.setattr(admin, "_admin_group", allow_admin)
    message = FakeMessage()
    service = FakeQuizService()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-403, title="Existing Group", type="supergroup"),
        effective_user=SimpleNamespace(id=51, full_name="Owner"), effective_message=message,
    )
    context = SimpleNamespace(args=[], bot=None, application=SimpleNamespace(bot_data={"database": database, "quiz_service": service}))

    await admin.startquiz_command(update, context)

    assert service.calls == 0
    assert "पहले से ON" in message.replies[0]["text"]
    assert "हर 20 मिनट" in message.replies[0]["text"]
    assert "/stopquiz" in message.replies[0]["text"]
    await database.dispose()

from types import SimpleNamespace

import pytest
from telegram.constants import ChatMemberStatus

from bot.database.database import Database
from bot.handlers.callbacks import help_action_callback
from bot.handlers.start import help_action_keyboard


class FakeHelpQuery:
    def __init__(self, data: str, chat_type: str, chat_id: int) -> None:
        self.data = data
        self.message = SimpleNamespace(chat=SimpleNamespace(id=chat_id, type=chat_type, title="Study Group"))
        self.from_user = SimpleNamespace(id=9101, full_name="Learner", first_name="Learner", username="learner")
        self.answers: list[tuple[tuple, dict]] = []
        self.edits: list[tuple[tuple, dict]] = []

    async def answer(self, *args, **kwargs) -> None:
        self.answers.append((args, kwargs))

    async def edit_message_text(self, *args, **kwargs) -> None:
        self.edits.append((args, kwargs))


class MemberBot:
    async def get_chat_member(self, chat_id: int, user_id: int):
        return SimpleNamespace(status=ChatMemberStatus.MEMBER)


@pytest.mark.asyncio
async def test_private_help_settings_button_opens_personal_dashboard() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    query = FakeHelpQuery("hact:dmsettings", "private", 9101)
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": database}), bot=MemberBot())
    await help_action_callback(SimpleNamespace(callback_query=query), context)
    assert query.edits
    assert "मेरी पढ़ाई की सेटिंग्स" in query.edits[-1][0][0]
    await database.dispose()


@pytest.mark.asyncio
async def test_group_help_settings_button_rejects_regular_member() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    query = FakeHelpQuery("hact:gsettings", "supergroup", -9101)
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": database}), bot=MemberBot())
    await help_action_callback(SimpleNamespace(callback_query=query), context)
    assert query.answers and query.answers[-1][1].get("show_alert") is True
    await database.dispose()


def test_help_keyboards_expose_direct_action_callbacks() -> None:
    private_actions = [button.callback_data for row in help_action_keyboard("Hindi", "private").inline_keyboard for button in row]
    group_actions = [button.callback_data for row in help_action_keyboard("Hindi", "supergroup").inline_keyboard for button in row]
    assert {"hact:dmsettings", "hact:dmstart", "hact:dmstop", "hact:profile"}.issubset(private_actions)
    assert {"hact:gsettings", "hact:startquiz", "hact:stopquiz", "hact:groupstats"}.issubset(group_actions)
    assert "hact:dmtest" not in private_actions
    assert "hact:testquestion" not in group_actions

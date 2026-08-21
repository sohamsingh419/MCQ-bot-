from types import SimpleNamespace

import pytest

from bot.config import default_subjects_for_state, display_subject_for_state, subjects_for_state, toggle_subject_selection
from bot.database.database import Database
from bot.database.repositories import Repository
from bot.handlers.dm import dm_settings_callback, dm_settings_keyboard, dm_subject_selector_keyboard
from bot.handlers.group_setup import subject_selector_keyboard
from bot.services.quiz import QuizService


class FakeDMQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.message = SimpleNamespace(chat=SimpleNamespace(id=8801, type="private", title=None))
        self.from_user = SimpleNamespace(id=8801, full_name="Learner", first_name="Learner", username="learner")
        self.answers: list[tuple[tuple, dict]] = []
        self.edits: list[tuple[tuple, dict]] = []

    async def answer(self, *args, **kwargs) -> None:
        self.answers.append((args, kwargs))

    async def edit_message_text(self, *args, **kwargs) -> None:
        self.edits.append((args, kwargs))

    async def edit_message_reply_markup(self, *args, **kwargs) -> None:
        self.edits.append((args, kwargs))


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[tuple, dict]] = []

    async def send_message(self, *args, **kwargs) -> None:
        self.sent.append((args, kwargs))


def test_subject_catalog_changes_between_all_india_and_state_profiles() -> None:
    all_india = subjects_for_state("All India")
    rajasthan = subjects_for_state("Rajasthan")
    assert "State GK" not in all_india
    assert "State GK" in rajasthan
    assert "State History" in rajasthan
    assert "State Art & Culture" in rajasthan
    assert rajasthan[0] == "State GK"
    assert "All India GK" not in rajasthan
    assert default_subjects_for_state("Rajasthan") == ["State GK"]
    assert default_subjects_for_state("All India") == ["All India GK"]
    assert all_india[0] == "All India GK"


def test_state_subject_display_names_include_selected_state_only_for_state_subjects() -> None:
    assert display_subject_for_state("Rajasthan", "State GK") == "Rajasthan GK"
    assert display_subject_for_state("Rajasthan", "State History") == "Rajasthan History"
    assert display_subject_for_state("Rajasthan", "State Art & Culture") == "Rajasthan Art & Culture"
    assert display_subject_for_state("All India", "Indian Polity") == "Indian Polity"
    assert display_subject_for_state("All India", "State GK") == "State GK"

    state_settings = SimpleNamespace(state="Rajasthan", subjects=default_subjects_for_state("Rajasthan"))
    group_labels = [button.text for row in subject_selector_keyboard(state_settings).inline_keyboard for button in row]
    dm_labels = [button.text for row in dm_subject_selector_keyboard(state_settings).inline_keyboard for button in row]
    assert "✅ Rajasthan GK" in group_labels and "✅ State GK" not in group_labels
    assert "✅ Rajasthan GK" in dm_labels
    assert "✅ Rajasthan History" not in dm_labels and "✅ Rajasthan Art & Culture" not in dm_labels

    india_settings = SimpleNamespace(state="All India", subjects=default_subjects_for_state("All India"))
    india_labels = [button.text for row in subject_selector_keyboard(india_settings).inline_keyboard for button in row]
    assert "✅ All India GK" in india_labels
    assert "✅ Indian Polity" not in india_labels


def test_quiz_subject_selection_defaults_to_state_relevant_practice() -> None:
    state_settings = SimpleNamespace(state="Rajasthan", subjects=[], rotation_enabled=False, current_rotation_index=0)
    india_settings = SimpleNamespace(state="All India", subjects=[], rotation_enabled=False, current_rotation_index=0)
    assert QuizService.subject_for_next_quiz(state_settings) == "State GK"
    assert QuizService.subject_for_next_quiz(india_settings) == "All India GK"
    assert toggle_subject_selection("Rajasthan", ["State GK"], "State History") == ["State History"]
    assert toggle_subject_selection("Rajasthan", ["State History"], "State Geography") == ["State History", "State Geography"]
    assert toggle_subject_selection("All India", ["All India GK"], "Indian History") == ["Indian History"]


@pytest.mark.asyncio
async def test_dm_settings_state_change_updates_subjects_and_dashboard() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": database}), bot=FakeBot())
    query = FakeDMQuery("dset:stateval:Rajasthan")
    await dm_settings_callback(SimpleNamespace(callback_query=query), context)
    assert query.edits
    async with database.session_factory() as session:
        settings = await Repository(session).get_settings(8801)
        assert settings and settings.state == "Rajasthan"
        assert settings.subjects == default_subjects_for_state("Rajasthan")
    await database.dispose()


def test_dm_settings_panel_exposes_full_personal_controls() -> None:
    settings = SimpleNamespace(
        quiz_active=False, state="All India", language="Hindi", difficulty="Exam",
        interval_minutes=15, rotation_enabled=True, explanation_enabled=True,
    )
    buttons = [button.callback_data for row in dm_settings_keyboard(settings).inline_keyboard for button in row]
    assert {"dset:state", "dset:subjects", "dset:language", "dset:interval", "dset:quiz", "dset:info", "dset:back"}.issubset(buttons)
    assert not {"dset:rotation", "dset:explain", "dset:test"}.intersection(buttons)
    assert "dset:close" not in buttons

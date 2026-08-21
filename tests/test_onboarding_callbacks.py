from types import SimpleNamespace

import pytest

from bot.database.database import Database
from bot.database.repositories import Repository
from bot.handlers.callbacks import onboarding_callback


class FakeOnboardingQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.message = SimpleNamespace(chat=SimpleNamespace(id=9901, type="private"))
        self.from_user = SimpleNamespace(id=9901, username="learner", full_name="Onboarding Learner", first_name="Learner")
        self.answers: list[tuple[tuple, dict]] = []
        self.edits: list[tuple[tuple, dict]] = []

    async def answer(self, *args, **kwargs) -> None:
        self.answers.append((args, kwargs))

    async def edit_message_text(self, *args, **kwargs) -> None:
        self.edits.append((args, kwargs))


@pytest.mark.asyncio
async def test_state_selection_opens_subjects_directly_without_exam_step() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": database}))
    query = FakeOnboardingQuery("onb:state:Rajasthan")

    await onboarding_callback(SimpleNamespace(callback_query=query), context)

    assert query.edits
    assert "अपना विषय चुनें" in query.edits[-1][0][0]
    callbacks = [
        button.callback_data
        for row in query.edits[-1][1]["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "onb:subjects_done" in callbacks
    assert not any(callback.startswith("onb:exam") for callback in callbacks)
    await database.dispose()


@pytest.mark.asyncio
async def test_private_subjects_support_multi_select_and_done() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(9901, "Private Study", "private")
        await repo.update_settings(9901, state="All India", subjects=[])
        await repo.commit()
    calls: list[int] = []

    class FakeQuizService:
        async def send_quiz(self, chat_id: int, **kwargs):
            calls.append(chat_id)
            return object()

    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"database": database, "quiz_service": FakeQuizService()})
    )

    for data in ("onb:subject:Indian Polity", "onb:subject:Indian Geography", "onb:subjects_done"):
        query = FakeOnboardingQuery(data)
        await onboarding_callback(SimpleNamespace(callback_query=query), context)
        assert query.edits

    async with database.session_factory() as session:
        repo = Repository(session)
        settings = await repo.get_settings(9901)
        user = await repo.get_user(9901)
        assert settings and settings.subjects == ["Indian Polity", "Indian Geography"]
        assert settings.quiz_active is True
        assert user and user.onboarding_completed is True
    assert calls == [9901]
    assert "आपकी Study Profile तैयार है" in query.edits[-1][0][0]
    callbacks = [
        button.callback_data
        for row in query.edits[-1][1]["reply_markup"].inline_keyboard
        for button in row
    ]
    assert {"onb:state_menu", "onb:subjects_menu", "menu:settings", "menu:help", "hact:profile"}.issubset(callbacks)
    await database.dispose()


@pytest.mark.asyncio
async def test_onboarding_callbacks_save_profile_and_activate_private_quizzes() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": database}))

    for data in ("onb:language:Hindi", "onb:state:All India", "onb:finish"):
        query = FakeOnboardingQuery(data)
        await onboarding_callback(SimpleNamespace(callback_query=query), context)
        assert query.edits

    async with database.session_factory() as session:
        repo = Repository(session)
        user = await repo.get_user(9901)
        settings = await repo.get_settings(9901)
        assert user and user.preferred_language == "Hindi"
        assert user.onboarding_completed is True
        assert user.exam_preparation is None
        assert settings and settings.state == "All India" and settings.quiz_active is True
    await database.dispose()


def test_onboarding_state_menu_covers_all_indian_states() -> None:
    from bot.config import VALID_STATES
    from bot.handlers.start import INDIAN_STATES

    offered = set(INDIAN_STATES)
    assert len(offered) == 28
    assert offered.issubset(VALID_STATES)
    assert "All India" in VALID_STATES


def test_complete_hindi_help_covers_every_registered_command_and_fits_telegram() -> None:
    from bot.handlers.start import group_help_text, onboarding_language_text, private_help_text

    private_text = private_help_text("Hindi")
    group_text = group_help_text("Hindi")
    welcome_text = onboarding_language_text("Learner")
    assert "⚙️ जब चाहें नीचे दिए गए options से अपनी State, Subjects, Language और Settings बदल सकते हैं।" in welcome_text
    help_text = private_text + group_text
    assert private_text == group_text
    commands = (
        "/start", "/help", "/profile", "/score", "/stats", "/rank", "/leaderboard",
        "/daily", "/weekly", "/monthly", "/subjects", "/setlanguage", "/settings",
        "/startquiz", "/stopquiz", "/setinterval", "/setstate", "/setsubjects",
        "/mocktest",
        "/startquiz", "/stopquiz",
        "/addquestion", "/removequestion", "/groupstats",
    )
    assert all(command in help_text for command in commands)
    assert all(command not in help_text for command in ("/setexplanation", "/setmode", "/setxp", "/testquestion", "/setrotation"))
    assert "`/" not in help_text
    assert len(private_text) <= 4096 and len(group_text) <= 4096


def test_help_menu_has_requested_bilingual_role_sections() -> None:
    from bot.handlers.start import group_help_text, onboarding_language_text

    hindi = group_help_text("Hindi")
    english = group_help_text("English")
    for text in (hindi, english):
        assert "GSI Quiz" in text
        assert "FOR EVERY LEARNER" in text or "हर विद्यार्थी के लिए" in text
        assert "GROUP OWNER & ADMIN CONTROLS" in text
        assert "BOT ADMIN CONTROLS" in text
        assert "COMMON COMMANDS" in text
        assert "/createquiz" in text and "/botreport" in text
    assert "Help menu फिर से खोलें" in hindi
    assert "Open this Help menu again" in english
    assert "केवल configured Bot Admin" in hindi
    assert "Only the configured Bot Admin" in english
    welcome = onboarding_language_text("विद्यार्थी")
    assert "अपनी तैयारी को रोज़ थोड़ा बेहतर" in welcome
    assert "AI-powered study bot" not in welcome


def test_redesigned_hindi_onboarding_uses_natural_study_language() -> None:
    from bot.handlers.start import confirmation_keyboard, language_keyboard, onboarding_language_text, onboarding_state_text

    welcome = onboarding_language_text("विद्यार्थी")
    state_step = onboarding_state_text("Hindi")
    labels = [button.text for row in language_keyboard().inline_keyboard for button in row]
    labels += [button.text for row in confirmation_keyboard("Hindi").inline_keyboard for button in row]
    assert "चरण" not in welcome and "AI-powered" not in welcome
    assert "अपनी तैयारी को रोज़ थोड़ा बेहतर" in welcome
    assert "जिस राज्य या पूरे भारत" in state_step
    assert "हिंदी" in labels and "English" in labels and "✨ मेरी पढ़ाई शुरू करें" in labels

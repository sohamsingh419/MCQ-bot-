from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from bot.database.database import Database
from bot.config import syllabus_topics_for
from bot.database.repositories import Repository
from bot.handlers.callbacks import explanation_callback
from bot.services.ai_generator import AIQuestionGenerationError
from bot.services.question_validator import ValidQuestion
from bot.services.quiz import QuizService


class FakeGenerator:
    async def generate(self, **kwargs):
        return ValidQuestion(
            question="भारतीय संविधान का संरक्षक किसे माना जाता है?",
            options=["सर्वोच्च न्यायालय", "संसद", "राष्ट्रपति", "निर्वाचन आयोग"],
            correct_option=0,
            explanation="संविधान की व्याख्या और संरक्षण में सर्वोच्च न्यायालय की केंद्रीय भूमिका है।",
            key_point="न्यायिक समीक्षा सर्वोच्च न्यायालय की मुख्य शक्ति है।",
            subject="Indian Polity",
            topic="Judiciary",
            difficulty="Exam",
            question_type="Conceptual",
            language="Hindi",
        )


class FakePollBot:
    def __init__(self):
        self.poll_kwargs = None
        self.polls = []
        self.messages = []
        self.edits = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)
        return SimpleNamespace(message_id=kwargs.get("message_id"))

    async def send_poll(self, **kwargs):
        self.poll_kwargs = kwargs
        self.polls.append(kwargs)
        poll_id = "no-timer-poll" if len(self.polls) == 1 else f"no-timer-poll-{len(self.polls)}"
        return SimpleNamespace(poll=SimpleNamespace(id=poll_id), message_id=30 + len(self.polls))

    async def stop_poll(self, **kwargs):
        return SimpleNamespace()


@pytest.mark.asyncio
async def test_new_chat_defaults_to_hindi_and_poll_has_no_timer() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        settings = await repo.ensure_group(-3001, "Hindi Study", "group")
        assert settings.language == "Hindi"
        await repo.update_settings(-3001, quiz_active=True)
        await repo.commit()

    bot = FakePollBot()
    service = QuizService(bot, database, SimpleNamespace(question_similarity_threshold=0.86, ai_model="test"), FakeGenerator())
    sent = await service.send_quiz(-3001, force=True)
    assert sent is not None
    assert bot.poll_kwargs["open_period"] is None
    assert bot.poll_kwargs["question"] == "भारतीय संविधान का संरक्षक किसे माना जाता है?"
    assert bot.poll_kwargs["options"] == ["सर्वोच्च न्यायालय", "संसद", "राष्ट्रपति", "निर्वाचन आयोग"]
    assert bot.messages == []
    keyboard = bot.poll_kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].callback_data.startswith("explain:")
    assert keyboard.inline_keyboard[0][0].text == "व्याख्या देखें"

    async with database.session_factory() as session:
        history = await Repository(session).get_quiz_by_poll("no-timer-poll")
        settings = await Repository(session).get_settings(-3001)
        assert history and history.closes_at is None
        assert settings and settings.source_mode == "source"
    await database.dispose()


@pytest.mark.asyncio
async def test_quiz_alternates_ai_then_source_questions() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    topic = syllabus_topics_for("Rajasthan", "State GK")[0]
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-3004, "Alternating Study", "group")
        await repo.update_settings(-3004, state="Rajasthan", language="Hindi", subjects=["State GK"], quiz_active=True, source_mode="ai")
        await repo.add_question(
            question_text="राजस्थान का राज्य पक्षी कौन सा है?",
            options=["गोडावण", "मोर", "सारस", "कोयल"], correct_option=0,
            explanation="गोडावण राजस्थान का राज्य पक्षी है।", key_point="राज्य पक्षी गोडावण है।",
            state="Rajasthan", subject="State GK", topic=topic, difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="source",
        )
        await repo.commit()

    class StateGenerator:
        async def generate(self, **kwargs):
            return ValidQuestion(
                question="राजस्थान का प्रसिद्ध वन्यजीव क्षेत्र कौन सा है?", options=["गोडावण", "मोर", "सारस", "कोयल"],
                correct_option=0, explanation="यह राजस्थान से संबंधित तथ्य है।", key_point="राजस्थान तथ्य।",
                subject=kwargs["subject"], topic=kwargs["topic"], difficulty="Exam",
                question_type="Conceptual", language="Hindi",
            )

    bot = FakePollBot()
    service = QuizService(bot, database, SimpleNamespace(question_similarity_threshold=0.86, ai_model="test"), StateGenerator())
    first = await service.send_quiz(-3004, force=True)
    second = await service.send_quiz(-3004, force=True)
    assert first and second
    assert first.source == "ai"
    assert second.source == "source"
    async with database.session_factory() as session:
        settings = await Repository(session).get_settings(-3004)
        assert settings and settings.source_mode == "ai"
    await database.dispose()


class FailingGenerator:
    async def generate(self, **kwargs):
        raise AIQuestionGenerationError("provider returned no completion")


@pytest.mark.asyncio
async def test_stored_question_fallback_keeps_quiz_delivery_working_when_ai_fails() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-3002, "Fallback Study", "group")
        await repo.update_settings(-3002, state="Rajasthan", language="Hindi", subjects=["State GK"], quiz_active=True)
        question = await repo.add_question(
            question_text="राजस्थान की राजधानी कौन सी है?",
            options=["जयपुर", "जोधपुर", "उदयपुर", "कोटा"], correct_option=0,
            explanation="जयपुर राजस्थान की राजधानी है।", key_point="राजस्थान की राजधानी जयपुर है।",
            state="Rajasthan", subject="State GK", topic="राजस्थान", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        question.is_used = True
        await repo.commit()

    bot = FakePollBot()
    service = QuizService(bot, database, SimpleNamespace(question_similarity_threshold=0.86, ai_model="test"), FailingGenerator())
    sent = await service.send_quiz(-3002, force=True)
    assert sent is not None
    assert bot.poll_kwargs["question"] == "राजस्थान की राजधानी कौन सी है?"
    assert bot.poll_kwargs["options"] == ["जयपुर", "जोधपुर", "उदयपुर", "कोटा"]
    await database.dispose()


@pytest.mark.asyncio
async def test_mock_test_uses_cached_fallback_when_ai_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-3003, "Fallback Mock", "group")
        await repo.update_settings(-3003, state="Rajasthan", language="Hindi", subjects=["State GK"], quiz_active=True)
        question = await repo.add_question(
            question_text="राजस्थान का राज्य पक्षी कौन सा है?",
            options=["गोडावण", "मोर", "सारस", "कोयल"], correct_option=0,
            explanation="गोडावण राजस्थान का राज्य पक्षी है।", key_point="गोडावण राजस्थान का राज्य पक्षी है।",
            state="Rajasthan", subject="State GK", topic="राजस्थान", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        question.is_used = True
        second_question = await repo.add_question(
            question_text="राजस्थान का सबसे बड़ा जिला क्षेत्रफल के आधार पर कौन सा है?",
            options=["जैसलमेर", "बीकानेर", "बाड़मेर", "उदयपुर"], correct_option=0,
            explanation="जैसलमेर क्षेत्रफल की दृष्टि से राजस्थान का सबसे बड़ा जिला है।", key_point="जैसलमेर सबसे बड़ा जिला है।",
            state="Rajasthan", subject="State GK", topic="राजस्थान", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        second_question.is_used = True
        await repo.commit()

    bot = FakePollBot()
    service = QuizService(bot, database, SimpleNamespace(question_similarity_threshold=0.86, ai_model="test"), FailingGenerator())
    mock_id = await service.create_mock_lobby(-3003, count=2, round_seconds=10, title="Fallback Mock", created_by=1)
    assert mock_id is not None
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.upsert_user(1, "one", "One")
        await repo.upsert_user(2, "two", "Two")
        assert await repo.join_mock_test(mock_id, 1) == 1
        assert await repo.join_mock_test(mock_id, 2) == 2
        await repo.commit()
    assert await service.start_mock_test(mock_id) is True
    assert len(bot.polls) == 1
    assert bot.polls[0]["open_period"] == 10
    assert await service.advance_mock_round(mock_id) is True
    assert len(bot.polls) == 2
    assert bot.polls[1]["open_period"] == 10
    assert bot.polls[0]["question"] != bot.polls[1]["question"]
    assert await service.advance_mock_round(mock_id) is False
    await database.dispose()


def test_long_question_uses_full_card_and_compact_answer_poll() -> None:
    long_question = SimpleNamespace(
        question_text="भारत के संवैधानिक विकास, स्वतंत्रता आंदोलन और प्रशासनिक संस्थाओं से संबंधित इस विस्तृत प्रश्न का सही उत्तर चुनिए।",
        options=["पहला विस्तृत विकल्प जो native poll में बहुत लंबा हो जाएगा", "दूसरा विकल्प", "तीसरा विकल्प", "चौथा विकल्प"],
        language="Hindi",
    )
    assert QuizService.uses_single_poll_layout(long_question) is False
    poll_question, poll_options = QuizService.poll_content(long_question)
    assert poll_question == "सही उत्तर चुनें"
    assert poll_options == ["A", "B", "C", "D"]


class FakeDirectBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)


class FakeQuery:
    def __init__(self, question_id: int):
        self.data = f"explain:{question_id}"
        self.from_user = SimpleNamespace(id=8101)
        self.answers = []

    async def answer(self, *args, **kwargs):
        self.answers.append((args, kwargs))


@pytest.mark.asyncio
async def test_explanation_callback_sends_only_to_requesting_user_dm() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        question = await repo.add_question(
            question_text="भारत की राजधानी क्या है?",
            options=["नई दिल्ली", "मुंबई", "कोलकाता", "चेन्नई"],
            correct_option=0,
            explanation="नई दिल्ली भारत की राजधानी है।",
            key_point="भारत की केंद्रीय सरकार नई दिल्ली से संचालित होती है।",
            state="General", subject="General Knowledge", topic="India", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        await repo.commit()

    direct_bot = FakeDirectBot()
    query = FakeQuery(question.id)
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"database": database}),
        bot=direct_bot,
    )
    await explanation_callback(SimpleNamespace(callback_query=query), context)
    assert direct_bot.sent[0]["chat_id"] == 8101
    assert "सही उत्तर" in direct_bot.sent[0]["text"]
    await database.dispose()


def test_hindi_first_onboarding_exposes_all_required_steps() -> None:
    from bot.handlers.start import (
        confirmation_keyboard, confirmation_text, language_keyboard,
        onboarding_language_text, state_menu_keyboard,
    )

    language_callbacks = [button.callback_data for row in language_keyboard().inline_keyboard for button in row]
    hindi_state_keyboard = state_menu_keyboard("Hindi")
    english_state_keyboard = state_menu_keyboard("English")
    state_callbacks = [button.callback_data for row in hindi_state_keyboard.inline_keyboard for button in row]
    confirmation_callbacks = [button.callback_data for row in confirmation_keyboard("Hindi").inline_keyboard for button in row]
    hindi_state_buttons = [button.text for row in hindi_state_keyboard.inline_keyboard for button in row]
    english_state_buttons = [button.text for row in english_state_keyboard.inline_keyboard for button in row]
    assert "onb:language:Hindi" in language_callbacks
    assert "onb:state:All India" in state_callbacks
    assert "🇮🇳 All India" in hindi_state_buttons and "🇮🇳 All India" in english_state_buttons
    assert "← वापस" in hindi_state_buttons and "← Back" in english_state_buttons
    assert "onb:welcome" in state_callbacks
    assert "onb:language_menu" not in state_callbacks
    assert confirmation_callbacks == ["onb:finish", "onb:subjects_menu"]
    assert "आपके स्तर के MCQ" in onboarding_language_text("विद्यार्थी")
    confirmation = confirmation_text("Tech × Sohan", "Hindi", "Rajasthan", None, ["Indian Polity", "Indian History", "Indian Geography", "General Science"])
    assert "परीक्षा:" not in confirmation and "Exam:" not in confirmation
    assert "✅ *आपकी Study Profile तैयार है!*" in confirmation
    assert "👤 *प्रोफ़ाइल:* Tech × Sohan" in confirmation
    assert "📍 *राज्य:* Rajasthan" in confirmation
    assert "📚 *विषय:* Indian Polity • History • Geography • General Science" in confirmation
    assert "GSI Quiz Bot" in confirmation


@pytest.mark.asyncio
async def test_stop_mock_test_cancels_active_lobby() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-3004, "Stop Mock", "group")
        await repo.update_settings(-3004, state="Rajasthan", language="Hindi", subjects=["State GK"], quiz_active=True)
        await repo.commit()

    bot = FakePollBot()
    service = QuizService(bot, database, SimpleNamespace(question_similarity_threshold=0.86, ai_model="test"), FailingGenerator())
    mock_id = await service.create_mock_lobby(-3004, count=2, round_seconds=10, title="Stop Mock", created_by=1)
    assert mock_id is not None
    assert await service.stop_mock_test(-3004) == mock_id
    async with database.session_factory() as session:
        mock = await Repository(session).get_mock_test(mock_id)
        assert mock and mock.status == "cancelled"
    await database.dispose()


@pytest.mark.asyncio
async def test_normal_chat_never_replays_an_exhausted_question() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-3005, "No Repeat", "group")
        await repo.update_settings(-3005, state="Rajasthan", language="Hindi", subjects=["State GK"], quiz_active=True)
        question = await repo.add_question(
            question_text="राजस्थान का राज्य पशु कौन सा है?",
            options=["ऊँट", "बाघ", "चीतल", "नीलगाय"], correct_option=0,
            explanation="ऊँट राजस्थान का राज्य पशु है।", key_point="राजस्थान का राज्य पशु ऊँट है।",
            state="Rajasthan", subject="State GK", topic="राजस्थान", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        question.is_used = True
        await repo.commit()

    bot = FakePollBot()
    service = QuizService(bot, database, SimpleNamespace(question_similarity_threshold=0.86, ai_model="test"), FailingGenerator())
    assert await service.send_quiz(-3005, force=True) is not None
    assert await service.send_quiz(-3005, force=True) is None
    assert len(bot.polls) == 1
    await database.dispose()


@pytest.mark.asyncio
async def test_mock_round_retries_transient_telegram_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timedelta, timezone
    from telegram.error import NetworkError

    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-3010, "Retry Mock", "group")
        await repo.update_settings(-3010, state="Rajasthan", subjects=["State GK"], quiz_active=True)
        mock = await repo.create_mock_test(
            group_id=-3010, title="Retry Mock", count=2, round_seconds=10, subjects=["State GK"],
            state="Rajasthan", difficulty="Exam", starts_at=datetime.now(timezone.utc),
            lobby_closes_at=None, ends_at=datetime.now(timezone.utc) + timedelta(minutes=5), created_by=1,
        )
        await repo.start_mock_test(mock.id, starts_at=datetime.now(timezone.utc), ends_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        await repo.commit()

    bot = FakePollBot()
    service = QuizService(bot, database, SimpleNamespace(question_similarity_threshold=0.86, ai_model="test"), FailingGenerator())
    calls = 0

    async def flaky_send_quiz(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise NetworkError("temporary disconnect")
        return SimpleNamespace(id=999)

    monkeypatch.setattr(service, "send_quiz", flaky_send_quiz)
    assert await service.send_next_mock_round(mock.id) is True
    assert calls == 2
    await database.dispose()



def test_all_india_gk_is_first_and_subject_menu_uses_back_button() -> None:
    from bot.config import syllabus_topics_for, subjects_for_state
    from bot.handlers.start import subject_keyboard

    subjects = subjects_for_state("All India")
    assert subjects[0] == "All India GK"
    assert {"Indian Polity", "Indian History", "Indian Geography", "Indian Culture", "Current Affairs"}.issubset(set(subjects))
    topics = syllabus_topics_for("All India", "All India GK")
    assert all(category in " ".join(topics) for category in ("संविधान", "जलवायु", "इतिहास", "Current Affairs"))

    buttons = [button for row in subject_keyboard("All India", "Hindi").inline_keyboard for button in row]
    assert buttons[0].text == "🇮🇳 All India GK"
    assert buttons[0].callback_data == "onb:subject:All India GK"
    labels = [button.text for button in buttons]
    callbacks = [button.callback_data for button in buttons]
    assert "Indian History" in labels and "Indian Geography" in labels
    assert "← वापस" in labels
    assert "✅ Done" in labels
    assert "onb:state_menu" in callbacks
    assert "onb:subjects_done" in callbacks
    assert "onb:exam_menu" not in callbacks

    private_buttons = [
        button
        for row in subject_keyboard("All India", "Hindi", back_callback="onb:welcome").inline_keyboard
        for button in row
    ]
    assert "onb:welcome" in [button.callback_data for button in private_buttons]
    selected_buttons = [
        button
        for row in subject_keyboard(
            "All India", "Hindi", back_callback="onb:welcome", selected_subjects=["Indian Polity", "Indian Geography"]
        ).inline_keyboard
        for button in row
    ]
    selected_labels = [button.text for button in selected_buttons]
    assert "✅ Indian Polity" in selected_labels and "✅ Indian Geography" in selected_labels


@pytest.mark.asyncio
async def test_mock_test_ends_once_when_no_validated_question_is_available() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-3005, "Unavailable Mock", "group")
        await repo.update_settings(-3005, state="Rajasthan", language="Hindi", subjects=["State GK"], quiz_active=True)
        await repo.upsert_user(1, "one", "One")
        await repo.upsert_user(2, "two", "Two")
        await repo.commit()

    bot = FakePollBot()
    service = QuizService(bot, database, SimpleNamespace(question_similarity_threshold=0.86, ai_model="test"), FailingGenerator())
    mock_id = await service.create_mock_lobby(-3005, count=2, round_seconds=30, title="Unavailable Mock", created_by=1)
    assert mock_id is not None
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.join_mock_test(mock_id, 1)
        await repo.join_mock_test(mock_id, 2)
        await repo.commit()

    assert await service.start_mock_test(mock_id) is False
    assert len([item for item in bot.messages if "validated question" in item.get("text", "")]) == 1
    async with database.session_factory() as session:
        mock = await Repository(session).get_mock_test(mock_id)
        assert mock is not None and mock.status == "completed"
    await database.dispose()


@pytest.mark.asyncio
async def test_expired_mock_edits_original_lobby_instead_of_sending_duplicate() -> None:
    from datetime import datetime, timedelta, timezone

    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-3011, "Lobby Edit", "group")
        await repo.update_settings(-3011, state="Rajasthan", subjects=["State GK"], language="Hindi")
        mock = await repo.create_mock_test(
            group_id=-3011, title="Lobby Edit", count=5, round_seconds=30, subjects=["State GK"],
            state="Rajasthan", difficulty="Exam", starts_at=datetime.now(timezone.utc),
            ends_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            lobby_closes_at=datetime.now(timezone.utc), created_by=1,
        )
        mock.lobby_message_id = 777
        await repo.commit()

    bot = FakePollBot()
    service = QuizService(bot, database, SimpleNamespace(question_similarity_threshold=0.86, ai_model="test"), FailingGenerator())
    assert await service.start_mock_test(mock.id) is False
    assert len(bot.edits) == 1
    assert bot.edits[0]["message_id"] == 777
    assert "Mock Test रद्द हो गया" in bot.edits[0]["text"]
    assert bot.edits[0]["reply_markup"] is None
    assert bot.messages == []
    await database.dispose()


@pytest.mark.asyncio
async def test_mock_lobby_creation_blocks_second_lobby_until_first_finishes() -> None:
    from datetime import datetime, timedelta, timezone

    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-3012, "Single Mock", "group")
        await repo.commit()

    bot = FakePollBot()
    service = QuizService(bot, database, SimpleNamespace(question_similarity_threshold=0.86, ai_model="test"), FailingGenerator())
    first = await service.create_mock_lobby(-3012, count=5, round_seconds=30, title="Mock Test", created_by=1)
    second = await service.create_mock_lobby(-3012, count=5, round_seconds=30, title="Mock Test", created_by=1)
    assert first is not None and first > 0
    assert second == -1

    async with database.session_factory() as session:
        repo = Repository(session)
        mock = await repo.get_mock_test(first)
        assert mock is not None
        await repo.start_mock_test(first, starts_at=datetime.now(timezone.utc), ends_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        await repo.commit()
    third = await service.create_mock_lobby(-3012, count=5, round_seconds=30, title="Mock Test", created_by=1)
    assert third == -1
    await database.dispose()

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.database.database import Database
from bot.database.repositories import Repository
from bot.services.official_quiz import OfficialQuizService
from bot.services.quiz import QuizService


def test_title_transfer_announcement_is_polished_and_winner_specific() -> None:
    winner_row = {"user_id": 77, "display_name": "Winner Student"}
    gsi_text = OfficialQuizService._title_transfer_announcement_text("gsi", winner_row)
    star_text = OfficialQuizService._title_transfer_announcement_text(
        "star", winner_row, SimpleNamespace(star_count=3)
    )
    assert "OFFICIAL TITLE TRANSFER" in gsi_text
    assert "Winner Student" in gsi_text
    assert "Grand Scholar of India" in gsi_text
    assert "OFFICIAL TITLE TRANSFER" in star_text
    assert "Winner Student" in star_text
    assert "Star Quizzer ×3" in star_text


def test_gsi_winner_template_renders_exact_display_name() -> None:
    template = Path(__file__).parents[1] / "assets" / "gsi_winner_template.png"
    assert template.exists()
    rendered = OfficialQuizService._render_gsi_winner_card(template, "परीक्षा विजेता")
    try:
        assert rendered is not None and rendered.exists()
        assert rendered.read_bytes() != template.read_bytes()
    finally:
        if rendered:
            rendered.unlink(missing_ok=True)


class OfficialFakeBot:
    def __init__(self):
        self.messages = []
        self.polls = []
        self.photos = []
        self.animations = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return SimpleNamespace(message_id=len(self.messages))

    async def send_poll(self, **kwargs):
        self.polls.append(kwargs)
        return SimpleNamespace(
            poll=SimpleNamespace(id=f"official-poll-{len(self.polls)}"),
            message_id=100 + len(self.polls),
        )

    async def stop_poll(self, **kwargs):
        return SimpleNamespace()

    async def send_photo(self, **kwargs):
        self.photos.append(kwargs)

    async def send_animation(self, **kwargs):
        self.animations.append(kwargs)


@pytest.mark.asyncio
async def test_official_quiz_lifecycle_uses_joined_users_and_visible_progress():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-1003799884627, "Official Play", "supergroup")
        question = await repo.add_question(
            question_text="राजस्थान की राजधानी क्या है?",
            options=["जयपुर", "जोधपुर", "उदयपुर", "अजमेर"], correct_option=0,
            explanation="जयपुर राजधानी है।", key_point="राजस्थान की राजधानी जयपुर है।",
            state="Rajasthan", subject="State GK", topic="राजधानी", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        question_two = await repo.add_question(
            question_text="राजस्थान का राज्य पक्षी कौन सा है?",
            options=["गोडावण", "मोर", "सारस", "कोयल"], correct_option=0,
            explanation="गोडावण राज्य पक्षी है।", key_point="राजस्थान का राज्य पक्षी गोडावण है।",
            state="Rajasthan", subject="State GK", topic="राज्य प्रतीक", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        await repo.commit()

    bot = OfficialFakeBot()
    quiz_service = QuizService(bot, database, SimpleNamespace(question_similarity_threshold=0.86, ai_model="test"), None)
    service = OfficialQuizService(bot, database, quiz_service)
    quiz = await service.create_quiz(
        created_by=7028236763, quiz_type="star", slug="staraug2026",
        title="Star Quiz August", rules="हर सही उत्तर 1 point का है।", count=2, round_seconds=5,
        question_items=[
            {"question": "राजस्थान की राजधानी क्या है?", "options": ["जयपुर", "जोधपुर", "उदयपुर", "अजमेर"], "correct_option": 0},
            {"question": "राजस्थान का राज्य पक्षी कौन सा है?", "options": ["गोडावण", "मोर", "सारस", "कोयल"], "correct_option": 0},
        ],
    )
    assert quiz.question_ids == [question.id, question_two.id]
    ok, _ = await service.launch("staraug2026")
    assert ok is True
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.upsert_user(101, "one", "One")
        await repo.commit()
    joined_quiz, count = await service.join(quiz.id, 101, "one", "One")
    assert joined_quiz and count == 1
    started_quiz, participants, error = await service.begin_countdown(quiz.id)
    assert started_quiz and participants == 1 and error is None
    assert await service.start_after_countdown(quiz.id) is True
    assert len(bot.polls) == 1
    assert bot.polls[0]["open_period"] == 5
    assert bot.polls[0]["question"].startswith("[1/2]")
    await database.dispose()


@pytest.mark.asyncio
async def test_multiple_gsi_quizzes_are_allowed_with_unique_ids():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-1003799884627, "Official Play", "supergroup")
        await repo.add_question(
            question_text="भारत का राष्ट्रीय पशु कौन सा है?",
            options=["बाघ", "सिंह", "हाथी", "मोर"], correct_option=0,
            explanation="बाघ राष्ट्रीय पशु है।", key_point="भारत का राष्ट्रीय पशु बाघ है।",
            state="All India", subject="General Knowledge", topic="राष्ट्रीय प्रतीक", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        await repo.add_question(
            question_text="भारत का राष्ट्रीय पक्षी कौन सा है?",
            options=["मोर", "गरुड़", "सारस", "हंस"], correct_option=0,
            explanation="मोर राष्ट्रीय पक्षी है।", key_point="भारत का राष्ट्रीय पक्षी मोर है।",
            state="All India", subject="General Knowledge", topic="राष्ट्रीय प्रतीक", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        await repo.commit()
    bot = OfficialFakeBot()
    service = OfficialQuizService(
        bot, database, QuizService(bot, database, SimpleNamespace(question_similarity_threshold=0.86, ai_model="test"), None)
    )
    await service.create_quiz(
                    created_by=1, quiz_type="gsi", slug="gsi-first", title="GSI First", rules="Rules", count=2, round_seconds=5,
            question_items=[
                {"question": "भारत का राष्ट्रीय पशु कौन सा है?", "options": ["बाघ", "सिंह", "हाथी", "मोर"], "correct_option": 0},
                {"question": "भारत का राष्ट्रीय पक्षी कौन सा है?", "options": ["मोर", "गरुड़", "सारस", "हंस"], "correct_option": 0},
            ],

    )
    second = await service.create_quiz(
        created_by=1, quiz_type="gsi", slug="gsi-second", title="GSI Second", rules="Rules", count=2, round_seconds=5,
        question_items=[
            {"question": "भारत का राष्ट्रीय पशु दूसरा कौन सा है?", "options": ["बाघ", "सिंह", "हाथी", "मोर"], "correct_option": 0},
            {"question": "भारत का राष्ट्रीय पक्षी दूसरा कौन सा है?", "options": ["मोर", "गरुड़", "सारस", "हंस"], "correct_option": 0},
        ],
    )
    assert second.slug == "gsi-second"
    with pytest.raises(ValueError, match="unique Quiz ID already exists"):
        await service.create_quiz(
            created_by=1, quiz_type="gsi", slug="gsi-second", title="GSI Duplicate ID", rules="Rules", count=2, round_seconds=5,
            question_items=[
                {"question": "अलग प्रश्न एक", "options": ["A", "B", "C", "D"], "correct_option": 0},
                {"question": "अलग प्रश्न दो", "options": ["A", "B", "C", "D"], "correct_option": 1},
            ],
        )
    await database.dispose()


@pytest.mark.asyncio
async def test_completed_official_quiz_finalize_is_idempotent() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-1003799884627, "Official Play", "supergroup")
        question = await repo.add_question(
            question_text="भारत की राजधानी क्या है?", options=["नई दिल्ली", "मुंबई", "जयपुर", "पटना"],
            correct_option=0, explanation="नई दिल्ली राजधानी है।", key_point="राजधानी नई दिल्ली है।",
            state="All India", subject="General Knowledge", topic="राजधानी", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        quiz = await repo.create_official_quiz(
            slug="completed-idempotent", quiz_type="star", title="Completed Star", rules="Rules", month_key="2026-08",
            config_group_id=-1003511361627, play_group_id=-1003799884627, source_group_id=None,
            question_count=1, round_seconds=5, question_ids=[question.id], created_by=1,
        )
        quiz.status = "completed"
        await repo.commit()

    bot = OfficialFakeBot()
    service = OfficialQuizService(
        bot, database, QuizService(bot, database, SimpleNamespace(question_similarity_threshold=0.86, ai_model="test"), None)
    )
    await service.finalize(quiz.id)
    assert bot.photos == []
    assert bot.messages == []
    await database.dispose()


@pytest.mark.asyncio
async def test_official_result_persists_star_reward_and_title():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    now = datetime.now(timezone.utc)
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-1003799884627, "Official Play", "supergroup")
        question = await repo.add_question(
            question_text="भारत की राजधानी क्या है?",
            options=["नई दिल्ली", "मुंबई", "जयपुर", "पटना"], correct_option=0,
            explanation="नई दिल्ली राजधानी है।", key_point="भारत की राजधानी नई दिल्ली है।",
            state="All India", subject="General Knowledge", topic="राजधानी", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        await repo.upsert_user(77, "winner", "Winner")
        quiz = await repo.create_official_quiz(
            slug="star-result", quiz_type="star", title="Star Result", rules="Rules", month_key="2026-08",
            config_group_id=-1003511361627, play_group_id=-1003799884627, source_group_id=None,
            question_count=2, round_seconds=5, question_ids=[question.id, question.id], created_by=1,
        )
        await repo.join_official_quiz(quiz.id, 77)
        await repo.start_official_countdown(quiz.id, now)
        await repo.start_official_quiz(quiz.id, now, now + timedelta(minutes=5))
        await repo.record_quiz(
            group_id=-1003799884627, question_id=question.id, poll_id="result-poll", message_id=1,
            quiz_kind="official_star", closes_at=now + timedelta(seconds=5), official_quiz_id=quiz.id,
            official_question_number=1,
        )
        await repo.record_answer(
            poll_id="result-poll", group_id=-1003799884627, question_id=question.id, user_id=77,
            selected_option=0, is_correct=True, xp_awarded=0, points_awarded=1,
        )
        await repo.commit()
    bot = OfficialFakeBot()
    service = OfficialQuizService(
        bot, database, QuizService(bot, database, SimpleNamespace(question_similarity_threshold=0.86, ai_model="test"), None)
    )
    await service.finalize(quiz.id)
    async with database.session_factory() as session:
        repo = Repository(session)
        winner = await repo.get_user(77)
        completed = await repo.get_official_quiz(quiz.id)
        assert winner and winner.star_count == 1 and winner.star_title == "Star Quizzer ×1"
        assert completed and completed.status == "completed" and completed.winner_user_id == 77
    await database.dispose()



def test_admin_text_mcq_parser_preserves_question_options_and_answer():
    from bot.handlers.official_quiz import _parse_text_mcq

    item = _parse_text_mcq(
        "राजस्थान की राजधानी क्या है?\nA. जयपुर\nB. जोधपुर\nC. उदयपुर\nD. अजमेर\nAnswer: A"
    )
    assert item == {
        "question": "राजस्थान की राजधानी क्या है?",
        "options": ["जयपुर", "जोधपुर", "उदयपुर", "अजमेर"],
        "correct_option": 0,
    }


def test_admin_text_mcq_parser_rejects_missing_answer():
    from bot.handlers.official_quiz import _parse_text_mcq

    assert _parse_text_mcq(
        "भारत की राजधानी क्या है?\nA. नई दिल्ली\nB. मुंबई\nC. जयपुर\nD. पटना"
    ) is None



def test_inline_forwarded_mcq_and_batch_answer_key_are_supported():
    from bot.handlers.official_quiz import _parse_answer_key, _parse_text_mcq

    item = _parse_text_mcq(
        "1. राजस्थान का राज्य वृक्ष कौन-सा है? A) नीम B) खेजड़ी C) पीपल D) बरगद ✅ उत्तर: B खेजड़ी"
    )
    assert item is not None
    assert item["question"] == "राजस्थान का राज्य वृक्ष कौन-सा है?"
    assert item["options"] == ["नीम", "खेजड़ी", "पीपल", "बरगद ✅"]
    assert item["correct_option"] == 1
    assert _parse_answer_key("1-C, 2-B, 3-A, 4-D") == {1: 2, 2: 1, 3: 0, 4: 3}

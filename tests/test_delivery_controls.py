from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from telegram.constants import ChatMemberStatus

from bot.config import get_settings
from bot.database.database import Database
from bot.database.repositories import Repository
from bot.handlers import admin
from bot.handlers.callbacks import explanation_callback
from bot.config import syllabus_topics_for
from bot.services.ai_generator import question_types_for_difficulty
from bot.services.quiz import QuizService
from bot.services.scoring import ScoringService


class PollBot:
    def __init__(self, status=ChatMemberStatus.ADMINISTRATOR):
        self.status = status
        self.polls = []
        self.messages = []

    async def get_me(self):
        return SimpleNamespace(id=90001)

    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status=self.status)

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return SimpleNamespace(message_id=len(self.messages))

    async def send_poll(self, **kwargs):
        self.polls.append(kwargs)
        return SimpleNamespace(
            poll=SimpleNamespace(id=f"poll-{len(self.polls)}"),
            message_id=100 + len(self.polls),
        )


class Generator:
    async def generate(self, **kwargs):
        raise AssertionError("stored question should satisfy this test")


class Message:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, **kwargs})


class Query:
    def __init__(self, question_id, user_id, group_id, message_id):
        self.data = f"explain:{question_id}"
        self.from_user = SimpleNamespace(id=user_id)
        self.message = SimpleNamespace(
            chat=SimpleNamespace(id=group_id, type="group"),
            message_id=message_id,
        )
        self.answers = []

    async def answer(self, *args, **kwargs):
        self.answers.append((args, kwargs))


@pytest.mark.asyncio
async def test_group_delivery_is_blocked_until_bot_is_admin():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-701, "Needs Admin", "supergroup")
        await repo.update_settings(-701, state="Rajasthan", subjects=["State GK"], bot_is_admin=False)
        question = await repo.add_question(
            question_text="राजस्थान का राज्य पशु कौन सा है?", options=["ऊँट", "बाघ", "चीतल", "नीलगाय"],
            correct_option=0, explanation="ऊँट।", key_point="राजस्थान का राज्य पशु ऊँट है।",
            state="Rajasthan", subject="State GK", topic="राज्य प्रतीक", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        await repo.commit()
    bot = PollBot(ChatMemberStatus.MEMBER)
    service = QuizService(bot, database, SimpleNamespace(
        question_similarity_threshold=0.86, ai_model="test", timezone="UTC",
    ), Generator())
    assert await service.send_quiz(-701, force=True) is None
    assert bot.polls == []
    await database.dispose()


@pytest.mark.asyncio
async def test_global_question_delivery_switch_blocks_and_resumes_all_poll_delivery(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "7028236763")
    get_settings.cache_clear()
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-702, "Global Control", "supergroup")
        await repo.update_settings(-702, state="Rajasthan", subjects=["State GK"], bot_is_admin=True)
        await repo.add_question(
            question_text="राजस्थान का राज्य वृक्ष कौन सा है?", options=["नीम", "खेजड़ी", "पीपल", "बरगद"],
            correct_option=1, explanation="खेजड़ी।", key_point="खेजड़ी राज्य वृक्ष है।",
            state="Rajasthan", subject="State GK", topic=syllabus_topics_for("Rajasthan", "State GK")[0], difficulty="Exam",
            question_type=question_types_for_difficulty("Exam", subject="State GK")[0], language="Hindi", source="admin",
        )
        await repo.commit()
    bot = PollBot()
    service = QuizService(bot, database, SimpleNamespace(
        question_similarity_threshold=0.86, ai_model="test", timezone="UTC",
    ), Generator())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=7028236763), effective_message=Message())
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": database}))
    await admin.questiondelivery_off_command(update, context)
    assert "OFF" in update.effective_message.replies[-1]["text"]
    assert await service.send_quiz(-702, force=True) is None
    assert bot.polls == []
    await admin.questiondelivery_on_command(update, context)
    assert "ON" in update.effective_message.replies[-1]["text"]
    assert await service.send_quiz(-702, force=True) is not None
    assert len(bot.polls) == 1
    get_settings.cache_clear()
    await database.dispose()


@pytest.mark.asyncio
async def test_correct_streak_notice_is_sent_only_to_started_private_chat():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    now = datetime.now(timezone.utc)
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-703, "Streak Group", "supergroup")
        await repo.update_settings(-703, bot_is_admin=True)
        await repo.ensure_group(703, "Learner DM", "private")
        user = await repo.upsert_user(703, "learner", "Learner")
        user.current_streak = 2
        question = await repo.add_question(
            question_text="भारत की राजधानी क्या है?", options=["नई दिल्ली", "मुंबई", "जयपुर", "पटना"],
            correct_option=0, explanation="नई दिल्ली।", key_point="नई दिल्ली राजधानी है।",
            state="General", subject="General Knowledge", topic="राजधानी", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        await repo.record_quiz(
            group_id=-703, question_id=question.id, poll_id="streak-poll", message_id=1,
            quiz_kind="automatic", closes_at=now,
        )
        await repo.commit()
    bot = PollBot()
    await ScoringService(database, bot).process_poll_answer(SimpleNamespace(
        poll_id="streak-poll", option_ids=[0], user=SimpleNamespace(id=703, username="learner", full_name="Learner"),
    ))
    assert len(bot.messages) == 1
    assert bot.messages[0]["chat_id"] == 703
    assert "3" in bot.messages[0]["text"]
    await database.dispose()


@pytest.mark.asyncio
async def test_explanation_is_blocked_until_requesting_user_answers():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(-704, "Explanation Group", "supergroup")
        await repo.update_settings(-704, bot_is_admin=True)
        question = await repo.add_question(
            question_text="भारत का राष्ट्रीय पशु कौन सा है?", options=["बाघ", "सिंह", "हाथी", "मोर"],
            correct_option=0, explanation="बाघ।", key_point="बाघ राष्ट्रीय पशु है।",
            state="All India", subject="General Knowledge", topic="राष्ट्रीय प्रतीक", difficulty="Exam",
            question_type="Conceptual", language="Hindi", source="admin",
        )
        await repo.record_quiz(
            group_id=-704, question_id=question.id, poll_id="explain-poll", message_id=44,
            quiz_kind="automatic", closes_at=None,
        )
        await repo.commit()
    bot = PollBot()
    query = Query(question.id, 704, -704, 44)
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": database}), bot=bot)
    await explanation_callback(SimpleNamespace(callback_query=query), context)
    assert bot.messages == []
    assert query.answers and query.answers[-1][1].get("show_alert") is True
    await database.dispose()

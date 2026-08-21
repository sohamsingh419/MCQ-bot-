"""Admin wizard and callbacks for official GSI and Star quizzes."""
from __future__ import annotations

import asyncio
import html
import logging
import re

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from bot.config import get_settings
from bot.services.official_quiz import OfficialQuizService

logger = logging.getLogger(__name__)

TYPE, SLUG, TITLE, COUNT, TIMER, RULES, QUESTIONS, ANSWERS, CONFIRM = range(9)


def _service(context: ContextTypes.DEFAULT_TYPE) -> OfficialQuizService:
    return context.application.bot_data["official_quiz_service"]


def _is_bot_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id in get_settings().global_admin_ids)


def _in_config_group(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.id == OfficialQuizService.config_group_id())


def _in_play_group(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.id == OfficialQuizService.play_group_id())


def _draft(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault("official_quiz_draft", {})


async def _save_draft(update: Update, context: ContextTypes.DEFAULT_TYPE, step: str) -> None:
    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None:
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        from bot.database.repositories import Repository
        repo = Repository(session)
        await repo.save_official_draft(user_id, step, dict(_draft(context)))
        await repo.commit()


def _language(question: str, options: list[str]) -> str:
    return "Hindi" if re.search(r"[\u0900-\u097F]", question + " " + " ".join(options)) else "English"


def _question_type(question: str) -> str:
    return "Statement-based" if re.search(r"\bstatements?\b|कथनों|कथन\s*[१२३४1-4]", question, re.IGNORECASE) else "Conceptual"


def _option_index(value: str) -> int | None:
    normalized = value.strip().upper()
    if normalized in {"A", "1"}:
        return 0
    if normalized in {"B", "2"}:
        return 1
    if normalized in {"C", "3"}:
        return 2
    if normalized in {"D", "4"}:
        return 3
    return None


def _parse_text_mcq(text: str) -> dict | None:
    """Parse both line-based and forwarded inline MCQ text without rewriting it."""
    raw = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if not raw:
        return None
    answer_match = re.search(
        r"(?:answer|correct\s*answer|सही\s*उत्तर|उत्तर)\s*[:\-]?\s*\(?([ABCD1-4])\)?\b",
        raw,
        re.IGNORECASE,
    )
    answer_index = _option_index(answer_match.group(1)) if answer_match else None
    option_pattern = re.compile(r"(?:^|\s|\()([ABCD])\s*[.)\-:]\s*", re.IGNORECASE)
    matches = list(option_pattern.finditer(raw))
    if len(matches) != 4:
        # Also accept a clean line format where the option marker is at line start.
        matches = list(re.finditer(r"(?m)^\s*([ABCD1-4])\s*[.)\-:]\s*", text, re.IGNORECASE))
        raw = text
    if len(matches) != 4 or answer_index is None:
        return None
    parsed: list[tuple[int, str]] = []
    for position, match in enumerate(matches):
        index = _option_index(match.group(1))
        if index is None:
            return None
        start = match.end()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(raw)
        value = raw[start:end].strip(" \t:-")
        value = re.split(r"(?:answer|correct\s*answer|सही\s*उत्तर|उत्तर)\s*[:\-]?", value, maxsplit=1, flags=re.IGNORECASE)[0].strip(" \t:-")
        if not value:
            return None
        parsed.append((index, value))
    parsed.sort(key=lambda item: item[0])
    if [index for index, _ in parsed] != [0, 1, 2, 3]:
        return None
    question = raw[:matches[0].start()].strip(" \t:-")
    question = re.sub(r"^\d+\s*[.)]\s*", "", question).strip()
    if not question:
        return None
    return {"question": question, "options": [value for _, value in parsed], "correct_option": answer_index}


def _parse_answer_key(text: str) -> dict[int, int]:
    """Parse batches such as 1-B, 2-C, 3-A or 1 B 2 C."""
    pairs = re.findall(r"(?:^|[,;\s])\s*(\d+)\s*[-:=]?\s*\(?([ABCD1-4])\)?\b", text.strip(), re.IGNORECASE)
    result: dict[int, int] = {}
    for number, letter in pairs:
        index = _option_index(letter)
        if index is not None:
            result[int(number)] = index
    return result


def _extract_mcq(message) -> tuple[dict | None, str | None]:
    poll = getattr(message, "poll", None)
    if poll is not None:
        if getattr(poll, "type", None) != "quiz":
            return None, "केवल Telegram Quiz Poll भेजें, सामान्य poll नहीं।"
        options = [option.text.strip() for option in getattr(poll, "options", [])]
        correct = getattr(poll, "correct_option_id", None)
        if len(options) != 4 or any(not option for option in options):
            return None, "MCQ poll में ठीक 4 खाली न होने वाले options होने चाहिए।"
        return {
            "question": poll.question.strip(), "options": options,
            "correct_option": int(correct) if correct is not None and 0 <= int(correct) < 4 else None,
            "answer_pending": correct is None,
        }, None
    text = getattr(message, "text", None) or getattr(message, "caption", None)
    parsed = _parse_text_mcq(text or "")
    if parsed is None:
        return None, (
            "MCQ स्वीकार नहीं हुआ। Forwarded MCQ को सीधे भेजें या इस format में भेजें:\n"
            "Question\nA) पहला option\nB) दूसरा option\nC) तीसरा option\nD) चौथा option\nउत्तर: B"
        )
    return parsed, None


async def createquiz_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_message or not _is_bot_admin(update) or not _in_config_group(update):
        if update.effective_message:
            await update.effective_message.reply_text("यह command केवल bot admin और configured quiz-creation group में उपलब्ध है।")
        return ConversationHandler.END
    context.user_data["official_quiz_draft"] = {}
    await _save_draft(update, context, "type")
    await update.effective_message.reply_text(
        "🏆 Official Quiz बनाने की शुरुआत।\n\n"
        "Quiz type लिखें:\n1. GSI\n2. Star\n\n"
        "केवल `GSI` या `Star` लिखें।"
    )
    return TYPE


async def type_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.effective_message.text or "").strip().casefold()
    if value not in {"gsi", "star", "1", "2"}:
        await update.effective_message.reply_text("कृपया केवल GSI या Star लिखें।")
        return TYPE
    _draft(context)["quiz_type"] = "gsi" if value in {"gsi", "1"} else "star"
    await _save_draft(update, context, "slug")
    await update.effective_message.reply_text("अब unique Quiz ID लिखें। उदाहरण: `August2026quiz`")
    return SLUG


async def slug_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.effective_message.text or "").strip().replace(" ", "")
    if not value or len(value) > 96 or "/" in value:
        await update.effective_message.reply_text("Quiz ID छोटा, unique और बिना space के लिखें।")
        return SLUG
    _draft(context)["slug"] = value
    await _save_draft(update, context, "title")
    await update.effective_message.reply_text("Quiz का display title लिखें।")
    return TITLE


async def title_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.effective_message.text or "").strip()
    if not value or len(value) > 256:
        await update.effective_message.reply_text("Title खाली नहीं होना चाहिए और 256 characters से छोटा होना चाहिए।")
        return TITLE
    _draft(context)["title"] = value
    await _save_draft(update, context, "count")
    await update.effective_message.reply_text("कुल कितने MCQ questions भेजेंगे? (2 से 100)")
    return COUNT


async def count_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        value = int((update.effective_message.text or "").strip())
    except ValueError:
        value = 0
    if not OfficialQuizService.MIN_COUNT <= value <= OfficialQuizService.MAX_COUNT:
        await update.effective_message.reply_text("Question count 2 से 100 के बीच लिखें।")
        return COUNT
    _draft(context)["count"] = value
    await _save_draft(update, context, "timer")
    await update.effective_message.reply_text("हर question का timer कितने seconds हो? (5 से 180)")
    return TIMER


async def timer_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        value = int((update.effective_message.text or "").strip())
    except ValueError:
        value = 0
    if not OfficialQuizService.MIN_TIMER <= value <= OfficialQuizService.MAX_TIMER:
        await update.effective_message.reply_text("Timer 5 से 180 seconds के बीच लिखें।")
        return TIMER
    _draft(context)["timer"] = value
    await _save_draft(update, context, "rules")
    await update.effective_message.reply_text("Quiz के rules लिखें।")
    return RULES


async def rules_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.effective_message.text or "").strip()
    if not value or len(value) > 2000:
        await update.effective_message.reply_text("Rules खाली नहीं होने चाहिए और 2000 characters से छोटे रखें।")
        return RULES
    _draft(context)["rules"] = value
    _draft(context)["items"] = []
    await _save_draft(update, context, "questions")
    await update.effective_message.reply_text(
        f"अब ठीक {int(_draft(context)['count'])} exact MCQ questions भेजें।\n\n"
        "Direct Telegram Quiz Poll forward/send करें, या text format इस्तेमाल करें:\n"
        "Question\nA. पहला option\nB. दूसरा option\nC. तीसरा option\nD. चौथा option\nAnswer: A\n\n"
        "Bot question, options या answer में कोई बदलाव/AI generation नहीं करेगी।"
    )
    return QUESTIONS


async def _show_quiz_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = _draft(context)
    expected = int(draft["count"])
    kind = "GSI Quiz" if draft["quiz_type"] == "gsi" else "Star Quiz"
    await update.effective_message.reply_text(
        f"✅ सभी {expected} MCQs exact रूप में मिल गए।\n\n"
        f"🏆 Type: {kind}\n🆔 ID: {draft['slug']}\n🎯 Title: {draft['title']}\n"
        f"⏱ Timer: {draft['timer']} seconds\n📜 Rules: {draft['rules']}\n\n"
        "Quiz save करने के लिए `YES` लिखें या `/cancelquiz` दें।"
    )
    return CONFIRM


async def answer_key_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = _draft(context)
    answer_key = _parse_answer_key(update.effective_message.text or "")
    expected = int(draft.get("count", 0))
    pending_numbers = [index + 1 for index, item in enumerate(draft.get("items", [])) if item.get("answer_pending")]
    missing = [number for number in pending_numbers if number not in answer_key]
    if missing:
        await update.effective_message.reply_text(
            "कुछ answers अभी missing हैं। इस format में भेजें: `1-C, 2-B, 3-A`\n"
            f"Missing question numbers: {', '.join(map(str, missing))}"
        )
        return ANSWERS
    for index, item in enumerate(draft.get("items", []), start=1):
        if item.get("answer_pending"):
            item["correct_option"] = answer_key[index]
            item.pop("answer_pending", None)
    await _save_draft(update, context, "confirm")
    return await _show_quiz_confirmation(update, context)


async def question_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message:
        return QUESTIONS
    draft = _draft(context)
    items = draft.setdefault("items", [])
    item, error = _extract_mcq(message)
    if error:
        await message.reply_text(f"❌ {error}")
        return QUESTIONS
    item["source_message_id"] = message.message_id
    items.append(item)
    await _save_draft(update, context, "questions")
    expected = int(draft["count"])
    if len(items) < expected:
        await message.reply_text(f"✅ Question {len(items)}/{expected} exact रूप में save हो गया। अगला MCQ भेजें।")
        return QUESTIONS
    if len(items) > expected:
        items.pop()
        await _save_draft(update, context, "questions")
        await message.reply_text(f"इस quiz में केवल {expected} questions हैं। Extra question save नहीं किया गया।")
        return QUESTIONS
    if any(item.get("answer_pending") for item in items):
        await message.reply_text(
            "✅ सभी MCQs मिल गए। Forwarded polls का सही answer Telegram API ने नहीं दिया है।\n\n"
            "अब केवल answer key एक साथ भेजें, जैसे: `1-C, 2-B, 3-A, 4-D`\n"
            "इसके बाद bot सीधे save confirmation दिखाएगी।"
        )
        return ANSWERS
    return await _show_quiz_confirmation(update, context)


async def donequestions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = _draft(context)
    items = draft.get("items", [])
    expected = int(draft.get("count", 0))
    if len(items) != expected:
        await update.effective_message.reply_text(f"अभी {len(items)}/{expected} MCQs मिले हैं। पहले बाकी exact questions भेजें।")
        return QUESTIONS
    if any(item.get("answer_pending") for item in items):
        await update.effective_message.reply_text(
            "Forwarded polls save हो गए हैं। अब answer key एक साथ भेजें, जैसे: `1-C, 2-B, 3-A`"
        )
        return ANSWERS
    await update.effective_message.reply_text("सभी MCQs मिल गए हैं। Save करने के लिए YES लिखें।")
    return CONFIRM


async def confirm_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if (update.effective_message.text or "").strip().casefold() not in {"yes", "y", "हाँ", "हां"}:
        await update.effective_message.reply_text("Quiz save नहीं की गई। Save करने के लिए YES लिखें या /cancelquiz दें।")
        return CONFIRM
    draft = dict(_draft(context))
    try:
        quiz = await _service(context).create_quiz(
            created_by=update.effective_user.id, quiz_type=draft["quiz_type"], slug=draft["slug"],
            title=draft["title"], rules=draft["rules"], count=int(draft["count"]),
            round_seconds=int(draft["timer"]), question_items=list(draft.get("items", [])),
        )
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ Quiz save नहीं हो सकी: {exc}")
        return ConversationHandler.END
    context.user_data.pop("official_quiz_draft", None)
    await update.effective_message.reply_text(
        f"✅ {('GSI Quiz' if quiz.quiz_type == 'gsi' else 'Star Quiz')} save हो गई।\n\n"
        f"🆔 Unique ID: `{quiz.slug}`\n"
        f"Questions: {quiz.question_count}\n"
        f"Play group में lobby खोलने के लिए creation group से `/quiz {quiz.slug}` दें।",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cancelquiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("official_quiz_draft", None)
    if update.effective_user:
        database = context.application.bot_data["database"]
        async with database.session_factory() as session:
            from bot.database.repositories import Repository
            repo = Repository(session)
            await repo.delete_official_draft(update.effective_user.id)
            await repo.commit()
    if update.effective_message:
        await update.effective_message.reply_text("Official quiz creation cancel कर दी गई।")
    return ConversationHandler.END


async def launch_quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not _is_bot_admin(update) or not (_in_config_group(update) or _in_play_group(update)):
        if update.effective_message:
            await update.effective_message.reply_text(
                "/quiz केवल bot admin द्वारा configured quiz-creation या official play group में चलाएँ।"
            )
        return
    if not context.args:
        await update.effective_message.reply_text("Use: `/quiz August2026quiz`", parse_mode="Markdown")
        return
    ok, message = await _service(context).launch(context.args[0])
    await update.effective_message.reply_text(message)


async def official_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data or not query.message:
        return
    parts = query.data.split(":")
    if len(parts) != 3:
        return
    action, raw_id = parts[1], parts[2]
    try:
        quiz_id = int(raw_id)
    except ValueError:
        await query.answer("Invalid quiz link", show_alert=True)
        return
    service = _service(context)
    if action == "join":
        if not _in_play_group(update):
            await query.answer("This quiz is available in the official play group only.", show_alert=True)
            return
        quiz, count = await service.join(quiz_id, query.from_user.id, query.from_user.username, query.from_user.full_name)
        if quiz is None:
            await query.answer("This lobby is no longer open.", show_alert=True)
            return
        await query.answer(f"Joined. Participants: {count}")
        try:
            await query.edit_message_text(
                service.lobby_text(quiz, count), reply_markup=service.lobby_keyboard(quiz.id), parse_mode="Markdown"
            )
        except TelegramError:
            logger.warning("Could not refresh official quiz lobby", exc_info=True)
        return
    if action == "start":
        if not _is_bot_admin(update) or not _in_play_group(update):
            await query.answer("Only the bot admin can start this official quiz.", show_alert=True)
            return
        quiz, participants, error = await service.begin_countdown(quiz_id)
        if error:
            await query.answer(error, show_alert=True)
            return
        await query.answer("15-second countdown started")
        try:
            await query.edit_message_text(
                _countdown_text(quiz.title, participants, 15),
                parse_mode="HTML",
            )
        except TelegramError:
            pass
        asyncio.create_task(
            _countdown_task(
                service,
                quiz_id,
                query.message.chat_id,
                query.message.message_id,
                quiz.title,
                participants,
            ),
            name=f"official-countdown-{quiz_id}",
        )


def _countdown_text(title: str, participants: int, remaining: int) -> str:
    title_html = html.escape(str(title))
    if remaining > 0:
        return (
            f"⏳ <b>{title_html}</b>\n\n"
            f"🚀 <b>GSI Quiz Countdown</b>\n"
            f"<b>{remaining}</b> seconds remaining\n"
            f"👥 Participants: <b>{participants}</b>\n\n"
            "Get ready — the official quiz is about to begin!"
        )
    return (
        f"🚀 <b>{title_html}</b>\n\n"
        "<b>LET’S START!</b>\n"
        "Your first question is coming now. Good luck!"
    )


async def _countdown_task(
    service: OfficialQuizService,
    quiz_id: int,
    chat_id: int,
    message_id: int,
    title: str,
    participants: int,
) -> None:
    for remaining in range(service.COUNTDOWN_SECONDS, 0, -1):
        try:
            await service.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=_countdown_text(title, participants, remaining),
                parse_mode="HTML",
            )
        except TelegramError:
            logger.debug("Could not refresh official countdown at %ss", remaining, exc_info=True)
        await asyncio.sleep(1)
    try:
        await service.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=_countdown_text(title, participants, 0),
            parse_mode="HTML",
        )
    except TelegramError:
        logger.debug("Could not send official Let’s Start transition", exc_info=True)
    await service.start_after_countdown(quiz_id)


def conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("createquiz", createquiz_entry)],
        states={
            TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, type_step)],
            SLUG: [MessageHandler(filters.TEXT & ~filters.COMMAND, slug_step)],
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, title_step)],
            COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, count_step)],
            TIMER: [MessageHandler(filters.TEXT & ~filters.COMMAND, timer_step)],
            RULES: [MessageHandler(filters.TEXT & ~filters.COMMAND, rules_step)],
            QUESTIONS: [
                CommandHandler("donequestions", donequestions_command),
                MessageHandler(filters.ALL & ~filters.COMMAND, question_step),
            ],
            ANSWERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_key_step)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_step)],
        },
        fallbacks=[CommandHandler("cancelquiz", cancelquiz)],
        per_user=True,
        per_chat=True,
    )

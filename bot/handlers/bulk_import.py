"""Admin-only import of forwarded Telegram quiz polls into the permanent question bank."""
from __future__ import annotations

import re

from sqlalchemy.exc import IntegrityError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import UNIFIED_EXAM_LEVEL, VALID_STATES, get_settings, subjects_for_state
from bot.database.repositories import Repository
from bot.handlers.start import INDIAN_STATES, STATE_PAGE_SIZE, state_page_count

BULK_DRAFT_KEY = "bulk_import_draft"


def _is_admin(user_id: int | None) -> bool:
    settings = get_settings()
    return user_id is not None and user_id in settings.global_admin_ids


def _is_bulk_group(chat_id: int | None, chat_type: str | None) -> bool:
    settings = get_settings()
    return bool(
        chat_id is not None
        and chat_type in {"group", "supergroup"}
        and settings.bulk_source_group_id is not None
        and chat_id == settings.bulk_source_group_id
    )


def _state_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    page = max(0, min(page, state_page_count() - 1))
    states = INDIAN_STATES[page * STATE_PAGE_SIZE:(page + 1) * STATE_PAGE_SIZE]
    rows: list[list[InlineKeyboardButton]] = []
    if page == 0:
        rows.append([InlineKeyboardButton("🇮🇳 पूरे भारत", callback_data="bulk:stateval:All India")])
    for index in range(0, len(states), 2):
        rows.append([
            InlineKeyboardButton(state, callback_data=f"bulk:stateval:{state}")
            for state in states[index:index + 2]
        ])
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(InlineKeyboardButton("⬅ पिछली सूची", callback_data=f"bulk:statepage:{page - 1}"))
    if page < state_page_count() - 1:
        navigation.append(InlineKeyboardButton("अगली सूची ➡", callback_data=f"bulk:statepage:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton("❌ रद्द करें", callback_data="bulk:cancel")])
    return InlineKeyboardMarkup(rows)


def _subject_keyboard(state: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(subject, callback_data=f"bulk:subject:{subject}")]
        for subject in subjects_for_state(state)
    ]
    rows.append([InlineKeyboardButton("❌ रद्द करें", callback_data="bulk:cancel")])
    return InlineKeyboardMarkup(rows)


def _language(question: str, options: list[str]) -> str:
    return "Hindi" if re.search(r"[\u0900-\u097F]", question + " " + " ".join(options)) else "English"


def _question_type(question: str) -> str:
    return "Statement-based" if re.search(r"\bstatements?\b|कथनों|कथन\s*[१२३४1-4]", question, re.IGNORECASE) else "Conceptual"


async def bulk_send_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    settings = get_settings()
    if not message or not chat or not user or not _is_admin(user.id):
        return
    if not _is_bulk_group(chat.id, chat.type):
        await message.reply_text("/bulksend केवल configured private bulk-MCQ group में bot admin दे सकते हैं।")
        return
    context.user_data[BULK_DRAFT_KEY] = {"items": []}
    await message.reply_text(
        "📥 Bulk MCQ import शुरू हो गया है।\n\n"
        "अब केवल Telegram के MCQ quiz polls forward करें। Bot question, options और सही answer को बदलेगी नहीं।\n\n"
        "सभी questions forward करने के बाद नीचे दिए गए Done button को दबाएँ।",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Done — State चुनें", callback_data="bulk:done")]]),
    )


async def bulk_content_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    draft = context.user_data.get(BULK_DRAFT_KEY)
    if not message or not chat or not user or not draft:
        return
    if not _is_admin(user.id) or not _is_bulk_group(chat.id, chat.type):
        return
    poll = message.poll
    if poll is None or poll.type != "quiz":
        await message.reply_text("कृपया केवल MCQ quiz poll forward करें। साधारण poll या text स्वीकार नहीं है।")
        return
    options = [option.text for option in poll.options]
    correct_option = getattr(poll, "correct_option_id", None)
    if len(options) != 4 or correct_option is None or not 0 <= int(correct_option) < 4 or any(not option.strip() for option in options):
        await message.reply_text("यह poll valid 4-option MCQ नहीं है, इसलिए import नहीं किया गया।")
        return
    draft["items"].append({
        "question": poll.question,
        "options": options,
        "correct_option": int(correct_option),
        "source_message_id": message.message_id,
    })
    await message.reply_text(
        f"✅ Question {len(draft['items'])} सुरक्षित हो गया। Content में कोई बदलाव नहीं होगा।\n"
        "और polls forward करें या Done दबाएँ।",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Done — State चुनें", callback_data="bulk:done")]]),
    )


async def bulk_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data or not query.message or not _is_admin(query.from_user.id):
        return
    if not _is_bulk_group(query.message.chat.id, query.message.chat.type):
        await query.answer("यह configured bulk group नहीं है।", show_alert=True)
        return
    draft = context.user_data.get(BULK_DRAFT_KEY)
    if not draft:
        await query.answer("कोई active bulk import नहीं है।", show_alert=True)
        return
    parts = query.data.split(":", 2)
    action = parts[1] if len(parts) > 1 else ""
    value = parts[2] if len(parts) > 2 else ""
    if action == "cancel":
        context.user_data.pop(BULK_DRAFT_KEY, None)
        await query.answer("Import रद्द किया गया।")
        await query.edit_message_text("Bulk MCQ import रद्द कर दिया गया।")
        return
    if action == "done":
        if not draft["items"]:
            await query.answer("पहले कम से कम एक MCQ poll forward करें।", show_alert=True)
            return
        await query.answer()
        await query.edit_message_text(
            f"{len(draft['items'])} MCQs मिल गए। अब state चुनें:", reply_markup=_state_keyboard()
        )
        return
    if action == "statepage" and value.isdigit():
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=_state_keyboard(int(value)))
        return
    if action == "stateval" and value in VALID_STATES:
        draft["state"] = value
        await query.answer("State सेव हो गया।")
        await query.edit_message_text(f"State: {value}\n\nअब subject चुनें:", reply_markup=_subject_keyboard(value))
        return
    if action == "subject" and value in subjects_for_state(draft.get("state", "All India")):
        draft["subject"] = value
        database = context.application.bot_data["database"]
        imported = 0
        duplicates = 0
        async with database.session_factory() as session:
            repo = Repository(session)
            for item in draft["items"]:
                try:
                    async with session.begin_nested():
                        await repo.add_question(
                            question_text=item["question"], options=item["options"], correct_option=item["correct_option"],
                            explanation=f"Imported Telegram MCQ answer: option {chr(ord('A') + item['correct_option'])}",
                            key_point="Imported exact MCQ; answer taken from the original Telegram quiz poll.",
                            state=draft["state"], subject=value, topic="Imported MCQ",
                            difficulty=UNIFIED_EXAM_LEVEL, question_type=_question_type(item["question"]),
                            language=_language(item["question"], item["options"]), source="bulk_mcq",
                            source_group_id=query.message.chat.id,
                        )
                    imported += 1
                except IntegrityError:
                    duplicates += 1
            await repo.commit()
        context.user_data.pop(BULK_DRAFT_KEY, None)
        await query.answer("Import पूरा हो गया।")
        duplicate_text = f"\nDuplicates skipped: {duplicates}" if duplicates else ""
        await query.edit_message_text(
            f"✅ Bulk MCQ import पूरा हुआ।\n\nState: {draft['state']}\nSubject: {value}\n"
            f"Imported: {imported}{duplicate_text}\n\nQuestions अब इसी state और subject के quiz pool में उपलब्ध हैं।"
        )
        return
    await query.answer("Invalid bulk import action.", show_alert=True)

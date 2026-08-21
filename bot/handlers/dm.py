"""Private-chat controls and a full personal-study settings dashboard."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from bot.config import (
    VALID_STATES,
    default_subjects_for_state,
    display_subject_for_state,
    normalize_language,
    normalize_state,
    subjects_for_state,
    toggle_subject_selection,
)
from bot.database.models import GroupSettings
from bot.database.repositories import Repository
from bot.handlers.start import INDIAN_STATES, STATE_PAGE_SIZE, onboarding_language_text, private_quick_actions_keyboard, state_page_count
from bot.utils.helpers import (
    already_off_text, command_text, interval_from_arg, parse_subjects, settings_text,
    stop_confirmation_keyboard, stop_confirmation_text, stopped_text,
)


def _on_off(value: bool) -> str:
    return "चालू" if value else "बंद"


async def _private_context(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == "private" and update.effective_user)


async def _ensure_private_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> GroupSettings:
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        user = await repo.upsert_user(
            update.effective_user.id, update.effective_user.username, update.effective_user.full_name
        )
        settings = await repo.ensure_group(
            update.effective_chat.id, update.effective_user.full_name or "Private Study", "private"
        )
        if settings.language == "English" and user.preferred_language == "Hindi":
            settings.language = "Hindi"
        await repo.commit()
        return settings


async def _is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or not update.effective_user or not update.effective_message:
        return False
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    except Exception:
        await update.effective_message.reply_text("I could not verify group administrator permissions.")
        return False
    if member.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}:
        await update.effective_message.reply_text("Only group administrators can change a group language.")
        return False
    return True


def dm_settings_text(settings: GroupSettings, name: str) -> str:
    return (
        "⚙️ *मेरी पढ़ाई की सेटिंग्स*\n\n"
        f"विद्यार्थी: {name}\n"
        f"स्थिति: {'🟢 निजी क्विज़ चालू' if settings.quiz_active else '⚪ निजी क्विज़ बंद'}\n"
        f"क्षेत्र: {settings.state}\n"
        f"भाषा: {'हिंदी' if settings.language == 'Hindi' else 'English'}\n"
        f"स्तर: एकीकृत Exam-level, तथ्य-आधारित प्रश्न\n"
        f"अंतराल: हर {settings.interval_minutes} मिनट\n\n"
        "नीचे किसी विकल्प पर टैप करके अपनी पढ़ाई की सेटिंग बदलें।"
    )


def dm_settings_keyboard(settings: GroupSettings) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗺️ राज्य", callback_data="dset:state"),
            InlineKeyboardButton("📚 विषय", callback_data="dset:subjects"),
        ],
        [InlineKeyboardButton("🌐 भाषा", callback_data="dset:language")],
        [
            InlineKeyboardButton("⏱️ क्विज़ अंतराल", callback_data="dset:interval"),
            InlineKeyboardButton("▶️ क्विज़ शुरू करें" if not settings.quiz_active else "⏸️ क्विज़ रोकें", callback_data="dset:quiz"),
        ],
        [InlineKeyboardButton("📊 सेटिंग विवरण", callback_data="dset:info")],
        [InlineKeyboardButton("🔙 वापस", callback_data="dset:back")],
    ])


def dm_state_selector_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    total_pages = state_page_count()
    page = max(0, min(page, total_pages - 1))
    states = INDIAN_STATES[page * STATE_PAGE_SIZE:(page + 1) * STATE_PAGE_SIZE]
    rows: list[list[InlineKeyboardButton]] = []
    if page == 0:
        rows.append([InlineKeyboardButton("🇮🇳 पूरे भारत से तैयारी", callback_data="dset:stateval:All India")])
    for index in range(0, len(states), 2):
        rows.append([InlineKeyboardButton(state, callback_data=f"dset:stateval:{state}") for state in states[index:index + 2]])
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(InlineKeyboardButton("⬅ पिछली सूची", callback_data=f"dset:statepage:{page - 1}"))
    if page < total_pages - 1:
        navigation.append(InlineKeyboardButton("अगली सूची ➡", callback_data=f"dset:statepage:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton("← सेटिंग्स", callback_data="dset:home")])
    return InlineKeyboardMarkup(rows)


def dm_language_selector_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("हिंदी", callback_data="dset:langval:Hindi")],
        [InlineKeyboardButton("English", callback_data="dset:langval:English")],
        [InlineKeyboardButton("← सेटिंग्स", callback_data="dset:home")],
    ])


def dm_interval_selector_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("10 मिनट", callback_data="dset:intval:10"), InlineKeyboardButton("15 मिनट", callback_data="dset:intval:15")],
        [InlineKeyboardButton("20 मिनट", callback_data="dset:intval:20"), InlineKeyboardButton("30 मिनट", callback_data="dset:intval:30")],
        [InlineKeyboardButton("60 मिनट", callback_data="dset:intval:60")],
        [InlineKeyboardButton("← सेटिंग्स", callback_data="dset:home")],
    ])


def dm_subject_selector_keyboard(settings: GroupSettings) -> InlineKeyboardMarkup:
    selected = set(settings.subjects or [])
    rows = []
    for subject in subjects_for_state(settings.state):
        label = display_subject_for_state(settings.state, subject)
        rows.append([InlineKeyboardButton(("✅ " if subject in selected else "▫️ ") + label, callback_data=f"dset:subj:{subject}")])
    rows.extend([
        [InlineKeyboardButton("मूल विषय चुनें", callback_data="dset:subjectdefault")],
        [InlineKeyboardButton("← सेटिंग्स", callback_data="dset:home")],
    ])
    return InlineKeyboardMarkup(rows)


async def setlanguage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user or not update.effective_message:
        return
    if update.effective_chat.type == "private" and not context.args:
        settings = await _ensure_private_settings(update, context)
        await update.effective_message.reply_text(
            "🌐 *क्विज़ की भाषा चुनें*", reply_markup=dm_language_selector_keyboard(), parse_mode="Markdown"
        )
        return
    language = normalize_language(command_text(context.args))
    if not language:
        await update.effective_message.reply_text("Use /setlanguage English or /setlanguage Hindi.")
        return
    if update.effective_chat.type in {"group", "supergroup"} and not await _is_group_admin(update, context):
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.upsert_user(update.effective_user.id, update.effective_user.username, update.effective_user.full_name)
        await repo.set_user_language(update.effective_user.id, language)
        await repo.ensure_group(
            update.effective_chat.id,
            update.effective_chat.title or update.effective_user.full_name or "Study Chat",
            update.effective_chat.type,
        )
        await repo.update_settings(update.effective_chat.id, language=language)
        await repo.commit()
    if language == "Hindi":
        await update.effective_message.reply_text("भाषा हिंदी पर सेट कर दी गई है। अगले प्रश्न हिंदी में भेजे जाएंगे।")
    else:
        await update.effective_message.reply_text("Language set to English. Future questions will be sent in English.")


async def dmstart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _private_context(update):
        if update.effective_message:
            await update.effective_message.reply_text("यह विकल्प केवल bot के निजी चैट में उपलब्ध है।")
        return
    await _ensure_private_settings(update, context)
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        settings = await repo.get_settings(update.effective_chat.id)
        was_active = bool(settings and settings.quiz_active)
        interval = int(settings.interval_minutes if settings else 10)
        language = settings.language if settings else "Hindi"
        if not was_active:
            await repo.update_settings(update.effective_chat.id, quiz_active=True, last_quiz_at=None)
        await repo.commit()

    if was_active:
        if language == "Hindi":
            message = (
                "ℹ️ <b>Private Automatic Quiz पहले से ON है</b>\n\n"
                f"⏱ <b>Next question:</b> configured schedule के अनुसार हर {interval} मिनट पर\n\n"
                "Private Automatic Quiz रोकने के लिए <code>/stopquiz</code> दें।"
            )
        else:
            message = (
                "ℹ️ <b>Private Automatic Quiz is already ON</b>\n\n"
                f"⏱ <b>Next question:</b> according to the configured {interval}-minute schedule\n\n"
                "Use <code>/stopquiz</code> to stop Private Automatic Quiz."
            )
        await update.effective_message.reply_text(message, parse_mode="HTML")
        return

    if language == "Hindi":
        message = (
            "🚀 <b>Private Automatic Quiz शुरू हो गया है</b>\n\n"
            "✅ पहला practice question अभी भेजा जा रहा है।\n"
            f"⏱ इसके बाद questions हर {interval} मिनट के configured schedule के अनुसार आएँगे।\n\n"
            "Private Automatic Quiz रोकने के लिए <code>/stopquiz</code> दें।"
        )
    else:
        message = (
            "🚀 <b>Private Automatic Quiz started</b>\n\n"
            "✅ The first practice question is being sent now.\n"
            f"⏱ After that, questions will arrive according to the configured {interval}-minute schedule.\n\n"
            "Use <code>/stopquiz</code> to stop Private Automatic Quiz."
        )
    await update.effective_message.reply_text(message, parse_mode="HTML")
    service = context.application.bot_data["quiz_service"]
    question = await service.send_quiz(update.effective_chat.id, force=True)
    if question is None:
        fallback = (
            "⚠️ पहला practice question अभी उपलब्ध नहीं हो सका। अगली कोशिश configured schedule के अनुसार होगी।"
            if language == "Hindi"
            else "⚠️ The first practice question could not be delivered yet. The scheduler will retry at the configured interval."
        )
        await update.effective_message.reply_text(fallback)


async def dmstop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _private_context(update):
        if update.effective_message:
            await update.effective_message.reply_text("यह विकल्प केवल bot के निजी चैट में उपलब्ध है।")
        return
    settings = await _ensure_private_settings(update, context)
    if not settings.quiz_active:
        language = settings.language
        await update.effective_message.reply_text(already_off_text(language, private=True), parse_mode="HTML")
        return
    await update.effective_message.reply_text(
        stop_confirmation_text(settings.language, private=True),
        reply_markup=stop_confirmation_keyboard(settings.language, private=True),
        parse_mode="HTML",
    )


async def dminterval_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _private_context(update):
        if update.effective_message:
            await update.effective_message.reply_text("यह विकल्प केवल bot के निजी चैट में उपलब्ध है।")
        return
    interval = interval_from_arg(command_text(context.args))
    if not interval:
        await update.effective_message.reply_text(
            "⏱️ *क्विज़ का अंतराल चुनें*", reply_markup=dm_interval_selector_keyboard(), parse_mode="Markdown"
        )
        return
    await _ensure_private_settings(update, context)
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.update_settings(update.effective_chat.id, interval_minutes=interval)
        await repo.commit()
    await update.effective_message.reply_text(f"निजी क्विज़ अंतराल हर {interval} मिनट पर सेट कर दिया गया है।")


async def dmstate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _private_context(update):
        if update.effective_message:
            await update.effective_message.reply_text("यह विकल्प केवल bot के निजी चैट में उपलब्ध है।")
        return
    if not context.args:
        await _ensure_private_settings(update, context)
        await update.effective_message.reply_text(
            "🗺️ *अपना राज्य चुनें*\nराज्य सूची: 1/3", reply_markup=dm_state_selector_keyboard(0), parse_mode="Markdown"
        )
        return
    state = normalize_state(command_text(context.args))
    if not state:
        await update.effective_message.reply_text("कृपया राज्य button से अपना valid state चुनें।")
        return
    await _ensure_private_settings(update, context)
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.update_settings(update.effective_chat.id, state=state, subjects=default_subjects_for_state(state), current_rotation_index=0)
        await repo.commit()
    await update.effective_message.reply_text(f"राज्य {state} सेव कर दिया गया है।")


async def dmsubjects_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _private_context(update):
        if update.effective_message:
            await update.effective_message.reply_text("यह विकल्प केवल bot के निजी चैट में उपलब्ध है।")
        return
    settings = await _ensure_private_settings(update, context)
    if context.args:
        subjects = parse_subjects(command_text(context.args))
        if subjects and set(subjects).issubset(set(subjects_for_state(settings.state))):
            database = context.application.bot_data["database"]
            async with database.session_factory() as session:
                repo = Repository(session)
                await repo.update_settings(update.effective_chat.id, subjects=subjects, current_rotation_index=0)
                await repo.commit()
            await update.effective_message.reply_text("Subjects सेव कर दिए गए हैं।")
            return
    await update.effective_message.reply_text(
        f"📚 *{settings.state} के subjects चुनें*", reply_markup=dm_subject_selector_keyboard(settings), parse_mode="Markdown"
    )


async def dmsettings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _private_context(update):
        if update.effective_message:
            await update.effective_message.reply_text("निजी सेटिंग केवल bot के निजी चैट में खोली जा सकती है।")
        return
    settings = await _ensure_private_settings(update, context)
    await update.effective_message.reply_text(
        dm_settings_text(settings, update.effective_user.first_name),
        reply_markup=dm_settings_keyboard(settings), parse_mode="Markdown",
    )


async def open_dm_settings_from_callback(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.upsert_user(query.from_user.id, query.from_user.username, query.from_user.full_name)
        settings = await repo.ensure_group(query.message.chat.id, query.from_user.full_name or "Private Study", "private")
        await repo.commit()
    await query.answer()
    await query.edit_message_text(
        dm_settings_text(settings, query.from_user.first_name), reply_markup=dm_settings_keyboard(settings), parse_mode="Markdown"
    )


async def dm_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None or not query.data.startswith("dset:"):
        return
    chat = query.message.chat
    if chat.type != "private":
        await query.answer("यह पैनल केवल निजी चैट में काम करता है।", show_alert=True)
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.upsert_user(query.from_user.id, query.from_user.username, query.from_user.full_name)
        settings = await repo.ensure_group(chat.id, query.from_user.full_name or "Private Study", "private")
        await repo.commit()

    parts = query.data.split(":", 2)
    action = parts[1]
    value = parts[2] if len(parts) == 3 else None

    async def update_values(**values: object) -> GroupSettings:
        async with database.session_factory() as session:
            repo = Repository(session)
            updated = await repo.update_settings(chat.id, **values)
            await repo.commit()
            return updated

    async def show_home(current: GroupSettings | None = None) -> None:
        current = current or settings
        await query.edit_message_text(
            dm_settings_text(current, query.from_user.first_name), reply_markup=dm_settings_keyboard(current), parse_mode="Markdown"
        )

    if action == "home":
        await query.answer()
        await show_home()
        return
    if action == "back":
        await query.answer()
        await query.edit_message_text(
            onboarding_language_text(query.from_user.first_name),
            reply_markup=private_quick_actions_keyboard(settings.language), parse_mode="Markdown",
        )
        return
    if action == "state":
        await query.answer()
        await query.edit_message_text("🗺️ *अपना राज्य चुनें*\nराज्य सूची: 1/3", reply_markup=dm_state_selector_keyboard(0), parse_mode="Markdown")
        return
    if action == "statepage" and value and value.isdigit():
        page = max(0, min(int(value), state_page_count() - 1))
        await query.answer()
        await query.edit_message_text(
            f"🗺️ *अपना राज्य चुनें*\nराज्य सूची: {page + 1}/{state_page_count()}",
            reply_markup=dm_state_selector_keyboard(page), parse_mode="Markdown",
        )
        return
    if action == "stateval" and value in VALID_STATES:
        updated = await update_values(state=value, subjects=default_subjects_for_state(value), current_rotation_index=0)
        await query.answer("राज्य और विषय अपडेट कर दिए गए हैं।")
        await show_home(updated)
        return
    if action == "language":
        await query.answer()
        await query.edit_message_text("🌐 *क्विज़ की भाषा चुनें*", reply_markup=dm_language_selector_keyboard(), parse_mode="Markdown")
        return
    if action == "langval" and value in {"Hindi", "English"}:
        updated = await update_values(language=value)
        async with database.session_factory() as session:
            repo = Repository(session)
            await repo.set_user_language(query.from_user.id, value)
            await repo.commit()
        await query.answer("भाषा अपडेट कर दी गई है।")
        await show_home(updated)
        return
    if action == "interval":
        await query.answer()
        await query.edit_message_text("⏱️ *क्विज़ का अंतराल चुनें*", reply_markup=dm_interval_selector_keyboard(), parse_mode="Markdown")
        return
    if action == "intval" and value and value.isdigit() and int(value) in {10, 15, 20, 30, 60}:
        updated = await update_values(interval_minutes=int(value))
        await query.answer("क्विज़ अंतराल अपडेट कर दिया गया है।")
        await show_home(updated)
        return
    if action == "subjects":
        await query.answer()
        await query.edit_message_text(
            f"📚 *विषय चुनें*\n{settings.state} के लिए उपलब्ध विषय दिख रहे हैं। जिन विषयों पर ✅ है, उन्हीं से क्विज़ आएगा।",
            reply_markup=dm_subject_selector_keyboard(settings), parse_mode="Markdown",
        )
        return
    if action == "subj" and value in subjects_for_state(settings.state):
        subjects = toggle_subject_selection(settings.state, settings.subjects, value)
        updated = await update_values(subjects=subjects, current_rotation_index=0)
        await query.answer("विषय अपडेट कर दिए गए हैं।")
        await query.edit_message_reply_markup(reply_markup=dm_subject_selector_keyboard(updated))
        return
    if action == "subjectdefault":
        updated = await update_values(subjects=default_subjects_for_state(settings.state), current_rotation_index=0)
        await query.answer("मूल विषय सेव कर दिए गए हैं।")
        await query.edit_message_reply_markup(reply_markup=dm_subject_selector_keyboard(updated))
        return
    if action == "stopconfirm":
        updated = await update_values(quiz_active=False)
        await query.answer("Private Automatic Quiz बंद कर दिया गया है।")
        await query.edit_message_text(
            stopped_text(updated.language, private=True), reply_markup=dm_settings_keyboard(updated), parse_mode="HTML"
        )
        return
    if action == "stopcancel":
        await query.answer("Quiz जारी है।")
        await show_home()
        return
    if action == "quiz":
        if settings.quiz_active:
            await query.answer()
            await query.edit_message_text(
                stop_confirmation_text(settings.language, private=True),
                reply_markup=stop_confirmation_keyboard(settings.language, private=True), parse_mode="HTML",
            )
            return
        updated = await update_values(quiz_active=True, last_quiz_at=None)
        await query.answer("निजी क्विज़ की स्थिति बदल दी गई है।")
        await show_home(updated)
        return
    if action == "info":
        await query.answer()
        await context.bot.send_message(chat.id, settings_text(settings, "Private Study"), parse_mode="HTML")
        return

    await query.answer("यह विकल्प उपलब्ध नहीं है।", show_alert=True)

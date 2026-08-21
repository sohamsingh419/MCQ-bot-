"""Group join welcome and inline administrator settings for the study bot."""
from __future__ import annotations

from datetime import datetime, timezone

from telegram import ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from bot.config import VALID_STATES, default_subjects_for_state, display_subject_for_state, get_settings, subjects_for_state, toggle_subject_selection
from bot.database.models import GroupSettings
from bot.database.repositories import Repository
from bot.handlers.start import INDIAN_STATES, STATE_PAGE_SIZE, state_page_count, support_links_keyboard
from bot.utils.helpers import settings_text, stop_confirmation_keyboard, stop_confirmation_text, stopped_text



def _on_off(value: bool) -> str:
    return "चालू" if value else "बंद"


def settings_panel_text(settings: GroupSettings, title: str) -> str:
    return (
        "⚙️ *ग्रुप क्विज़ सेटिंग्स*\n\n"
        f"ग्रुप: {title}\n"
        f"स्थिति: {'🟢 क्विज़ चालू' if settings.quiz_active else '⚪ क्विज़ बंद'}\n"
        f"क्षेत्र: {settings.state}\n"
        f"भाषा: {'हिंदी' if settings.language == 'Hindi' else 'English'}\n"
        f"स्तर: एकीकृत Exam-level, तथ्य-आधारित प्रश्न\n"
        f"अंतराल: हर {settings.interval_minutes} मिनट\n\n"
        "नीचे किसी भी सेटिंग पर टैप करके उसे बदलें।"
    )


def settings_panel_keyboard(settings: GroupSettings) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗺️ क्षेत्र / राज्य", callback_data="gset:state"),
            InlineKeyboardButton("📚 विषय", callback_data="gset:subjects"),
        ],
        [InlineKeyboardButton("🌐 भाषा", callback_data="gset:language")],
        [
            InlineKeyboardButton("⏱️ क्विज़ अंतराल", callback_data="gset:interval"),
            InlineKeyboardButton("▶️ क्विज़ शुरू करें" if not settings.quiz_active else "⏸️ क्विज़ रोकें", callback_data="gset:quiz"),
        ],
        [InlineKeyboardButton("📊 सेटिंग विवरण", callback_data="gset:info")],
        [InlineKeyboardButton("🔙 वापस", callback_data="gset:back")],
    ])


def welcome_keyboard(settings: GroupSettings) -> InlineKeyboardMarkup:
    """Welcome controls compacted into two columns without dropping any action."""
    buttons = [
        button
        for row in settings_panel_keyboard(settings).inline_keyboard
        for button in row
    ]
    buttons.extend(
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="gset:home"),
            InlineKeyboardButton("❓ Help", callback_data="hact:help"),
        ]
    )
    buttons.extend(
        [button for row in support_links_keyboard(settings.language).inline_keyboard for button in row]
    )
    rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def state_selector_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    total_pages = state_page_count()
    page = max(0, min(page, total_pages - 1))
    start = page * STATE_PAGE_SIZE
    states = INDIAN_STATES[start:start + STATE_PAGE_SIZE]
    rows: list[list[InlineKeyboardButton]] = []
    if page == 0:
        rows.append([InlineKeyboardButton("🇮🇳 पूरे भारत से तैयारी", callback_data="gset:stateval:All India")])
    for index in range(0, len(states), 2):
        rows.append([InlineKeyboardButton(state, callback_data=f"gset:stateval:{state}") for state in states[index:index + 2]])
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(InlineKeyboardButton("⬅ पिछली सूची", callback_data=f"gset:statepage:{page - 1}"))
    if page < total_pages - 1:
        navigation.append(InlineKeyboardButton("अगली सूची ➡", callback_data=f"gset:statepage:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton("← सेटिंग्स", callback_data="gset:home")])
    return InlineKeyboardMarkup(rows)


def language_selector_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("हिंदी", callback_data="gset:langval:Hindi")],
        [InlineKeyboardButton("English", callback_data="gset:langval:English")],
        [InlineKeyboardButton("← सेटिंग्स", callback_data="gset:home")],
    ])


def interval_selector_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("10 मिनट", callback_data="gset:intval:10"), InlineKeyboardButton("15 मिनट", callback_data="gset:intval:15")],
        [InlineKeyboardButton("20 मिनट", callback_data="gset:intval:20"), InlineKeyboardButton("30 मिनट", callback_data="gset:intval:30")],
        [InlineKeyboardButton("60 मिनट", callback_data="gset:intval:60")],
        [InlineKeyboardButton("← सेटिंग्स", callback_data="gset:home")],
    ])


def subject_selector_keyboard(settings: GroupSettings) -> InlineKeyboardMarkup:
    selected = set(settings.subjects or [])
    rows = []
    for subject in subjects_for_state(settings.state):
        prefix = "✅ " if subject in selected else "▫️ "
        label = display_subject_for_state(settings.state, subject)
        rows.append([InlineKeyboardButton(prefix + label, callback_data=f"gset:subj:{subject}")])
    rows.extend([
        [InlineKeyboardButton("मूल विषय चुनें", callback_data="gset:subjectdefault")],
        [InlineKeyboardButton("← सेटिंग्स", callback_data="gset:home")],
    ])
    return InlineKeyboardMarkup(rows)


def welcome_text(title: str) -> str:
    return (
        "*सभी को नमस्ते*\n\n"
        "❄️ *मुझे इस ग्रुप में जोड़ने के लिए धन्यवाद।*\n"
        "अब इस ग्रुप में आपकी तैयारी के अनुसार Advanced & Exam-Level MCQs मिलते रहेंगे। 🧠\n"
        "*मैं क्या कर सकता हूँ?* राज्य, विषय, XP, streak और leaderboard के अनुसार अभ्यास।\n\n"
        "🛑 Setup शुरू करने से पहले Bot को Group में Admin बनाना आवश्यक है।👇\n"
        "📍 राज्य चुनें\n"
        "📚 विषय चुनें\n"
        "⏱️ Quiz का अंतराल सेट करें\n\n"
        "Setup पूरा होते ही bot अपने आप questions भेजेगी।\n\n"
        "🏆 हर महीने GSI Quiz भी होगा, जिसमें Top Performer को मिलेगा:\n"
        "👑 GSI — Grand Scholar of India\n\n"
        "अधिक जानकारी के लिए: /help\n"
        "Settings के लिए: /settings"
    )


async def is_group_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    config = get_settings()
    if user_id in config.global_admin_ids:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}


async def _settings_for_chat(chat_id: int, title: str, chat_type: str, context: ContextTypes.DEFAULT_TYPE) -> GroupSettings:
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        settings = await repo.ensure_group(chat_id, title or "Study Group", chat_type)
        await repo.commit()
        return settings


async def group_welcome_on_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist the bot's current rights and send welcome only on a fresh join."""
    change: ChatMemberUpdated | None = update.my_chat_member
    if change is None or change.chat.type not in {"group", "supergroup"}:
        return
    old_status = change.old_chat_member.status
    new_status = change.new_chat_member.status
    active_statuses = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}
    inactive_statuses = {ChatMemberStatus.LEFT, ChatMemberStatus.BANNED}
    if new_status not in active_statuses and new_status not in inactive_statuses:
        return

    now = datetime.now(timezone.utc)
    bot_is_admin = new_status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        settings = await repo.ensure_group(change.chat.id, change.chat.title or "Study Group", change.chat.type)
        if new_status in active_statuses:
            fresh_join = old_status in inactive_statuses
            rights_changed = old_status != new_status
            if fresh_join or rights_changed:
                await repo.update_settings(
                    change.chat.id,
                    bot_is_admin=bot_is_admin,
                    bot_joined_at=now if (fresh_join or not bot_is_admin) else settings.bot_joined_at,
                    admin_reminder_stage=8 if bot_is_admin else 0,
                    admin_reminder_sent_at=None,
                )
        else:
            await repo.update_settings(
                change.chat.id,
                bot_is_admin=False,
                admin_reminder_stage=8,
                admin_reminder_sent_at=None,
            )
        await repo.commit()

    if old_status in inactive_statuses and new_status in active_statuses:
        await context.bot.send_message(
            chat_id=change.chat.id,
            text=welcome_text(change.chat.title or "इस ग्रुप"),
            reply_markup=welcome_keyboard(settings),
            parse_mode="Markdown",
        )


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user or not update.effective_message:
        return
    if update.effective_chat.type == "private":
        from bot.handlers.dm import dmsettings_command
        await dmsettings_command(update, context)
        return
    if update.effective_chat.type not in {"group", "supergroup"}:
        await update.effective_message.reply_text("सेटिंग केवल ग्रुप या bot के निजी चैट में खोली जा सकती है।")
        return
    if not await is_group_admin(update.effective_chat.id, update.effective_user.id, context):
        await update.effective_message.reply_text("यह सेटिंग केवल ग्रुप owner और admins बदल सकते हैं।")
        return
    settings = await _settings_for_chat(
        update.effective_chat.id, update.effective_chat.title or "Study Group", update.effective_chat.type, context
    )
    await update.effective_message.reply_text(
        settings_panel_text(settings, update.effective_chat.title or "Study Group"),
        reply_markup=settings_panel_keyboard(settings), parse_mode="Markdown",
    )


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None or not query.data.startswith("gset:"):
        return
    chat = query.message.chat
    if chat.type not in {"group", "supergroup"}:
        await query.answer("यह पैनल केवल ग्रुप में काम करता है।", show_alert=True)
        return
    if not await is_group_admin(chat.id, query.from_user.id, context):
        await query.answer("सेटिंग बदलने की अनुमति केवल ग्रुप owner और admins को है।", show_alert=True)
        return

    parts = query.data.split(":", 2)
    action = parts[1]
    value = parts[2] if len(parts) == 3 else None
    settings = await _settings_for_chat(chat.id, chat.title or "Study Group", chat.type, context)
    database = context.application.bot_data["database"]

    async def update_values(**values: object) -> GroupSettings:
        async with database.session_factory() as session:
            repo = Repository(session)
            updated = await repo.update_settings(chat.id, **values)
            await repo.commit()
            return updated

    async def show_home(current: GroupSettings | None = None) -> None:
        current = current or settings
        await query.edit_message_text(
            settings_panel_text(current, chat.title or "Study Group"),
            reply_markup=settings_panel_keyboard(current), parse_mode="Markdown",
        )

    if action == "home":
        await query.answer()
        await show_home()
        return
    if action == "back":
        await query.answer()
        await query.edit_message_text(
            welcome_text(chat.title or "इस ग्रुप"),
            reply_markup=welcome_keyboard(settings),
            parse_mode="Markdown",
        )
        return
    if action == "state":
        await query.answer()
        await query.edit_message_text("🗺️ *ग्रुप का राज्य चुनें*\nराज्य सूची: 1/3", reply_markup=state_selector_keyboard(0), parse_mode="Markdown")
        return
    if action == "statepage" and value and value.isdigit():
        page = max(0, min(int(value), state_page_count() - 1))
        await query.answer()
        await query.edit_message_text(
            f"🗺️ *ग्रुप का राज्य चुनें*\nराज्य सूची: {page + 1}/{state_page_count()}",
            reply_markup=state_selector_keyboard(page), parse_mode="Markdown",
        )
        return
    if action == "stateval" and value in VALID_STATES:
        updated = await update_values(state=value, subjects=default_subjects_for_state(value), current_rotation_index=0)
        await query.answer("क्षेत्र सेव कर दिया गया है।")
        await show_home(updated)
        return
    if action == "language":
        await query.answer()
        await query.edit_message_text("🌐 *क्विज़ की भाषा चुनें*", reply_markup=language_selector_keyboard(), parse_mode="Markdown")
        return
    if action == "langval" and value in {"Hindi", "English"}:
        updated = await update_values(language=value)
        await query.answer("भाषा सेव कर दी गई है।")
        await show_home(updated)
        return
    if action == "interval":
        await query.answer()
        await query.edit_message_text("⏱️ *क्विज़ का अंतराल चुनें*", reply_markup=interval_selector_keyboard(), parse_mode="Markdown")
        return
    if action == "intval" and value and value.isdigit() and int(value) in {10, 15, 20, 30, 60}:
        updated = await update_values(interval_minutes=int(value))
        await query.answer("क्विज़ अंतराल सेव कर दिया गया है।")
        await show_home(updated)
        return
    if action == "subjects":
        await query.answer()
        await query.edit_message_text(
            f"📚 *विषय चुनें*\n{settings.state} के लिए उपलब्ध विषय दिख रहे हैं। जिन विषयों पर ✅ है, उन्हीं से क्विज़ आएगा।",
            reply_markup=subject_selector_keyboard(settings), parse_mode="Markdown",
        )
        return
    if action == "subj" and value in subjects_for_state(settings.state):
        subjects = toggle_subject_selection(settings.state, settings.subjects, value)
        updated = await update_values(subjects=subjects, current_rotation_index=0)
        await query.answer("विषय अपडेट कर दिए गए हैं।")
        await query.edit_message_reply_markup(reply_markup=subject_selector_keyboard(updated))
        return
    if action == "subjectdefault":
        updated = await update_values(subjects=default_subjects_for_state(settings.state), current_rotation_index=0)
        await query.answer("मूल विषय सेव कर दिए गए हैं।")
        await query.edit_message_reply_markup(reply_markup=subject_selector_keyboard(updated))
        return
    if action == "stopconfirm":
        updated = await update_values(quiz_active=False)
        await query.answer("Automatic Quiz बंद कर दिया गया है।")
        await query.edit_message_text(
            stopped_text(updated.language), reply_markup=settings_panel_keyboard(updated), parse_mode="HTML"
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
                stop_confirmation_text(settings.language),
                reply_markup=stop_confirmation_keyboard(settings.language), parse_mode="HTML",
            )
            return
        updated = await update_values(quiz_active=True, last_quiz_at=None)
        await query.answer("क्विज़ की स्थिति बदल दी गई है।")
        await show_home(updated)
        return
    if action == "info":
        await query.answer()
        await context.bot.send_message(
            chat.id, settings_text(settings, chat.title or "Study Group"), parse_mode="HTML"
        )
        return

    await query.answer("यह विकल्प उपलब्ध नहीं है।", show_alert=True)


async def open_group_settings_from_callback(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Open the group settings panel from a help action while enforcing administrator rights."""
    chat = query.message.chat
    if chat.type not in {"group", "supergroup"}:
        await query.answer("यह सेटिंग केवल ग्रुप में खोली जा सकती है।", show_alert=True)
        return
    if not await is_group_admin(chat.id, query.from_user.id, context):
        await query.answer("सेटिंग बदलने की अनुमति केवल ग्रुप owner और admins को है।", show_alert=True)
        return
    settings = await _settings_for_chat(chat.id, chat.title or "Study Group", chat.type, context)
    await query.answer()
    await query.edit_message_text(
        settings_panel_text(settings, chat.title or "Study Group"),
        reply_markup=settings_panel_keyboard(settings), parse_mode="Markdown",
    )

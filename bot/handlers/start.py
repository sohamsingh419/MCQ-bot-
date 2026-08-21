"""Hindi-first onboarding, welcome, and command guidance for the study bot."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.config import display_subject_for_state, get_settings, subjects_for_state
from bot.database.repositories import Repository


INDIAN_STATES = (
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
    "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal",
)
STATE_PAGE_SIZE = 10


def _label(hindi: str, english: str, language: str) -> str:
    return english if language == "English" else hindi


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("हिंदी", callback_data="onb:language:Hindi")],
        [InlineKeyboardButton("English", callback_data="onb:language:English")],
    ])


def state_page_count() -> int:
    return (len(INDIAN_STATES) + STATE_PAGE_SIZE - 1) // STATE_PAGE_SIZE


def state_menu_keyboard(language: str, page: int = 0) -> InlineKeyboardMarkup:
    total_pages = state_page_count()
    page = max(0, min(page, total_pages - 1))
    start = page * STATE_PAGE_SIZE
    states = INDIAN_STATES[start:start + STATE_PAGE_SIZE]
    rows: list[list[InlineKeyboardButton]] = []
    if page == 0:
        rows.append([InlineKeyboardButton("🇮🇳 All India", callback_data="onb:state:All India")])
    for index in range(0, len(states), 2):
        rows.append([InlineKeyboardButton(state, callback_data=f"onb:state:{state}") for state in states[index:index + 2]])
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(InlineKeyboardButton(_label("⬅ पिछली सूची", "⬅ Back", language), callback_data=f"onb:statepage:{page - 1}"))
    if page < total_pages - 1:
        navigation.append(InlineKeyboardButton(_label("अगली सूची ➡", "Next ➡", language), callback_data=f"onb:statepage:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(_label("← वापस", "← Back", language), callback_data="onb:welcome")])
    return InlineKeyboardMarkup(rows)


def subject_keyboard(
    state: str,
    language: str,
    back_callback: str = "onb:state_menu",
    selected_subjects: list[str] | None = None,
) -> InlineKeyboardMarkup:
    subjects = subjects_for_state(state)
    selected = set(selected_subjects or [])
    rows: list[list[InlineKeyboardButton]] = []
    if "All India GK" in subjects:
        rows.append([
            InlineKeyboardButton(
                ("✅ " if "All India GK" in selected else "") + _label("🇮🇳 All India GK", "🇮🇳 All India GK", language),
                callback_data="onb:subject:All India GK",
            )
        ])
        subjects = [subject for subject in subjects if subject != "All India GK"]
    for index in range(0, len(subjects), 2):
        rows.append([
            InlineKeyboardButton(
                ("✅ " if subject in selected else "") + display_subject_for_state(state, subject),
                callback_data=f"onb:subject:{subject}",
            )
            for subject in subjects[index:index + 2]
        ])
    rows.append([
        InlineKeyboardButton(_label("← वापस", "← Back", language), callback_data=back_callback),
        InlineKeyboardButton(_label("✅ Done", "✅ Done", language), callback_data="onb:subjects_done"),
    ])
    return InlineKeyboardMarkup(rows)


def support_links_keyboard(language: str) -> InlineKeyboardMarkup:
    settings = get_settings()
    if language == "English":
        labels = ("💬 Support Group", "📢 Support Channel", "👤 Owner Contact")
    else:
        labels = ("💬 Support Group", "📢 Support Channel", "👤 Owner Contact")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(labels[0], url=settings.support_group_url)],
        [
            InlineKeyboardButton(labels[1], url=settings.support_channel_url),
            InlineKeyboardButton(labels[2], url=settings.owner_contact_url),
        ],
    ])


def private_quick_actions_keyboard(language: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(_label("🗺️ राज्य", "🗺️ State", language), callback_data="onb:state_menu"),
            InlineKeyboardButton(_label("📚 विषय", "📚 Subjects", language), callback_data="onb:subjects_menu"),
        ],
        [
            InlineKeyboardButton(_label("🌐 भाषा", "🌐 Language", language), callback_data="onb:language_menu"),
            InlineKeyboardButton(_label("⚙️ Settings", "⚙️ Settings", language), callback_data="menu:settings"),
        ],
        [
            InlineKeyboardButton(_label("❓ Help", "❓ Help", language), callback_data="menu:help"),
            InlineKeyboardButton(_label("👤 Profile", "👤 Profile", language), callback_data="hact:profile"),
        ],
    ]
    rows.extend(support_links_keyboard(language).inline_keyboard)
    return InlineKeyboardMarkup(rows)


def confirmation_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_label("✨ मेरी पढ़ाई शुरू करें", "✨ Start my practice", language), callback_data="onb:finish")],
        [InlineKeyboardButton(_label("← वापस", "← Back", language), callback_data="onb:subjects_menu")],
    ])


def onboarding_language_text(name: str) -> str:
    return (
        "👋 *नमस्ते! GSI Quiz में आपका स्वागत है।*\n\n"
        "📚 यहाँ आपको मिलेंगे Advanced & Exam-Level MCQs, जो आपकी competitive-exam preparation को और मजबूत बनाने के लिए तैयार किए जाते हैं।\n"
        "अपनी तैयारी को रोज़ थोड़ा बेहतर बनाने के लिए आपके स्तर के MCQ, राज्य-आधारित अभ्यास और progress tools मिलेंगे।\n\n"
        "🧠 *आप क्या कर सकते हैं?*\n"
        "• राज्य और विषय के अनुसार MCQ Practice\n"
        "• सही उत्तर के साथ Explanation\n"
        "• XP & Streaks 🔥\n"
        "• Leaderboard 🏆\n"
        "• Monthly GSI Quiz\n\n"
        "👑 *Monthly GSI Quiz के Topper को मिलेगा खास सम्मान:*\n"
        "GSI — Grand Scholar of India\n\n"
        "⚙️ जब चाहें नीचे दिए गए options से अपनी State, Subjects, Language और Settings बदल सकते हैं।\n"
    )


def onboarding_subject_text(language: str, state: str) -> str:
    if language == "English":
        return f"📚 *Choose your subject*\nSelect a subject for {state}."
    return f"📚 *अपना विषय चुनें*\n{state} के लिए अपना विषय चुनें।"


def onboarding_state_text(language: str, page: int = 0) -> str:
    page_label = f"{page + 1}/{state_page_count()}"
    if language == "English":
        return f"🎯 *Choose your state*\nSelect All India or your state for relevant practice.\n\nState list: {page_label}"
    return f"🎯 *अपना राज्य चुनें*\nजिस राज्य या पूरे भारत के लिए आप तैयारी कर रहे हैं, उसी के अनुसार आपको बेहतर अभ्यास मिलेगा।\n\nराज्य सूची: {page_label}"



def confirmation_text(
    name: str, language: str, state: str, exam: str | None = None, subjects: list[str] | None = None
) -> str:
    """Render the compact profile confirmation shown after subject selection."""
    labels: list[str] = []
    for subject in subjects or []:
        label = display_subject_for_state(state, subject)
        if label == "Indian History":
            label = "History"
        elif label == "Indian Geography":
            label = "Geography"
        labels.append(label)
    subject_text = " • ".join(labels) or ("Not selected" if language == "English" else "चयन नहीं किया गया")
    if language == "English":
        return (
            "✅ *Your Study Profile is Ready!*\n"
            f"👤 *Profile:* {name}\n"
            "🌐 *Language:* English\n"
            f"📍 *State:* {state}\n"
            f"📚 *Subjects:* {subject_text}\n\n"
            "GSI Quiz Bot will now send Exam-Level MCQs based on your selected preferences.\n\n"
            "⚙️ You can change your State, Subjects, Language and Settings anytime using the options below."
        )
    return (
        "✅ *आपकी Study Profile तैयार है!*\n"
        f"👤 *प्रोफ़ाइल:* {name}\n"
        "🌐 *भाषा:* हिंदी\n"
        f"📍 *राज्य:* {state}\n"
        f"📚 *विषय:* {subject_text}\n\n"
        "अब आपकी चुनी हुई preferences के अनुसार GSI Quiz Bot आपको Exam-Level MCQs भेजेगी।\n\n"
        "⚙️ जब चाहें नीचे दिए गए options से अपनी State, Subjects, Language और Settings बदल सकते हैं।"
    )


def completed_profile_text(
    name: str, language: str, state: str, exam: str | None = None, subjects: list[str] | None = None
) -> str:
    return confirmation_text(name, language, state, exam, subjects)


def private_help_text(language: str) -> str:
    """Return exactly the same Help command guide used in groups.

    The inline keyboard remains private-safe, so its buttons run private-chat
    actions rather than group-administration operations.
    """
    return group_help_text(language)


def group_help_text(language: str) -> str:
    if language == "English":
        return (
            "📘 *GSI Quiz — Help & Commands*\n\n"
            "GSI Quiz is built for competitive-exam preparation. Use the options below to manage quizzes, your profile, rankings, and chat settings easily.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👤 *FOR EVERY LEARNER*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "/help\n↳ Open this Help menu again\n\n"
            "/profile\n↳ View your Profile, XP and Accuracy\n\n"
            "/score\n↳ View your Profile, XP and Accuracy\n\n"
            "/rules\n↳ View XP, Level, Streak, GSI and Star rules\n\n"
            "/rank\n↳ View your current Group rank\n\n"
            "/leaderboard\n↳ View Group rankings\n\n"
            "/daily\n↳ View daily ranking\n\n"
            "/weekly\n↳ View weekly ranking\n\n"
            "/monthly\n↳ View monthly ranking\n\n"
            "/stats\n↳ View Group study statistics\n\n"
            "/subjects\n↳ View subjects available in this Group\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👑 *GROUP OWNER & ADMIN CONTROLS*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "/settings\n↳ Open all Group Settings in one place\n\n"
            "/startquiz\n↳ Start the Group Quiz\n\n"
            "/stopquiz\n↳ Stop the Group Quiz\n\n"
            "/groupstats\n↳ View Group Quiz Performance\n\n"
            "/mocktest\n↳ View Mock Test information and options\n\n"
            "/setstate\n↳ Choose the Group State\n\n"
            "/setsubjects\n↳ Choose Quiz Subjects\n\n"
            "/setinterval\n↳ Set the Quiz time interval\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🤖 *BOT ADMIN CONTROLS*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Only the configured Bot Admin can use these commands.\n\n"
            "/createquiz\n↳ Create a GSI Quiz / Star Quiz in the configured creation Group\n\n"
            "/quiz <Quiz ID>\n↳ Open the saved Quiz Lobby\n\n"
            "/addquestion\n↳ Add a validated Question\n\n"
            "/removequestion\n↳ Remove a Question\n\n"
            "/sources\n↳ View indexed Source Documents\n\n"
            "/bulksend\n↳ Import validated MCQ polls from the private source Group\n\n"
            "/broadcast\n↳ Broadcast a message, photo, video or MCQ poll\n\n"
            "/deliver or /targeted\n↳ Deliver content to selected users, Groups or States\n\n"
            "/botreport\n↳ View the live Bot diagnostic report\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⚙️ *COMMON COMMANDS*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "/start\n↳ Open your Study Profile or Group Welcome\n\n"
            "/settings\n↳ Open Settings for this chat\n\n"
            "/setlanguage\n↳ Choose Hindi / English\n\n"
            "/setstate\n↳ Choose State\n\n"
            "/setsubjects\n↳ Choose Subjects\n\n"
            "/setinterval\n↳ Choose a Quiz Interval of 10 / 15 / 20 / 30 / 60 minutes\n\n"
            "/startquiz\n↳ Start the Quiz\n\n"
            "/stopquiz\n↳ Stop the Quiz\n\n"
            "/profile\n↳ View your XP, Accuracy and Profile\n"
        )
    return (
        "📘 *GSI Quiz — Help & Commands*\n\n"
        "GSI Quiz आपकी competitive-exam preparation के लिए बनाया गया है। नीचे दिए गए options से आप quiz, profile, ranking और chat settings आसानी से manage कर सकते हैं।\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👤 *हर विद्यार्थी के लिए*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "/help\n↳ Help menu फिर से खोलें\n\n"
        "/profile\n↳ अपना Profile, XP और Accuracy देखें\n\n"
        "/score\n↳ अपना Profile, XP और Accuracy देखें\n\n"
        "/rules\n↳ XP, Level, Streak, GSI और Star के rules देखें\n\n"
        "/rank\n↳ Group में अपनी current rank देखें\n\n"
        "/leaderboard\n↳ Group की ranking देखें\n\n"
        "/daily\n↳ Daily ranking देखें\n\n"
        "/weekly\n↳ Weekly ranking देखें\n\n"
        "/monthly\n↳ Monthly ranking देखें\n\n"
        "/stats\n↳ Group की study statistics देखें\n\n"
        "/subjects\n↳ Group में available subjects देखें\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👑 *GROUP OWNER & ADMIN CONTROLS*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "/settings\n↳ सभी Group Settings एक जगह खोलें\n\n"
        "/startquiz\n↳ Group में Quiz शुरू करें\n\n"
        "/stopquiz\n↳ Group Quiz रोकें\n\n"
        "/groupstats\n↳ Group की Quiz Performance देखें\n\n"
        "/mocktest\n↳ Mock Test की जानकारी और options देखें\n\n"
        "/setstate\n↳ Group का State चुनें\n\n"
        "/setsubjects\n↳ Quiz Subjects चुनें\n\n"
        "/setinterval\n↳ Quiz का समय अंतराल सेट करें\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🤖 *BOT ADMIN CONTROLS*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "इन commands का उपयोग केवल configured Bot Admin कर सकते हैं।\n\n"
        "/createquiz\n↳ Configured creation Group में GSI Quiz / Star Quiz बनाएं\n\n"
        "/quiz <Quiz ID>\n↳ Saved Quiz की Lobby खोलें\n\n"
        "/addquestion\n↳ Validated Question जोड़ें\n\n"
        "/removequestion\n↳ Question हटाएं\n\n"
        "/sources\n↳ Indexed Source Documents देखें\n\n"
        "/bulksend\n↳ Private source Group से validated MCQ polls import करें\n\n"
        "/broadcast\n↳ Message, photo, video या MCQ poll broadcast करें\n\n"
        "/deliver या /targeted\n↳ चुने हुए users, Groups या States को content भेजें\n\n"
        "/botreport\n↳ Live Bot diagnostic report देखें\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚙️ *COMMON COMMANDS*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "/start\n↳ Study Profile या Group Welcome खोलें\n\n"
        "/settings\n↳ इस chat की Settings खोलें\n\n"
        "/setlanguage\n↳ Hindi / English चुनें\n\n"
        "/setstate\n↳ State चुनें\n\n"
        "/setsubjects\n↳ Subjects चुनें\n\n"
        "/setinterval\n↳ 10 / 15 / 20 / 30 / 60 मिनट में Quiz Interval चुनें\n\n"
        "/startquiz\n↳ Quiz शुरू करें\n\n"
        "/stopquiz\n↳ Quiz रोकें\n\n"
        "/profile\n↳ अपना XP, Accuracy और Profile देखें\n"
    )


def help_action_keyboard(language: str, chat_type: str) -> InlineKeyboardMarkup:
    if chat_type == "private":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ सेटिंग्स" if language == "Hindi" else "⚙️ Settings", callback_data="hact:dmsettings")],
            [
                InlineKeyboardButton("▶️ क्विज़ शुरू" if language == "Hindi" else "▶️ Start quiz", callback_data="hact:dmstart"),
                InlineKeyboardButton("⏸️ क्विज़ रोकें" if language == "Hindi" else "⏸️ Stop quiz", callback_data="hact:dmstop"),
            ],
            [
                InlineKeyboardButton("👤 मेरी प्रोफ़ाइल" if language == "Hindi" else "👤 My profile", callback_data="hact:profile"),
            ],
            [
                InlineKeyboardButton("📚 विषय" if language == "Hindi" else "📚 Subjects", callback_data="hact:subjects"),
                InlineKeyboardButton("📖 नियम" if language == "Hindi" else "📖 Rules", callback_data="hact:rules"),
            ],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ ग्रुप सेटिंग्स" if language == "Hindi" else "⚙️ Group settings", callback_data="hact:gsettings")],
        [
            InlineKeyboardButton("▶️ क्विज़ शुरू" if language == "Hindi" else "▶️ Start quiz", callback_data="hact:startquiz"),
            InlineKeyboardButton("⏸️ क्विज़ रोकें" if language == "Hindi" else "⏸️ Stop quiz", callback_data="hact:stopquiz"),
        ],
        [
            InlineKeyboardButton("📊 ग्रुप आँकड़े" if language == "Hindi" else "📊 Group statistics", callback_data="hact:groupstats"),
        ],
        [
            InlineKeyboardButton("👤 मेरी प्रोफ़ाइल" if language == "Hindi" else "👤 My profile", callback_data="hact:profile"),
            InlineKeyboardButton("🏆 रैंकिंग" if language == "Hindi" else "🏆 Leaderboard", callback_data="hact:leaderboard"),
        ],
        [InlineKeyboardButton("📚 विषय" if language == "Hindi" else "📚 Subjects", callback_data="hact:subjects")],
    ])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat or not update.effective_message:
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        user = await repo.upsert_user(update.effective_user.id, update.effective_user.username, update.effective_user.full_name)
        settings = await repo.ensure_group(
            update.effective_chat.id,
            update.effective_chat.title or update.effective_user.full_name or "Study Chat",
            update.effective_chat.type,
        )
        await repo.commit()

    if update.effective_chat.type == "private":
        if user.onboarding_completed:
            await update.effective_message.reply_text(
                completed_profile_text(user.display_name, settings.language, settings.state, user.exam_preparation, settings.subjects),
                reply_markup=private_quick_actions_keyboard(settings.language), parse_mode="Markdown",
            )
        else:
            await update.effective_message.reply_text(
                onboarding_language_text(update.effective_user.first_name), reply_markup=private_quick_actions_keyboard(settings.language), parse_mode="Markdown"
            )
        return

    language = settings.language
    await update.effective_message.reply_text(
        "सभी को नमस्ते\n\n"
        "❄️ मुझे इस ग्रुप में जोड़ने के लिए धन्यवाद।\n"
        "अब इस ग्रुप में आपकी तैयारी के अनुसार Advanced & Exam-Level MCQs मिलते रहेंगे। 🧠\n\n"
        "🛑 Setup शुरू करने से पहले Bot को Group में Admin बनाना आवश्यक है।👇\n"
        "📍 राज्य चुनें\n📚 विषय चुनें\n⏱️ Quiz का अंतराल सेट करें\n\n"
        "Setup पूरा होते ही bot अपने आप questions भेजेगी।\n\n"
        "🏆 हर महीने GSI Quiz भी होगा, जिसमें Top Performer को मिलेगा:\n"
        "👑 GSI — Grand Scholar of India\n\n"
        "अधिक जानकारी के लिए: /help\nSettings के लिए: /settings",
        reply_markup=__import__("bot.handlers.group_setup", fromlist=["welcome_keyboard"]).welcome_keyboard(settings),
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_chat:
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        settings = await Repository(session).get_settings(update.effective_chat.id)
    language = settings.language if settings else "Hindi"
    chat_type = update.effective_chat.type
    text = private_help_text(language) if chat_type == "private" else group_help_text(language)
    try:
        await update.effective_message.reply_text(text, parse_mode="Markdown")
    except TelegramError:
        # A malformed legacy Markdown entity must never make /help silently fail.
        await update.effective_message.reply_text(text)

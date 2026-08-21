"""Small pure helpers used by Telegram handlers."""
from __future__ import annotations

from datetime import datetime, timezone
import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import GSI_HONOR_TAG, XP_LEVELS, VALID_INTERVALS, display_subject_for_state, normalize_state, normalize_subject
from bot.database.models import GroupSettings, User


def command_text(args: list[str]) -> str:
    return " ".join(args).strip()


def parse_bool(value: str) -> bool | None:
    truthy = {"on", "true", "yes", "enable", "enabled", "1"}
    falsy = {"off", "false", "no", "disable", "disabled", "0"}
    normalized = value.strip().casefold()
    if normalized in truthy:
        return True
    if normalized in falsy:
        return False
    return None


def parse_subjects(value: str) -> list[str] | None:
    items = [part.strip() for part in value.split(",") if part.strip()]
    if not items:
        return None
    normalized = [normalize_subject(item) for item in items]
    if any(item is None for item in normalized):
        return None
    return list(dict.fromkeys(item for item in normalized if item))


def _tagged_identity(
    display_name: str,
    username: str | None = None,
    honor_tag: str | None = None,
    star_title: str | None = None,
) -> str:
    identity = f"@{username}" if username else display_name
    safe_identity = html.escape(str(identity))
    tags = [html.escape(str(tag)) for tag in (honor_tag, star_title) if tag]
    prefix = " ".join(tags)
    return f"{prefix} {safe_identity}".strip() if prefix else safe_identity


def xp_level_info(xp: int, language: str = "English") -> tuple[str, int, int | None, int]:
    current_name = XP_LEVELS[0][2] if language == "Hindi" else XP_LEVELS[0][1]
    current_threshold = XP_LEVELS[0][0]
    next_threshold: int | None = None
    for index, (threshold, english_name, hindi_name) in enumerate(XP_LEVELS):
        if xp >= threshold:
            current_threshold = threshold
            current_name = hindi_name if language == "Hindi" else english_name
            next_threshold = XP_LEVELS[index + 1][0] if index + 1 < len(XP_LEVELS) else None
    progress = xp - current_threshold
    return current_name, current_threshold, next_threshold, progress


def profile_text(user: User, rank: int | None) -> str:
    accuracy = (user.correct_answers * 100 / user.total_attempts) if user.total_attempts else 0
    language = user.preferred_language if user.preferred_language in {"Hindi", "English"} else "Hindi"
    level_name, level_start, next_level, level_progress = xp_level_info(user.xp, language)
    # Profiles intentionally show the Telegram display name only; usernames are private identifiers.
    identity = _tagged_identity(user.display_name, None, user.honor_tag, user.star_title)
    rank_text = str(rank) if rank else "Not ranked in this group yet"
    if next_level is not None:
        span = max(1, next_level - level_start)
        filled = min(10, max(0, int((user.xp - level_start) * 10 / span)))
        progress_bar = "█" * filled + "░" * (10 - filled)
        xp_progress = (
            f"⚡ <b>XP:</b> {user.xp:,} / {next_level:,}"
            f" ({'अगले स्तर में' if language == 'Hindi' else 'next level'}: {max(0, next_level - user.xp):,} XP)\n"
            f"   {progress_bar}"
        )
    else:
        xp_progress = f"⚡ <b>XP:</b> {user.xp:,} / MAX\n   {'█' * 10}"
    achievements = list(user.gsi_achievements or [])
    achievement_lines = [
        f"• {html.escape(GSI_HONOR_TAG)} <b>GSI ({html.escape(str(quiz_name))})</b>"
        for quiz_name in achievements
    ]
    if int(user.star_count or 0) > 0:
        achievement_lines.append(f"• ⭐ <b>Star Quizzer ×{int(user.star_count)}</b>")
    achievement_block = "\n".join(achievement_lines) if achievement_lines else "No achievements yet"
    return (
        "🏅 <b>Scholar Profile</b>\n\n"
        f"👤 <b>{identity}</b>\n"
        f"{xp_progress}\n"
        f"🎓 <b>Level:</b> {html.escape(level_name)}   •   <b>Points:</b> {user.total_points}\n"
        f"📝 <b>Total attempts:</b> {user.total_attempts}\n"
        f"✅ <b>Correct:</b> {user.correct_answers}   •   ❌ <b>Wrong:</b> {user.wrong_answers}\n"
        f"🎯 <b>Accuracy:</b> {accuracy:.1f}%\n"
        f"🔥 <b>Current streak:</b> {user.current_streak}   •   <b>Best:</b> {user.best_streak}\n"
        f"🏆 <b>Achievements</b>\n{achievement_block}\n\n"
        f"📊 <b>Group rank:</b> {html.escape(str(rank_text))}"
    )


def rules_text(language: str) -> str:
    if language == "English":
        return (
            "📘 <b>STUDY MCQ BOT — RULES & REWARDS</b>\n\n"
            "⚡ <b>XP SYSTEM</b>\n"
            "• Correct regular answer: <b>+10 XP</b>\n"
            "• Daily Challenge correct answer: <b>+20 bonus XP</b>\n"
            "• XP measures learning progress; official rewards are separate.\n\n"
            "🎓 <b>XP LEVELS</b>\n"
            "New Learner: 0+   •   Regular Scholar: 500+\n"
            "Focused Scholar: 1,500+   •   Exam Warrior: 3,000+\n"
            "Elite Scholar: 6,000+   •   Master Scholar: 10,000+\n"
            "Grand Scholar: 20,000+\n\n"
            "🔥 <b>STREAK BONUSES</b>\n"
            "3 consecutive correct: +5 XP   •   5: +10 XP\n"
            "10 consecutive correct: +25 XP\n\n"
            "🧪 <b>MOCK TEST</b>\n"
            "A mock test starts when at least 2 participants have joined. Questions follow a fixed time schedule, and the final scorecard is shown after completion."
            " Mock-test correct answers follow normal XP rules; duplicate answers never earn XP.\n\n"
            "🎯 <b>ACCURACY & FAIR PLAY</b>\n"
            "Only validated correct answers earn XP. Duplicate poll answers are ignored."
            " Accuracy is used as a leaderboard tie-breaker after XP.\n\n"
            "🏆 <b>GSI QUIZ</b>\n"
            "The winner earns the GSI title and a quiz-specific achievement such as GSI (August2026)."
            " GSI is not awarded through XP.\n\n"
            "⭐ <b>STAR QUIZ</b>\n"
            "Every Star Quiz win adds one star. The profile title becomes Star Quizzer ×N."
            " Star rewards are separate from XP and GSI."
        )
    return (
        "📘 <b>स्टडी MCQ बॉट — नियम और रिवॉर्ड</b>\n\n"
        "⚡ <b>XP सिस्टम</b>\n"
        "• सही regular answer: <b>+10 XP</b>\n"
        "• Daily Challenge सही answer: <b>+20 bonus XP</b>\n"
        "• XP पढ़ाई की progress है; official rewards अलग हैं।\n\n"
        "🎓 <b>XP LEVELS</b>\n"
        "New Learner: 0+   •   Regular Scholar: 500+\n"
        "Focused Scholar: 1,500+   •   Exam Warrior: 3,000+\n"
        "Elite Scholar: 6,000+   •   Master Scholar: 10,000+\n"
        "Grand Scholar: 20,000+\n\n"
        "🔥 <b>STREAK BONUS</b>\n"
        "लगातार 3 सही: +5 XP   •   5 सही: +10 XP\n"
        "लगातार 10 सही: +25 XP\n\n"
        "🧪 <b>MOCK TEST</b>\n"
        "Mock test कम से कम 2 participants के join होने पर शुरू होता है। Questions fixed time schedule पर आते हैं और अंत में final scorecard दिखता है।"
        " Mock test के सही answers पर normal XP rules लागू होते हैं; duplicate answer पर XP नहीं मिलेगा।\n\n"
        "🎯 <b>ACCURACY और FAIR PLAY</b>\n"
        "सिर्फ validated सही answer पर XP मिलेगा। एक ही poll का duplicate answer दोबारा XP नहीं देगा।"
        " XP बराबर होने पर leaderboard में accuracy tie-breaker होगी।\n\n"
        "🏆 <b>GSI QUIZ</b>\n"
        "Winner को GSI title और GSI (August2026) जैसी quiz-specific achievement मिलेगी।"
        " GSI XP से नहीं मिलता।\n\n"
        "⭐ <b>STAR QUIZ</b>\n"
        "हर Star Quiz जीतने पर 1 star मिलेगा। Profile में Star Quizzer ×N दिखेगा।"
        " Star reward XP और GSI से अलग है।"
    )


def settings_text(settings: GroupSettings, title: str = "Study Group") -> str:
    """Render an advanced, readable settings summary with the chat name first."""
    status = "🟢 Running" if settings.quiz_active else "⚪ Stopped"
    language = "Hindi" if settings.language == "Hindi" else "English"
    subject_labels: list[str] = []
    for subject in settings.subjects or []:
        label = display_subject_for_state(settings.state, subject)
        if label == "Indian History":
            label = "History"
        elif label == "Indian Geography":
            label = "Geography"
        subject_labels.append(html.escape(label))
    subjects = " • ".join(subject_labels) or "Not selected"
    safe_title = html.escape(title or "Study Group")
    state = html.escape(settings.state)
    return (
        f"⚙️ <b>{safe_title} — Quiz Settings</b>\n\n"
        "👥 <b>GROUP PROFILE</b>\n"
        f"🏷 <b>Group:</b> {safe_title}\n"
        f"📍 <b>State:</b> {state}\n"
        f"📚 <b>Subjects:</b> {subjects}\n\n"
        "⚙️ <b>QUIZ CONFIGURATION</b>\n"
        f"🌐 <b>Language:</b> {language}\n"
        "🎯 <b>Level:</b> Exam-level • Fact-heavy questions\n"
        f"⏱ <b>Interval:</b> Every {settings.interval_minutes} minutes\n"
        "🔄 <b>Subject Rotation:</b> 🟢 ALWAYS ON\n"
        "💡 <b>Explanation:</b> 🟢 ALWAYS ON\n"
        f"📡 <b>Automatic Quiz:</b> {status}"
    )


def stop_confirmation_text(language: str, *, private: bool = False) -> str:
    scope_hi = "Private Automatic Quiz" if private else "Automatic Quiz"
    scope_en = "Private Automatic Quiz" if private else "Automatic Quiz"
    if language == "Hindi":
        return (
            f"⚠️ <b>{scope_hi} बंद करने की पुष्टि</b>\n\n"
            f"क्या आप सच में <b>{scope_hi}</b> बंद करना चाहते हैं?\n"
            "Active polls हटाए नहीं जाएंगे।\n\n"
            "नीचे <b>Yes</b> दबाने पर ही quiz बंद होगी।"
        )
    return (
        f"⚠️ <b>Confirm stopping {scope_en}</b>\n\n"
        f"Do you really want to stop <b>{scope_en}</b>?\n"
        "Active polls will not be removed.\n\n"
        "The quiz will stop only after you press <b>Yes, Stop Quiz</b>."
    )


def stop_confirmation_keyboard(language: str, *, private: bool = False) -> InlineKeyboardMarkup:
    prefix = "dset" if private else "gset"
    yes = "✅ हाँ, Quiz रोकें" if language == "Hindi" else "✅ Yes, Stop Quiz"
    cancel = "🔙 रद्द करें" if language == "Hindi" else "🔙 Cancel"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(yes, callback_data=f"{prefix}:stopconfirm"),
        InlineKeyboardButton(cancel, callback_data=f"{prefix}:stopcancel"),
    ]])


def already_off_text(language: str, *, private: bool = False) -> str:
    scope_hi = "Private Automatic Quiz" if private else "Automatic Quiz"
    scope_en = "Private Automatic Quiz" if private else "Automatic Quiz"
    if language == "Hindi":
        return (
            f"ℹ️ <b>{scope_hi} पहले से OFF है</b>\n\n"
            f"इसे चालू करने के लिए <code>/startquiz</code> दें।"
        )
    return (
        f"ℹ️ <b>{scope_en} is already OFF</b>\n\n"
        "Use <code>/startquiz</code> to turn it on."
    )


def stopped_text(language: str, *, private: bool = False) -> str:
    scope_hi = "Private Automatic Quiz" if private else "Automatic Quiz"
    scope_en = "Private Automatic Quiz" if private else "Automatic Quiz"
    if language == "Hindi":
        return f"✅ <b>{scope_hi} बंद कर दिया गया है</b>\n\nअब नए automatic questions schedule नहीं होंगे।"
    return f"✅ <b>{scope_en} stopped</b>\n\nNo new automatic questions will be scheduled."


def interval_from_arg(value: str) -> int | None:
    try:
        interval = int(value)
    except ValueError:
        return None
    return interval if interval in VALID_INTERVALS else None


def period_start(period: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if period == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "weekly":
        return now.replace(hour=0, minute=0, second=0, microsecond=0) - __import__("datetime").timedelta(days=now.weekday())
    if period == "monthly":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return None


def leaderboard_text(rows: list[dict], label: str) -> str:
    if not rows:
        return f"🏆 <b>{html.escape(label)} Leaderboard</b>\n\nNo scored answers yet."
    lines = [
        f"🏆 <b>{html.escape(label.upper())} LEADERBOARD</b>",
        "━━━━━━━━━━━━━━━━━━",
        "<b>Rank  •  Scholar  •  XP  •  Accuracy</b>",
    ]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for rank, row in enumerate(rows, 1):
        name = _tagged_identity(
            row.get("display_name", "Student"), None, row.get("honor_tag"), row.get("star_title")
        )
        xp = int(row.get("xp") or 0)
        correct = int(row.get("correct") or 0)
        attempts = int(row.get("attempts") or 0)
        accuracy = correct * 100 / attempts if attempts else 0
        achievements = list(row.get("gsi_achievements") or [])
        achievement_items = [f"GSI ({quiz_name})" for quiz_name in achievements]
        star_count = int(row.get("star_count") or 0)
        if star_count > 0:
            achievement_items.append(f"Star Quizzer ×{star_count}")
        achievement_text = ", ".join(achievement_items) if achievement_items else "—"
        badge = medals.get(rank, f"<b>{rank}.</b>")
        lines.append(
            f"{badge} <b>{name}</b>\n"
            f"   ⚡ XP: <b>{xp}</b>   •   🎯 Accuracy: <b>{accuracy:.1f}%</b>\n"
            f"   ✅ Correct: <b>{correct}</b>   •   🏆 Achievements: <b>{html.escape(achievement_text)}</b>"
        )
    lines.extend(["", "━━━━━━━━━━━━━━━━━━", "🔥 Keep learning. Keep climbing."])
    return "\n".join(lines)


def group_stats_text(stats: dict[str, int]) -> str:
    accuracy = stats["correct"] * 100 / stats["attempts"] if stats["attempts"] else 0
    return (
        "📊 <b>ADVANCED GROUP INSIGHTS</b>\n\n"
        f"👥 <b>Active scholars:</b> {stats['players']}\n"
        f"📝 <b>Quiz attempts:</b> {stats['attempts']}\n"
        f"✅ <b>Correct answers:</b> {stats['correct']}\n"
        f"🎯 <b>Group accuracy:</b> {accuracy:.1f}%\n"
        f"📚 <b>Quiz sessions:</b> {stats['quizzes']}\n\n"
        "🏆 Rankings reward accuracy, consistency and daily participation."
    )

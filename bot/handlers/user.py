"""User-facing commands and group-scoped statistics."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.config import VALID_SUBJECTS
from bot.database.repositories import Repository
from bot.handlers.start import support_links_keyboard
from bot.utils.helpers import group_stats_text, leaderboard_text, period_start, profile_text, rules_text


async def _require_chat(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_message)


async def _upsert_user_and_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat:
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.upsert_user(update.effective_user.id, update.effective_user.username, update.effective_user.full_name)
        if update.effective_chat.type in {"group", "supergroup"}:
            await repo.ensure_group(update.effective_chat.id, update.effective_chat.title or "Study Group", update.effective_chat.type)
        await repo.commit()


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_chat(update) or not update.effective_user:
        return
    await _upsert_user_and_group(update, context)
    message = update.effective_message
    replied_user = message.reply_to_message.from_user if message.reply_to_message else None
    target = replied_user if replied_user and not replied_user.is_bot else update.effective_user
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.upsert_user(target.id, target.username, target.full_name)
        await repo.commit()
        user = await repo.get_user(target.id)
        rank = (
            await repo.group_rank(update.effective_chat.id, target.id)
            if update.effective_chat.type in {"group", "supergroup"} else None
        )
    await message.reply_text(
        profile_text(user, rank) if user else "No profile found. Use /start first.",
        parse_mode=ParseMode.HTML,
    )


async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await profile_command(update, context)


async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_chat(update) or not update.effective_user:
        return
    await _upsert_user_and_group(update, context)
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        user = await Repository(session).get_user(update.effective_user.id)
    language = user.preferred_language if user and user.preferred_language in {"Hindi", "English"} else "Hindi"
    await update.effective_message.reply_text(
        rules_text(language), reply_markup=support_links_keyboard(language), parse_mode=ParseMode.HTML
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_chat(update):
        return
    if update.effective_chat.type not in {"group", "supergroup"}:
        await update.effective_message.reply_text("Use /profile in a private chat. Group statistics are available inside a group.")
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        stats = await repo.group_stats(update.effective_chat.id)
    await update.effective_message.reply_text(group_stats_text(stats), parse_mode=ParseMode.HTML)


async def rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_chat(update) or not update.effective_user:
        return
    if update.effective_chat.type not in {"group", "supergroup"}:
        await update.effective_message.reply_text("Ranks are group-specific. Use this command in a study group.")
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        rank = await Repository(session).group_rank(update.effective_chat.id, update.effective_user.id)
    await update.effective_message.reply_text(
        f"📊 <b>Your group rank:</b> {rank or 'Not ranked yet'}",
        parse_mode=ParseMode.HTML,
    )


def leaderboard_scope_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📍 This Group", callback_data="lb:group"),
        InlineKeyboardButton("🌐 Overall", callback_data="lb:overall"),
    ]])


async def _leaderboard_view(
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int | None,
    label: str,
    since=None,
) -> str:
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        rows = await Repository(session).leaderboard(group_id, since)
    return leaderboard_text(rows, label)


async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE, period: str = "all_time") -> None:
    if not await _require_chat(update):
        return
    if update.effective_chat.type not in {"group", "supergroup"}:
        await update.effective_message.reply_text("Leaderboards are group-specific. Use this command in a study group.")
        return
    label = "This Group" if period == "all_time" else {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}[period]
    text = await _leaderboard_view(context, update.effective_chat.id, label, period_start(period))
    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=leaderboard_scope_keyboard() if period == "all_time" else None,
    )


async def leaderboard_scope_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.message is None or not query.data or not query.data.startswith("lb:"):
        return
    if query.message.chat.type not in {"group", "supergroup"}:
        await query.answer("यह leaderboard group में उपलब्ध है।", show_alert=True)
        return
    scope = query.data.split(":", 1)[1]
    if scope == "overall":
        label = "Overall"
        group_id = None
    else:
        label = "This Group"
        group_id = query.message.chat.id
    text = await _leaderboard_view(context, group_id, label, None)
    await query.answer("Overall leaderboard" if scope == "overall" else "This Group leaderboard")
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=leaderboard_scope_keyboard(),
    )


async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await leaderboard_command(update, context, "daily")


async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await leaderboard_command(update, context, "weekly")


async def monthly_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await leaderboard_command(update, context, "monthly")


async def subjects_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text("Supported subjects:\n" + ", ".join(sorted(VALID_SUBJECTS)))


async def mocktest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "Mock tests are launched by group admins. Once a test starts, answer every quiz poll before its stated deadline; results and ranks are posted automatically."
        )

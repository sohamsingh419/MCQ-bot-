"""Telegram-group administrator controls for quizzes and content."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import html
import os
import re

from sqlalchemy import func, select
from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from bot.config import UNIFIED_EXAM_LEVEL, default_subjects_for_state, get_settings, normalize_state, subjects_for_state
from bot.database.models import DeliveryCampaign, Group, GroupSettings, MockTest, OfficialQuiz, Question, SourceDocument, User
from bot.database.repositories import Repository
from bot.handlers.group_setup import interval_selector_keyboard, state_selector_keyboard, subject_selector_keyboard
from bot.services.question_validator import QuestionValidationError, validate_question
from bot.utils.helpers import (
    already_off_text, command_text, group_stats_text, interval_from_arg, parse_bool, parse_subjects,
    settings_text, stop_confirmation_keyboard, stop_confirmation_text, stopped_text,
)


async def _admin_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or not update.effective_user or not update.effective_message:
        return False
    if update.effective_chat.type not in {"group", "supergroup"}:
        await update.effective_message.reply_text("This configuration command must be used in a Telegram group.")
        return False
    settings = get_settings()
    if update.effective_user.id not in settings.global_admin_ids:
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        except Exception:
            await update.effective_message.reply_text("I could not verify administrator rights. Make sure the bot is an administrator.")
            return False
        if member.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}:
            await update.effective_message.reply_text("Only group administrators can change quiz settings.")
            return False
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.ensure_group(update.effective_chat.id, update.effective_chat.title or "Study Group", update.effective_chat.type)
        await repo.commit()
    return True


def _log_snapshot(text: str, limit: int = 80) -> dict[str, object]:
    lines = text.splitlines()
    generated = re.findall(r"MCQ generated via ([A-Za-z0-9_-]+) provider", text)
    validator_approved = len(re.findall(r"validator approved MCQ|independent validation", text, re.IGNORECASE))
    unavailable = len(re.findall(r"unavailable|429|403 Forbidden|404 Not Found", text, re.IGNORECASE))
    no_fresh = len(re.findall(r"No unseen question available", text))
    error_lines = [
        line.strip() for line in lines
        if re.search(r"ERROR|Traceback|Scheduler tick failed|Unhandled bot update error|AI generation failed", line, re.IGNORECASE)
    ]
    return {
        "generated": generated[-limit:],
        "validator_approved": validator_approved,
        "unavailable": unavailable,
        "no_fresh": no_fresh,
        "errors": error_lines[-8:],
    }


def _report_chunks(text: str, limit: int = 3800) -> list[str]:
    chunks: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if current and len(candidate) > limit:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


async def botreport_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    settings = get_settings()
    if update.effective_user.id not in settings.global_admin_ids:
        await update.effective_message.reply_text("यह diagnostic report केवल configured bot admin के लिए उपलब्ध है।")
        return

    database = context.application.bot_data["database"]
    now = datetime.now(timezone.utc)
    configured_log_path = Path(settings.log_file)
    log_path = configured_log_path if configured_log_path.is_absolute() else Path(__file__).resolve().parents[2] / configured_log_path
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")[-180_000:]
    except OSError:
        log_text = ""
    log = _log_snapshot(log_text)

    async with database.session_factory() as session:
        total_questions = int((await session.scalar(select(func.count(Question.id)))) or 0)
        source_rows = (await session.execute(select(Question.source, func.count(Question.id)).group_by(Question.source))).all()
        recent_questions = int((await session.scalar(
            select(func.count(Question.id)).where(Question.created_at >= now - timedelta(hours=24))
        )) or 0)
        document_rows = (await session.execute(
            select(SourceDocument.status, func.count(SourceDocument.id)).group_by(SourceDocument.status)
        )).all()
        group_rows = (await session.execute(
            select(Group.chat_type, func.count(Group.telegram_chat_id)).where(Group.is_active.is_(True)).group_by(Group.chat_type)
        )).all()
        active_regular = int((await session.scalar(
            select(func.count(GroupSettings.group_id)).where(GroupSettings.quiz_active.is_(True))
        )) or 0)
        active_mocks = list((await session.execute(
            select(MockTest.id, MockTest.title, MockTest.current_question_number, MockTest.question_count, MockTest.status)
            .where(MockTest.status.in_(["lobby", "running"])).order_by(MockTest.id.desc())
        )).all())
        active_official = list((await session.execute(
            select(OfficialQuiz.id, OfficialQuiz.slug, OfficialQuiz.quiz_type, OfficialQuiz.current_question_number, OfficialQuiz.question_count, OfficialQuiz.status)
            .where(OfficialQuiz.status.in_(["lobby", "countdown", "running"])).order_by(OfficialQuiz.id.desc())
        )).all())
        latest_campaigns = list((await session.execute(
            select(DeliveryCampaign.id, DeliveryCampaign.content_type, DeliveryCampaign.status, DeliveryCampaign.sent_count, DeliveryCampaign.failed_count)
            .order_by(DeliveryCampaign.id.desc()).limit(3)
        )).all())

    scheduler = context.application.bot_data.get("scheduler")
    scheduler_task = getattr(scheduler, "_task", None)
    scheduler_status = "RUNNING" if scheduler_task is not None and not scheduler_task.done() else "NOT RUNNING"
    provider_config = {
        "Gemini": bool(settings.gemini_api_key),
        "Groq": bool(settings.groq_api_key),
        "Mistral": bool(settings.mistral_api_key),
        "OpenAI-compatible": bool(settings.ai_api_key),
    }
    source_text = ", ".join(f"{html.escape(str(source or 'unknown'))}: {count}" for source, count in source_rows) or "none"
    docs_text = ", ".join(f"{html.escape(str(status))}: {count}" for status, count in document_rows) or "none"
    groups_text = ", ".join(f"{html.escape(str(kind))}: {count}" for kind, count in group_rows) or "none"
    providers_text = ", ".join(f"{name}: {'configured' if configured else 'not configured'}" for name, configured in provider_config.items())
    generated_text = ", ".join(log["generated"][-12:]) if log["generated"] else "no provider generation entry in recent log window"
    mock_text = "; ".join(f"#{item[0]} {item[1]} {item[2]}/{item[3]} ({item[4]})" for item in active_mocks) or "none"
    official_text = "; ".join(f"#{item[0]} {item[1]} [{item[2]}] {item[3]}/{item[4]} ({item[5]})" for item in active_official) or "none"
    campaign_text = "; ".join(f"#{item[0]} {item[1]} {item[2]} sent={item[3]} failed={item[4]}" for item in latest_campaigns) or "none"
    error_text = "\n".join(f"• {html.escape(line[-360:])}" for line in log["errors"]) or "• no recent critical error lines"

    report = (
        "🔎 <b>BOT OPERATIONS REPORT</b>\n"
        f"Generated: <code>{html.escape(now.isoformat())}</code>\n"
        f"Process: <b>RUNNING</b> (PID {os.getpid()})\n"
        f"Scheduler: <b>{scheduler_status}</b>\n"
        f"Timezone: <code>{html.escape(settings.timezone)}</code>\n\n"
        "<b>QUESTION GENERATION</b>\n"
        f"Total stored: <b>{total_questions}</b>\n"
        f"Created in last 24h: <b>{recent_questions}</b>\n"
        f"By source: {source_text}\n"
        f"Recent generated providers: {html.escape(generated_text)}\n"
        f"Validator approvals in log window: <b>{log['validator_approved']}</b>\n"
        f"Provider unavailable/rate-limit entries: <b>{log['unavailable']}</b>\n"
        f"No-fresh-question entries: <b>{log['no_fresh']}</b>\n\n"
        "<b>AI PROVIDERS</b>\n"
        f"{html.escape(providers_text)}\n\n"
        "<b>SOURCES / DATABASE</b>\n"
        f"Source documents: {docs_text}\n"
        f"Active chats: {groups_text}\n"
        f"Regular automatic quiz chats: <b>{active_regular}</b>\n\n"
        "<b>ACTIVE QUIZZES</b>\n"
        f"Mock tests: {html.escape(mock_text)}\n"
        f"GSI/Star quizzes: {html.escape(official_text)}\n\n"
        "<b>RECENT BROADCASTS</b>\n"
        f"{html.escape(campaign_text)}\n\n"
        "<b>RECENT ERRORS</b>\n"
        f"{error_text}"
    )
    for chunk in _report_chunks(report):
        await update.effective_message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show a compact operational status report to the configured bot admins."""
    if not update.effective_user or not update.effective_message:
        return
    settings = get_settings()
    if update.effective_user.id not in settings.global_admin_ids:
        await update.effective_message.reply_text("यह command केवल configured bot admin के लिए उपलब्ध है।")
        return

    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        total_users = int((await session.scalar(select(func.count(User.telegram_user_id)))) or 0)
        active_groups = int((await session.scalar(
            select(func.count(Group.telegram_chat_id)).where(
                Group.is_active.is_(True), Group.chat_type.in_(["group", "supergroup"])
            )
        )) or 0)
        admin_groups = int((await session.scalar(
            select(func.count(GroupSettings.group_id))
            .join(Group, Group.telegram_chat_id == GroupSettings.group_id)
            .where(
                Group.is_active.is_(True),
                Group.chat_type.in_(["group", "supergroup"]),
                GroupSettings.bot_is_admin.is_(True),
            )
        )) or 0)
        private_chats = int((await session.scalar(
            select(func.count(Group.telegram_chat_id)).where(
                Group.is_active.is_(True), Group.chat_type == "private"
            )
        )) or 0)
        active_regular = int((await session.scalar(
            select(func.count(GroupSettings.group_id)).where(GroupSettings.quiz_active.is_(True))
        )) or 0)
        active_mocks = int((await session.scalar(
            select(func.count(MockTest.id)).where(MockTest.status.in_(["lobby", "running"]))
        )) or 0)
        active_official = int((await session.scalar(
            select(func.count(OfficialQuiz.id)).where(OfficialQuiz.status.in_(["lobby", "countdown", "running"]))
        )) or 0)
        total_questions = int((await session.scalar(select(func.count(Question.id)))) or 0)
        ready_documents = int((await session.scalar(
            select(func.count(SourceDocument.id)).where(SourceDocument.status == "ready")
        )) or 0)
    non_admin_groups = max(0, active_groups - admin_groups)

    scheduler = context.application.bot_data.get("scheduler")
    scheduler_task = getattr(scheduler, "_task", None)
    scheduler_state = "RUNNING" if scheduler_task is not None and not scheduler_task.done() else "NOT RUNNING"
    report = (
        "📊 <b>GSI QUIZ — BOT STATUS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Total users:</b> {total_users}\n"
        f"💬 <b>Private chats:</b> {private_chats}\n"
        f"👥 <b>Total groups:</b> {active_groups}\n"
        f"✅ <b>Bot is admin:</b> {admin_groups}\n"
        f"⚠️ <b>Bot is not admin:</b> {non_admin_groups}\n\n"
        f"🧠 <b>Active automatic quizzes:</b> {active_regular}\n"
        f"📝 <b>Active mock tests:</b> {active_mocks}\n"
        f"🏆 <b>Active GSI/Star quizzes:</b> {active_official}\n"
        f"📚 <b>Stored questions:</b> {total_questions}\n"
        f"📄 <b>Ready source documents:</b> {ready_documents}\n\n"
        f"⚙️ <b>Scheduler:</b> {scheduler_state}\n"
        f"🌐 <b>Timezone:</b> <code>{html.escape(settings.timezone)}</code>\n\n"
        "<i>Admin readiness is based on the latest membership-status check. "
        "Groups without admin rights receive reminders at 10m, 1h, 2h, 6h, 12h, 24h, and 48h only.</i>"
    )
    await update.effective_message.reply_text(report, parse_mode="HTML", disable_web_page_preview=True)


async def _set_question_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE, enabled: bool | None = None) -> None:
    if not update.effective_user or not update.effective_message:
        return
    settings = get_settings()
    if update.effective_user.id not in settings.global_admin_ids:
        await update.effective_message.reply_text("यह command केवल configured bot admin के लिए उपलब्ध है।")
        return
    if enabled is None:
        raw = command_text(context.args).casefold() if context.args else ""
        if raw in {"on", "enable", "enabled", "चालू", "start"}:
            enabled = True
        elif raw in {"off", "disable", "disabled", "बंद", "stop"}:
            enabled = False
        else:
            database = context.application.bot_data["database"]
            async with database.session_factory() as session:
                control = await Repository(session).get_bot_control()
                await session.commit()
            state = "ON / चालू" if control.question_delivery_enabled else "OFF / बंद"
            await update.effective_message.reply_text(
                f"Global question delivery: <b>{state}</b>.", parse_mode="HTML"
            )
            return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        control = await repo.set_question_delivery_enabled(enabled, update.effective_user.id)
        await repo.commit()
    if enabled:
        message = (
            "✅ <b>Global question delivery ON / चालू</b>\n\n"
            "Automatic questions अब सभी eligible groups और private chats में फिर से भेजे जाएँगे।"
        )
    else:
        message = (
            "⏸️ <b>Global question delivery OFF / बंद</b>\n\n"
            "Bot अब किसी group या private chat में automatic questions नहीं भेजेगी। Existing polls के answers और results फिर भी process होंगे।"
        )
    await update.effective_message.reply_text(message, parse_mode="HTML")


async def questiondelivery_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _set_question_delivery(update, context)


async def questiondelivery_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _set_question_delivery(update, context, True)


async def questiondelivery_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _set_question_delivery(update, context, False)


async def _settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        return await Repository(session).get_settings(update.effective_chat.id)


async def setstate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat and update.effective_chat.type == "private":
        from bot.handlers.dm import dmstate_command
        await dmstate_command(update, context)
        return
    if not await _admin_group(update, context):
        return
    if not context.args:
        await update.effective_message.reply_text("🗺️ अपना state चुनें:", reply_markup=state_selector_keyboard(0))
        return
    state = normalize_state(command_text(context.args))
    if not state:
        await update.effective_message.reply_text("Valid states: Rajasthan, Uttar Pradesh, Bihar, Madhya Pradesh, Haryana, General.")
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.update_settings(
            update.effective_chat.id, state=state, subjects=default_subjects_for_state(state), current_rotation_index=0
        )
        await repo.commit()
    await update.effective_message.reply_text(f"State scope saved: {state}.")


async def setsubject_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat and update.effective_chat.type == "private":
        from bot.handlers.dm import dmsubjects_command
        await dmsubjects_command(update, context)
        return
    if not await _admin_group(update, context):
        return
    if not context.args:
        settings = await _settings(update, context)
        await update.effective_message.reply_text(
            f"📚 {settings.state} के subjects चुनें:", reply_markup=subject_selector_keyboard(settings)
        )
        return
    subjects = parse_subjects(command_text(context.args))
    if not subjects:
        await update.effective_message.reply_text("Use comma-separated supported names, for example: /setsubject Indian Polity, History, Geography")
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        settings = await repo.get_settings(update.effective_chat.id)
        allowed = set(subjects_for_state(settings.state))
        if not set(subjects).issubset(allowed):
            await update.effective_message.reply_text(
                f"Choose only subjects available for {settings.state}: " + ", ".join(subjects_for_state(settings.state))
            )
            return
        await repo.update_settings(update.effective_chat.id, subjects=subjects, current_rotation_index=0)
        await repo.commit()
    await update.effective_message.reply_text("Subjects saved: " + ", ".join(subjects))


async def setxp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _admin_group(update, context):
        return
    if len(context.args) == 1:
        difficulty, raw_points = UNIFIED_EXAM_LEVEL, context.args[0]
    elif len(context.args) == 2 and context.args[0].title() == UNIFIED_EXAM_LEVEL:
        difficulty, raw_points = UNIFIED_EXAM_LEVEL, context.args[1]
    else:
        await update.effective_message.reply_text("Use /setxp <positive XP> or /setxp Exam <positive XP>.")
        return
    try:
        points = int(raw_points)
    except ValueError:
        points = 0
    if difficulty != UNIFIED_EXAM_LEVEL or not 1 <= points <= 1000:
        await update.effective_message.reply_text("Use the unified Exam level and an XP value from 1 to 1000.")
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        settings = await repo.get_settings(update.effective_chat.id)
        xp_map = dict(settings.xp_map or {})
        xp_map[difficulty] = points
        await repo.update_settings(update.effective_chat.id, xp_map=xp_map)
        await repo.commit()
    await update.effective_message.reply_text(f"XP for unified Exam questions is now {points}.")


async def setinterval_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat and update.effective_chat.type == "private":
        from bot.handlers.dm import dminterval_command
        await dminterval_command(update, context)
        return
    if not await _admin_group(update, context):
        return
    if not context.args:
        await update.effective_message.reply_text("⏱️ quiz interval चुनें:", reply_markup=interval_selector_keyboard())
        return
    interval = interval_from_arg(command_text(context.args))
    if not interval:
        await update.effective_message.reply_text("Interval must be one of: 10, 15, 20, 30, or 60 minutes.")
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.update_settings(update.effective_chat.id, interval_minutes=interval)
        await repo.commit()
    await update.effective_message.reply_text(f"Automatic quiz interval saved: every {interval} minutes.")


async def startquiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat and update.effective_chat.type == "private":
        from bot.handlers.dm import dmstart_command
        await dmstart_command(update, context)
        return
    if not await _admin_group(update, context):
        return

    chat = update.effective_chat
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        settings = await repo.get_settings(chat.id)
        if settings is None:
            await repo.ensure_group(chat.id, chat.title or "Study Group", chat.type)
            settings = await repo.get_settings(chat.id)
        was_active = bool(settings and settings.quiz_active)
        interval = int(settings.interval_minutes if settings else 10)
        language = settings.language if settings else "Hindi"
        if not was_active:
            await repo.update_settings(chat.id, quiz_active=True, last_quiz_at=None)
        await repo.commit()

    group_name = html.escape(chat.title or "Study Group")
    if was_active:
        if language == "Hindi":
            message = (
                "ℹ️ <b>Automatic Quiz पहले से ON है</b>\n\n"
                f"👥 <b>Group:</b> {group_name}\n"
                f"⏱ <b>Next question:</b> configured schedule के अनुसार हर {interval} मिनट पर\n\n"
                "Automatic Quiz रोकने के लिए <code>/stopquiz</code> दें।"
            )
        else:
            message = (
                "ℹ️ <b>Automatic Quiz is already ON</b>\n\n"
                f"👥 <b>Group:</b> {group_name}\n"
                f"⏱ <b>Next question:</b> according to the configured {interval}-minute schedule\n\n"
                "Use <code>/stopquiz</code> to stop Automatic Quiz."
            )
        await update.effective_message.reply_text(message, parse_mode="HTML")
        return

    if language == "Hindi":
        message = (
            "🚀 <b>Automatic Quiz शुरू हो गया है</b>\n\n"
            f"👥 <b>Group:</b> {group_name}\n"
            "✅ पहली practice question अभी भेजी जा रही है।\n"
            f"⏱ इसके बाद questions हर {interval} मिनट के configured schedule के अनुसार आएँगे।\n\n"
            "Automatic Quiz रोकने के लिए <code>/stopquiz</code> दें।"
        )
    else:
        message = (
            "🚀 <b>Automatic Quiz started</b>\n\n"
            f"👥 <b>Group:</b> {group_name}\n"
            "✅ The first practice question is being sent now.\n"
            f"⏱ After that, questions will arrive according to the configured {interval}-minute schedule.\n\n"
            "Use <code>/stopquiz</code> to stop Automatic Quiz."
        )
    await update.effective_message.reply_text(message, parse_mode="HTML")
    service = context.application.bot_data["quiz_service"]
    question = await service.send_quiz(chat.id, force=True)
    if question is None:
        fallback = (
            "⚠️ पहली practice question अभी उपलब्ध नहीं हो सकी। अगली कोशिश configured schedule के अनुसार होगी।"
            if language == "Hindi"
            else "⚠️ The first practice question could not be delivered yet. The scheduler will retry at the configured interval."
        )
        await update.effective_message.reply_text(fallback)


async def stopquiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat and update.effective_chat.type == "private":
        from bot.handlers.dm import dmstop_command
        await dmstop_command(update, context)
        return
    if not await _admin_group(update, context):
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        settings = await repo.get_settings(update.effective_chat.id)
        language = settings.language if settings else "Hindi"
        is_active = bool(settings and settings.quiz_active)
        await repo.commit()
    if not is_active:
        await update.effective_message.reply_text(already_off_text(language), parse_mode="HTML")
        return
    await update.effective_message.reply_text(
        stop_confirmation_text(language),
        reply_markup=stop_confirmation_keyboard(language),
        parse_mode="HTML",
    )


async def setmode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _admin_group(update, context):
        return
    mode = command_text(context.args).casefold()
    if mode not in {"automatic", "manual"}:
        await update.effective_message.reply_text("Use /setmode automatic or /setmode manual. Manual mode stops scheduled quizzes but permits /startquiz.")
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        await repo.update_settings(update.effective_chat.id, quiz_active=(mode == "automatic"))
        await repo.commit()
    await update.effective_message.reply_text(f"Quiz mode saved: {mode}.")


async def groupstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _admin_group(update, context):
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        settings = await repo.get_settings(update.effective_chat.id)
        stats = await repo.group_stats(update.effective_chat.id)
    await update.effective_message.reply_text(
        settings_text(settings, update.effective_chat.title or "Study Group") + "\n\n" + group_stats_text(stats),
        parse_mode="HTML",
    )


async def addquestion_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _admin_group(update, context):
        return
    raw = command_text(context.args)
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) not in {10, 11}:
        await update.effective_message.reply_text(
            "Format: /addquestion question | option 1 | option 2 | option 3 | option 4 | correct number (1-4) | explanation | subject | topic | difficulty | optional key point"
        )
        return
    try:
        correct = int(parts[5]) - 1
        settings = await _settings(update, context)
        payload = {
            "question": parts[0], "options": parts[1:5], "correct_option": correct,
            "explanation": parts[6], "subject": parts[7], "topic": parts[8], "difficulty": UNIFIED_EXAM_LEVEL,
            "key_point": parts[10] if len(parts) == 11 else parts[6], "question_type": "Admin-supplied",
            "language": settings.language,
        }
        valid = validate_question(payload, expected_language=settings.language)
    except (ValueError, QuestionValidationError) as exc:
        await update.effective_message.reply_text(f"Question rejected: {exc}")
        return
    settings = await _settings(update, context)
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        if await repo.existing_question(__import__("bot.services.question_validator", fromlist=["normalize_text"]).normalize_text(valid.question)):
            await update.effective_message.reply_text("A matching question already exists and was not added.")
            return
        await repo.add_question(
            question_text=valid.question, options=valid.options, correct_option=valid.correct_option,
            explanation=valid.explanation, key_point=valid.key_point, state=settings.state, subject=valid.subject,
            topic=valid.topic, difficulty=valid.difficulty, question_type=valid.question_type, language=valid.language,
            source="admin", source_group_id=update.effective_chat.id,
        )
        await repo.commit()
    await update.effective_message.reply_text("Validated question added to the database.")


async def removequestion_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _admin_group(update, context):
        return
    try:
        question_id = int(command_text(context.args))
    except ValueError:
        await update.effective_message.reply_text("Use /removequestion followed by the numeric question ID.")
        return
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        removed = await repo.remove_question(question_id)
        await repo.commit()
    await update.effective_message.reply_text("Question removed." if removed else "No question with that ID exists.")


async def mocktest_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _admin_group(update, context):
        return
    raw = context.args
    try:
        count = int(raw[0]) if raw else 5
        seconds_per_question = int(raw[1]) if len(raw) > 1 else 30
    except ValueError:
        await update.effective_message.reply_text("Use /mocktest [question_count 2-50] [seconds_per_question 10-120].")
        return
    if not 2 <= count <= 50 or not 10 <= seconds_per_question <= 120:
        await update.effective_message.reply_text("Question count must be 2–50 and per-question time must be 10–120 seconds.")
        return
    database = context.application.bot_data.get("database")
    language = "Hindi"
    if database is not None:
        async with database.session_factory() as session:
            repo = Repository(session)
            settings = await repo.get_settings(update.effective_chat.id)
            language = settings.language if settings else "Hindi"
            await repo.commit()
    service = context.application.bot_data["quiz_service"]
    mock_id = await service.create_mock_lobby(
        update.effective_chat.id, count=count, round_seconds=seconds_per_question,
        title="Mock Test", created_by=update.effective_user.id,
    )
    if mock_id == -1:
        message = (
            "⏳ <b>Mock Test पहले से तैयार या चल रहा है</b>\n\n"
            "पहला Mock Test expire या complete होने के बाद ही नया Mock Test शुरू किया जा सकता है।\n"
            "कृपया थोड़ी देर बाद फिर प्रयास करें।"
            if language == "Hindi"
            else "⏳ <b>Mock Test is already ready or running</b>\n\n"
            "A new Mock Test can start only after the current one expires or completes.\n"
            "Please try again after a little while."
        )
        await update.effective_message.reply_text(message, parse_mode="HTML")
        return
    if not mock_id:
        await update.effective_message.reply_text("Mock-test lobby could not be launched.")


async def stopmocktest_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _admin_group(update, context):
        return
    service = context.application.bot_data["quiz_service"]
    mock_id = await service.stop_mock_test(update.effective_chat.id)
    if mock_id is None:
        await update.effective_message.reply_text("No active mock test or lobby is running in this group.")

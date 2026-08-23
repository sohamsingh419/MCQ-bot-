"""Inline callbacks for private explanations, onboarding, and learner controls."""
from __future__ import annotations

import logging

from sqlalchemy.exc import OperationalError
from telegram import Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

from bot.config import VALID_STATES, default_subjects_for_state, subjects_for_state, toggle_subject_selection
from bot.database.repositories import Repository
from bot.handlers.start import (
    completed_profile_text,
    confirmation_keyboard,
    confirmation_text,
    language_keyboard,
    onboarding_language_text,
    onboarding_state_text,
    onboarding_subject_text,
    group_help_text,
    private_help_text,
    private_quick_actions_keyboard,
    state_menu_keyboard,
    subject_keyboard,
)
from bot.services.quiz import QuizService

logger = logging.getLogger(__name__)


async def explanation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or not query.data.startswith("explain:"):
        return
    try:
        question_id = int(query.data.split(":", 1)[1])
    except ValueError:
        await query.answer("This explanation link is invalid.", show_alert=True)
        return

    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        question = await repo.get_question(question_id)
        source_message = getattr(query, "message", None)
        settings = await repo.get_settings(source_message.chat.id) if source_message else None
        history = (
            await repo.quiz_for_message(source_message.chat.id, source_message.message_id, question_id)
            if source_message is not None else None
        )
        answered = bool(history and await repo.user_has_answered_poll(history.telegram_poll_id, query.from_user.id))
    if question is None:
        await query.answer("This explanation is no longer available.", show_alert=True)
        return
    if not answered:
        ui_language = settings.language if settings is not None else "Hindi"
        message = "पहले इस प्रश्न का उत्तर दें, फिर व्याख्या देखें।" if ui_language == "Hindi" else "Answer this question first, then view the explanation."
        await query.answer(message, show_alert=True)
        return

    ui_language = settings.language if settings is not None else "Hindi"
    try:
        await context.bot.send_message(chat_id=query.from_user.id, text=QuizService.explanation_text(question, ui_language))
    except Forbidden:
        await query.answer(
            "Please open the bot privately and send /start once, then tap this button again.", show_alert=True,
        )
        return
    except TelegramError:
        logger.exception("Could not deliver a private explanation to user %s", query.from_user.id)
        await query.answer("The explanation could not be delivered. Please retry shortly.", show_alert=True)
        return

    message = "व्याख्या आपके निजी चैट में भेज दी गई है।" if ui_language == "Hindi" else "The explanation has been sent to your private chat."
    await query.answer(message, show_alert=False)


async def onboarding_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or not query.data.startswith("onb:") or query.message is None:
        return
    if query.message.chat.type != "private":
        await query.answer("This onboarding flow is available only in private chat.", show_alert=True)
        return

    parts = query.data.split(":", 2)
    action = parts[1]
    value = parts[2] if len(parts) == 3 else None
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        user = await repo.upsert_user(query.from_user.id, query.from_user.username, query.from_user.full_name)
        settings = await repo.ensure_group(query.message.chat.id, query.from_user.full_name or "Private Study", "private")

        if action == "language_menu":
            await repo.commit()
            await query.answer()
            await query.edit_message_text(
                onboarding_language_text(query.from_user.first_name), reply_markup=language_keyboard(), parse_mode="Markdown"
            )
            return

        if action == "language" and value in {"Hindi", "English"}:
            await repo.set_user_language(query.from_user.id, value)
            settings = await repo.update_settings(query.message.chat.id, language=value)
            await repo.commit()
            await query.answer("बढ़िया! हिंदी चुन ली गई है।" if value == "Hindi" else "Great! English selected.")
            await query.edit_message_text(
                onboarding_language_text(query.from_user.first_name),
                reply_markup=private_quick_actions_keyboard(value), parse_mode="Markdown"
            )
            return

        if action == "state_menu":
            await repo.commit()
            await query.answer()
            await query.edit_message_text(
                onboarding_state_text(settings.language, 0), reply_markup=state_menu_keyboard(settings.language, 0), parse_mode="Markdown"
            )
            return

        if action == "subjects_menu":
            await repo.commit()
            await query.answer()
            await query.edit_message_text(
                onboarding_subject_text(settings.language, settings.state),
                reply_markup=subject_keyboard(
                    settings.state, settings.language, back_callback="onb:welcome", selected_subjects=settings.subjects
                ), parse_mode="Markdown",
            )
            return

        if action == "welcome":
            await repo.commit()
            await query.answer()
            await query.edit_message_text(
                onboarding_language_text(query.from_user.first_name),
                reply_markup=private_quick_actions_keyboard(settings.language), parse_mode="Markdown",
            )
            return

        if action == "statepage" and value and value.isdigit():
            page = int(value)
            await repo.commit()
            await query.answer()
            await query.edit_message_text(
                onboarding_state_text(settings.language, page), reply_markup=state_menu_keyboard(settings.language, page), parse_mode="Markdown"
            )
            return

        if action == "state" and value in VALID_STATES:
            settings = await repo.update_settings(
                query.message.chat.id, state=value, subjects=default_subjects_for_state(value), current_rotation_index=0
            )
            await repo.update_user_onboarding(query.from_user.id, completed=False)
            await repo.commit()
            await query.answer("राज्य चुन लिया गया। अब विषय चुनें।" if settings.language == "Hindi" else "State selected. Now choose your subjects.")
            await query.edit_message_text(
                onboarding_subject_text(settings.language, settings.state),
                reply_markup=subject_keyboard(
                    settings.state, settings.language, selected_subjects=settings.subjects
                ), parse_mode="Markdown",
            )
            return

        if action == "subject" and value in subjects_for_state(settings.state):
            selected = toggle_subject_selection(settings.state, settings.subjects, value)
            settings = await repo.update_settings(
                query.message.chat.id, subjects=selected, current_rotation_index=0
            )
            await repo.update_user_onboarding(query.from_user.id, completed=False)
            await repo.commit()
            await query.answer("विषय अपडेट हो गए।" if settings.language == "Hindi" else "Subjects updated.")
            await query.edit_message_text(
                onboarding_subject_text(settings.language, settings.state),
                reply_markup=subject_keyboard(
                    settings.state, settings.language, back_callback="onb:welcome", selected_subjects=settings.subjects
                ), parse_mode="Markdown",
            )
            return

        if action == "subjects_done":
            if not settings.subjects:
                await query.answer(
                    "कम से कम एक विषय चुनें।" if settings.language == "Hindi" else "Select at least one subject.",
                    show_alert=True,
                )
                return
            user = await repo.update_user_onboarding(query.from_user.id, completed=True)
            settings = await repo.update_settings(
                query.message.chat.id, quiz_active=True, last_quiz_at=None
            )
            await repo.commit()
            await query.answer("आपकी Study Profile तैयार है। पहला प्रश्न भेजा जा रहा है।" if settings.language == "Hindi" else "Your Study Profile is ready. Sending the first question.")

            service = context.application.bot_data.get("quiz_service")
            question = await service.send_quiz(query.message.chat.id, force=True) if service else None
            await query.edit_message_text(
                completed_profile_text(
                    user.display_name, settings.language, settings.state, user.exam_preparation, settings.subjects
                ),
                reply_markup=private_quick_actions_keyboard(settings.language), parse_mode="Markdown",
            )
            if question is None and service is not None:
                fallback = (
                    "⚠️ पहला practice question अभी उपलब्ध नहीं हो सका। अगली कोशिश configured schedule के अनुसार होगी।"
                    if settings.language == "Hindi"
                    else "⚠️ The first practice question could not be delivered yet. The scheduler will retry at the configured interval."
                )
                await context.bot.send_message(query.message.chat.id, fallback)
            return

        if action == "finish":
            user = await repo.update_user_onboarding(query.from_user.id, completed=True)
            settings = await repo.update_settings(query.message.chat.id, quiz_active=True, last_quiz_at=None)
            await repo.commit()
            await query.answer("तैयारी शुरू हो गई है!" if settings.language == "Hindi" else "Your practice has started!")
            start_note = "\n\nआपका निजी अभ्यास शुरू हो गया है। पहला प्रश्न जल्द मिलेगा।" if settings.language == "Hindi" else "\n\nYour private practice is active. The first question will arrive shortly."
            await query.edit_message_text(
                confirmation_text(user.display_name, settings.language, settings.state, user.exam_preparation, settings.subjects) + start_note,
                reply_markup=confirmation_keyboard(settings.language), parse_mode="Markdown",
            )
            return

    await query.answer("This step is unavailable. Please restart with /start.", show_alert=True)


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None or not query.data.startswith("menu:"):
        return
    if query.message.chat.type != "private":
        await query.answer("This control is available only in private chat.", show_alert=True)
        return
    if query.data == "menu:settings":
        from bot.handlers.dm import open_dm_settings_from_callback
        await open_dm_settings_from_callback(query, context)
        return
    if query.data != "menu:help":
        await query.answer("Use /start to configure your study profile.", show_alert=True)
        return

    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        settings = await repo.ensure_group(query.message.chat.id, query.from_user.full_name or "Private Study", "private")
        await repo.commit()
    await query.answer()
    await context.bot.send_message(chat_id=query.message.chat.id, text=private_help_text(settings.language), parse_mode="Markdown")


async def help_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run common command actions directly from the inline Help dashboard."""
    query = update.callback_query
    if query is None or query.data is None or query.message is None or not query.data.startswith("hact:"):
        return
    action = query.data.split(":", 1)[1]
    chat_type = query.message.chat.type

    from bot.handlers import admin, dm, group_setup, user

    if chat_type == "private":
        if action == "dmsettings":
            await dm.open_dm_settings_from_callback(query, context)
            return
        if action == "dmstart":
            await query.answer("निजी क्विज़ शुरू किए जा रहे हैं…")
            await dm.dmstart_command(update, context)
            return
        if action == "dmstop":
            await query.answer("निजी क्विज़ रोके जा रहे हैं…")
            await dm.dmstop_command(update, context)
            return
        if action == "profile":
            await query.answer()
            await user.profile_command(update, context)
            return
        if action == "subjects":
            await query.answer()
            await user.subjects_command(update, context)
            return
        if action == "rules":
            await query.answer()
            await user.rules_command(update, context)
            return
        await query.answer("यह विकल्प निजी चैट में उपलब्ध नहीं है।", show_alert=True)
        return

    if chat_type not in {"group", "supergroup"}:
        await query.answer("यह विकल्प यहाँ उपलब्ध नहीं है।", show_alert=True)
        return
    if action == "help":
        database = context.application.bot_data["database"]
        async with database.session_factory() as session:
            settings = await Repository(session).get_settings(query.message.chat.id)
        language = settings.language if settings else "Hindi"
        await query.answer()
        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text=group_help_text(language),
            parse_mode="Markdown",
        )
        return
    if action == "gsettings":
        await group_setup.open_group_settings_from_callback(query, context)
        return
    if action == "startquiz":
        await query.answer("ग्रुप क्विज़ शुरू किए जा रहे हैं…")
        await admin.startquiz_command(update, context)
        return
    if action == "stopquiz":
        await query.answer("ग्रुप क्विज़ रोके जा रहे हैं…")
        await admin.stopquiz_command(update, context)
        return
    if action == "groupstats":
        await query.answer()
        await admin.groupstats_command(update, context)
        return
    if action == "profile":
        await query.answer()
        await user.profile_command(update, context)
        return
    if action == "leaderboard":
        await query.answer()
        await user.leaderboard_command(update, context)
        return
    if action == "subjects":
        await query.answer()
        await user.subjects_command(update, context)
        return
    await query.answer("यह विकल्प उपलब्ध नहीं है।", show_alert=True)


async def mock_test_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Register one learner in a lobby before its synchronized mock test starts."""
    query = update.callback_query
    if query is None or query.data is None or not query.data.startswith("mock:join:"):
        return
    try:
        mock_id = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        await query.answer("This mock-test link is invalid.", show_alert=True)
        return
    database = context.application.bot_data["database"]
    try:
        async with database.session_factory() as session:
            repo = Repository(session)
            mock = await repo.get_mock_test(mock_id)
            if mock is None or mock.status != "lobby":
                await query.answer("This mock-test lobby is no longer open.", show_alert=True)
                return
            settings = await repo.get_settings(mock.group_id)
            ui_language = settings.language if settings is not None else "Hindi"
            await repo.upsert_user(query.from_user.id, query.from_user.username, query.from_user.full_name)
            joined = await repo.join_mock_test(mock_id, query.from_user.id)
            await repo.commit()
    except OperationalError as exc:
        logger.warning("Mock lobby join database error for %s: %s", mock_id, exc)
        await query.answer("Database busy है। कृपया 2 seconds बाद फिर Join दबाएँ।", show_alert=True)
        return
    service: QuizService = context.application.bot_data["quiz_service"]
    if joined >= 2:
        await query.answer(f"Joined successfully. Participants: {joined}. Starting the mock test now.", show_alert=True)
        try:
            await query.edit_message_text(
                f"✅ *Lobby complete*\n\n{joined} participants joined. Starting the timed mock test now…",
                parse_mode="Markdown",
            )
        except TelegramError:
            pass
        await service.start_mock_test(mock_id)
        return
    await query.answer(f"Joined successfully. Participants: {joined}. One more participant is required.", show_alert=True)
    try:
        await query.edit_message_text(
            service.mock_lobby_text(
                mock.title, mock.question_count, mock.round_seconds, joined, ui_language=ui_language
            ),
            reply_markup=service.mock_lobby_keyboard(mock_id), parse_mode="Markdown",
        )
    except TelegramError:
        pass

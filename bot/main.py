"""Production entry point for the Telegram Study MCQ Quiz Bot."""
from __future__ import annotations

import logging

from telegram import BotCommand, BotCommandScopeDefault, Update
from telegram.error import NetworkError, RetryAfter, TimedOut
from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, ChatMemberHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, PollAnswerHandler, filters

from bot.config import get_settings
from bot.database.database import Database
from bot.handlers import admin, bulk_import, callbacks, delivery, dm, group_setup, official_quiz, source, start, user
from bot.services.ai_generator import AIQuestionGenerator
from bot.services.delivery import DeliveryService
from bot.services.ocr_health import check_ocr_environment
from bot.services.official_quiz import OfficialQuizService
from bot.services.quiz import QuizService
from bot.services.scheduler import SchedulerService
from bot.services.scoring import ScoringService
from bot.utils.logger import configure_logging
from bot.web import mark_ready, mark_stopping, start_health_server

logger = logging.getLogger(__name__)


async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.poll_answer:
        await context.application.bot_data["scoring_service"].process_poll_answer(update.poll_answer)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    if isinstance(error, (NetworkError, TimedOut, RetryAfter)):
        logger.warning("Transient Telegram delivery error; suppressing generic user error: %s", error)
        return
    logger.exception("Unhandled bot update error", exc_info=error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("अस्थायी समस्या आई थी। कृपया command या button दोबारा दबाएँ।")
        except Exception:
            logger.exception("Could not notify user about handler error")


async def post_init(application: Application) -> None:
    settings = get_settings()
    check_ocr_environment(settings.source_ocr_enabled, logger=logger)
    database: Database = application.bot_data["database"]
    await database.create_schema()
    await application.bot.set_my_commands([
        BotCommand("start", "शुरू करें / Start"),
        BotCommand("help", "Help & Commands"),
        BotCommand("profile", "अपना Profile देखें"),
        BotCommand("rules", "Rules & Rewards"),
        BotCommand("settings", "Settings खोलें"),
        BotCommand("setlanguage", "भाषा बदलें"),
        BotCommand("setstate", "State चुनें"),
        BotCommand("setsubjects", "Subjects चुनें"),
        BotCommand("setinterval", "Quiz Interval सेट करें"),
        BotCommand("startquiz", "Quiz शुरू करें"),
        BotCommand("stopquiz", "Quiz रोकें"),
        BotCommand("mocktest", "Mock Test"),
        BotCommand("leaderboard", "Leaderboard"),
        BotCommand("rank", "अपनी Rank देखें"),
        BotCommand("daily", "Daily Ranking"),
        BotCommand("weekly", "Weekly Ranking"),
        BotCommand("monthly", "Monthly Ranking"),
        BotCommand("stats", "Group Statistics"),
        BotCommand("subjects", "Available Subjects"),
        BotCommand("groupstats", "Group Performance"),
        BotCommand("quiz", "Official Quiz Lobby"),
        BotCommand("createquiz", "Create Official Quiz"),
        BotCommand("addquestion", "Validated Question जोड़ें"),
        BotCommand("removequestion", "Question हटाएं"),
        BotCommand("sources", "Indexed Source Documents"),
        BotCommand("bulksend", "Import MCQ Polls"),
        BotCommand("broadcast", "Broadcast Content"),
        BotCommand("deliver", "Targeted Delivery"),
        BotCommand("targeted", "Targeted Delivery"),
        BotCommand("botreport", "Diagnostic Report (Admin)"),
        BotCommand("status", "Bot Status (Admin only)"),
        BotCommand("questiondelivery", "Global Questions ON/OFF"),
        BotCommand("deliveryon", "Resume Questions (Admin)"),
        BotCommand("deliveryoff", "Pause Questions (Admin)"),
    ], scope=BotCommandScopeDefault())
    await application.bot_data["scheduler"].start()
    mark_ready()
    logger.info("Database initialized, Telegram command menu registered, scheduler started, and Flask health endpoint ready")


async def post_shutdown(application: Application) -> None:
    mark_stopping()
    scheduler: SchedulerService = application.bot_data["scheduler"]
    await scheduler.stop()
    await application.bot_data["generator"].close()
    await application.bot_data["database"].dispose()
    logger.info("Bot shutdown completed")


def build_application() -> Application:
    settings = get_settings()
    configure_logging(
        settings.log_level,
        [
            settings.bot_token, settings.ai_api_key, settings.news_api_key or "",
            settings.gemini_api_key or "", settings.groq_api_key or "", settings.mistral_api_key or "",
        ],
        log_file=settings.log_file,
    )
    database = Database(settings.database_url)
    application = (
        ApplicationBuilder()
        .token(settings.bot_token)
        .concurrent_updates(True)
        .get_updates_connect_timeout(10)
        .get_updates_read_timeout(15)
        .get_updates_write_timeout(10)
        .get_updates_pool_timeout(10)
        .connect_timeout(10)
        .read_timeout(15)
        .write_timeout(10)
        .pool_timeout(10)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    generator = AIQuestionGenerator(settings)
    quiz_service = QuizService(application.bot, database, settings, generator)
    official_quiz_service = OfficialQuizService(application.bot, database, quiz_service)
    scheduler = SchedulerService(database, quiz_service, settings, official_quiz_service)
    scoring_service = ScoringService(database, application.bot)
    delivery_service = DeliveryService(application.bot, database)
    application.bot_data.update(
        database=database, generator=generator, quiz_service=quiz_service,
        official_quiz_service=official_quiz_service, scheduler=scheduler,
        scoring_service=scoring_service, delivery_service=delivery_service,
    )

    application.add_handler(CommandHandler("start", start.start_command))
    application.add_handler(CommandHandler("help", start.help_command))
    application.add_handler(CommandHandler("setting", group_setup.settings_command))
    application.add_handler(CommandHandler("settings", group_setup.settings_command))
    application.add_handler(CommandHandler("profile", user.profile_command))
    application.add_handler(CommandHandler("score", user.score_command))
    application.add_handler(CommandHandler("rules", user.rules_command))
    application.add_handler(CommandHandler("stats", user.stats_command))
    application.add_handler(CommandHandler("rank", user.rank_command))
    application.add_handler(CommandHandler("leaderboard", user.leaderboard_command))
    application.add_handler(CommandHandler("daily", user.daily_command))
    application.add_handler(CommandHandler("weekly", user.weekly_command))
    application.add_handler(CommandHandler("monthly", user.monthly_command))
    application.add_handler(CommandHandler("subjects", user.subjects_command))
    application.add_handler(CommandHandler("setlanguage", dm.setlanguage_command))
    application.add_handler(CommandHandler("dmlanguage", dm.setlanguage_command))
    application.add_handler(CommandHandler("dmstart", dm.dmstart_command))
    application.add_handler(CommandHandler("dmstop", dm.dmstop_command))
    application.add_handler(CommandHandler("dminterval", dm.dminterval_command))
    application.add_handler(CommandHandler("dmsettings", dm.dmsettings_command))
    application.add_handler(CommandHandler("mocktest", admin.mocktest_admin_command))
    application.add_handler(official_quiz.conversation_handler())
    application.add_handler(CommandHandler("quiz", official_quiz.launch_quiz_command))
    application.add_handler(CommandHandler("cancelquiz", official_quiz.cancelquiz))
    application.add_handler(CommandHandler("stopmocktest", admin.stopmocktest_admin_command))
    application.add_handler(CommandHandler("deliver", delivery.delivery_command))
    application.add_handler(CommandHandler("targeted", delivery.delivery_command))
    application.add_handler(CommandHandler("broadcast", delivery.delivery_command))
    application.add_handler(CommandHandler("sources", source.sources_command))
    application.add_handler(CommandHandler("bulksend", bulk_import.bulk_send_command))

    application.add_handler(CommandHandler("setstate", admin.setstate_command))
    application.add_handler(CommandHandler("setsubject", admin.setsubject_command))
    application.add_handler(CommandHandler("setsubjects", admin.setsubject_command))
    application.add_handler(CommandHandler("setxp", admin.setxp_command))
    application.add_handler(CommandHandler("setinterval", admin.setinterval_command))
    application.add_handler(CommandHandler("startquiz", admin.startquiz_command))
    application.add_handler(CommandHandler("stopquiz", admin.stopquiz_command))
    application.add_handler(CommandHandler("setmode", admin.setmode_command))
    application.add_handler(CommandHandler("addquestion", admin.addquestion_command))
    application.add_handler(CommandHandler("removequestion", admin.removequestion_command))
    application.add_handler(CommandHandler("groupstats", admin.groupstats_command))
    application.add_handler(CommandHandler("botreport", admin.botreport_command))
    application.add_handler(CommandHandler("status", admin.status_command))
    application.add_handler(CommandHandler("questiondelivery", admin.questiondelivery_command))
    application.add_handler(CommandHandler("deliveryon", admin.questiondelivery_on_command))
    application.add_handler(CommandHandler("deliveryoff", admin.questiondelivery_off_command))
    application.add_handler(ChatMemberHandler(group_setup.group_welcome_on_join, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(CallbackQueryHandler(group_setup.settings_callback, pattern=r"^gset:"))
    application.add_handler(CallbackQueryHandler(dm.dm_settings_callback, pattern=r"^dset:"))
    application.add_handler(CallbackQueryHandler(callbacks.explanation_callback, pattern=r"^explain:"))
    application.add_handler(CallbackQueryHandler(callbacks.mock_test_callback, pattern=r"^mock:"))
    application.add_handler(CallbackQueryHandler(official_quiz.official_callback, pattern=r"^official:"))
    application.add_handler(CallbackQueryHandler(delivery.delivery_callback, pattern=r"^deliver:"))
    application.add_handler(CallbackQueryHandler(source.source_callback, pattern=r"^src:"))
    application.add_handler(CallbackQueryHandler(bulk_import.bulk_callback, pattern=r"^bulk:"))
    application.add_handler(CallbackQueryHandler(callbacks.help_action_callback, pattern=r"^hact:"))
    application.add_handler(CallbackQueryHandler(callbacks.onboarding_callback, pattern=r"^onb:"))
    application.add_handler(CallbackQueryHandler(callbacks.menu_callback, pattern=r"^menu:"))
    application.add_handler(CallbackQueryHandler(user.leaderboard_scope_callback, pattern=r"^lb:"))
    application.add_handler(PollAnswerHandler(poll_answer_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, source.source_document_handler))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, delivery.delivery_content_handler))
    application.add_error_handler(error_handler)
    return application


def main() -> None:
    start_health_server()
    application = build_application()
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()

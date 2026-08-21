from bot.config import get_settings


def test_application_builds_with_environment(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123456789:abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("AI_API_KEY", "test-ai-key-123")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    get_settings.cache_clear()
    from bot.main import build_application

    application = build_application()
    assert application.bot_data["database"] is not None
    assert application.bot_data["quiz_service"] is not None
    assert application.bot_data["scoring_service"] is not None
    assert application.handlers
    get_settings.cache_clear()

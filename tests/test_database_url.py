import pytest

from bot.config import get_settings


@pytest.mark.parametrize(
    ("raw_url", "expected_url"),
    [
        (
            "postgresql://user:password@render-host:5432/study_mcq_bot?sslmode=require",
            "postgresql+asyncpg://user:password@render-host:5432/study_mcq_bot?ssl=require",
        ),
        (
            "postgres://user:password@render-host:5432/study_mcq_bot?sslmode=require&application_name=gsi",
            "postgresql+asyncpg://user:password@render-host:5432/study_mcq_bot?application_name=gsi&ssl=require",
        ),
        (
            "postgresql://user:password@render-host:5432/study_mcq_bot?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://user:password@render-host:5432/study_mcq_bot?ssl=require",
        ),
    ],
)
def test_render_postgres_url_translates_sslmode(monkeypatch: pytest.MonkeyPatch, raw_url: str, expected_url: str) -> None:
    monkeypatch.setenv("BOT_TOKEN", "12345678901234567890")
    monkeypatch.setenv("AI_API_KEY", "placeholder-ai-key")
    monkeypatch.setenv("DATABASE_URL", raw_url)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.database_url == expected_url
        assert "sslmode" not in settings.database_url
        assert "channel_binding" not in settings.database_url
    finally:
        get_settings.cache_clear()


def test_sqlite_url_behavior_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "12345678901234567890")
    monkeypatch.setenv("AI_API_KEY", "placeholder-ai-key")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./study_mcq_bot.db")
    get_settings.cache_clear()
    try:
        assert get_settings().database_url == "sqlite+aiosqlite:///./study_mcq_bot.db"
    finally:
        get_settings.cache_clear()

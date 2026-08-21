"""Async database setup and lifecycle helpers."""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.database.models import Base


class Database:
    def __init__(self, database_url: str) -> None:
        engine_kwargs = {"pool_pre_ping": True, "future": True}
        if database_url.startswith("sqlite+"):
            engine_kwargs["connect_args"] = {"timeout": 30}
        self.engine = create_async_engine(database_url, **engine_kwargs)
        if database_url.startswith("sqlite+"):
            @event.listens_for(self.engine.sync_engine, "connect")
            def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await self._add_missing_columns(connection)

    @staticmethod
    async def _add_missing_columns(connection) -> None:
        """Apply additive migrations for existing local and PostgreSQL databases."""
        async def has_column(table: str, column: str) -> bool:
            columns = await connection.run_sync(lambda sync_conn: inspect(sync_conn).get_columns(table))
            return any(item["name"] == column for item in columns)

        migrations = [
            ("users", "preferred_language", "VARCHAR(16) NOT NULL DEFAULT 'Hindi'"),
            ("users", "exam_preparation", "VARCHAR(32)"),
            ("users", "onboarding_completed", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("users", "honor_tag", "VARCHAR(64)"),
            ("users", "gsi_wins", "INTEGER NOT NULL DEFAULT 0"),
            ("users", "gsi_achievements", "JSON NOT NULL DEFAULT '[]'"),
            ("users", "star_count", "INTEGER NOT NULL DEFAULT 0"),
            ("users", "star_title", "VARCHAR(64)"),
            ("group_settings", "language", "VARCHAR(16) NOT NULL DEFAULT 'Hindi'"),
            ("group_settings", "topic_rotation_state", "JSON NOT NULL DEFAULT '{}'"),
            ("group_settings", "source_mode", "VARCHAR(24) NOT NULL DEFAULT 'ai'"),
            ("group_settings", "bot_is_admin", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("group_settings", "bot_joined_at", "DATETIME"),
            ("group_settings", "admin_reminder_stage", "INTEGER NOT NULL DEFAULT 0"),
            ("group_settings", "admin_reminder_sent_at", "DATETIME"),
            ("questions", "source_document_id", "INTEGER"),
            ("questions", "source_title", "VARCHAR(256)"),
            ("questions", "source_page_start", "INTEGER"),
            ("questions", "source_page_end", "INTEGER"),
            ("questions", "language", "VARCHAR(16) NOT NULL DEFAULT 'Hindi'"),
            ("questions", "is_active", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("mock_tests", "lobby_closes_at", "DATETIME"),
            ("mock_tests", "round_seconds", "INTEGER NOT NULL DEFAULT 30"),
            ("mock_tests", "current_question_number", "INTEGER NOT NULL DEFAULT 0"),
            ("mock_tests", "round_ends_at", "DATETIME"),
            ("mock_tests", "current_poll_id", "VARCHAR(128)"),
            ("mock_tests", "lobby_message_id", "INTEGER"),
            ("quiz_history", "official_quiz_id", "INTEGER"),
            ("quiz_history", "official_question_number", "INTEGER"),
        ]
        for table, column, definition in migrations:
            if not await has_column(table, column):
                await connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        await connection.execute(text(
            "UPDATE group_settings SET rotation_enabled = TRUE, explanation_enabled = TRUE"
        ))
        await connection.execute(text(
            "UPDATE group_settings SET source_mode = 'ai' "
            "WHERE source_mode IS NULL OR source_mode NOT IN ('ai', 'source')"
        ))
        await connection.execute(text(
            "UPDATE group_settings SET admin_reminder_stage = 0 "
            "WHERE admin_reminder_stage IS NULL"
        ))
        # Keep historical quiz references intact, but retire deprecated or
        # disallowed question types from future delivery.
        await connection.execute(text(
            "UPDATE questions SET is_active = FALSE "
            "WHERE question_type = 'Application-based' "
            "OR (question_type = 'Assertion-Reason' AND subject <> 'Reasoning')"
        ))
        await connection.execute(text("UPDATE users SET honor_tag = '⟦𝙂𝙎𝙄✦⟧' WHERE honor_tag = '⟦ GSI ⟧'"))
        await connection.execute(text("UPDATE group_settings SET interval_minutes = 10 WHERE interval_minutes < 10"))
        # Difficulty remains as a historical column, but all current delivery
        # and newly generated questions use the single unified Exam level.
        await connection.execute(text("UPDATE group_settings SET difficulty = 'Exam' WHERE difficulty <> 'Exam' OR difficulty IS NULL"))
        await connection.execute(text("UPDATE questions SET difficulty = 'Exam' WHERE is_active = TRUE"))

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()

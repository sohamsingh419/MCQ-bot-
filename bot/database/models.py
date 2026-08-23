"""Database schema for the study quiz bot."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str] = mapped_column(String(256), default="Student", nullable=False)
    total_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct_answers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wrong_answers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    best_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    preferred_language: Mapped[str] = mapped_column(String(16), default="Hindi", nullable=False)
    exam_preparation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    honor_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gsi_wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gsi_achievements: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    star_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    star_title: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Group(TimestampMixin, Base):
    __tablename__ = "groups"

    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(256), default="Study Group", nullable=False)
    chat_type: Mapped[str] = mapped_column(String(32), default="group", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    settings: Mapped["GroupSettings"] = relationship(back_populates="group", uselist=False, cascade="all, delete-orphan")


class GroupSettings(TimestampMixin, Base):
    __tablename__ = "group_settings"

    group_id: Mapped[int] = mapped_column(ForeignKey("groups.telegram_chat_id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[str] = mapped_column(String(64), default="General", nullable=False)
    subjects: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # Retained for database compatibility; the bot now uses one unified exam level.
    difficulty: Mapped[str] = mapped_column(String(16), default="Exam", nullable=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    rotation_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    explanation_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    quiz_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_rotation_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    topic_rotation_state: Mapped[dict[str, int]] = mapped_column(JSON, default=dict, nullable=False)
    last_quiz_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    xp_map: Mapped[dict[str, int]] = mapped_column(JSON, default=dict, nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="Hindi", nullable=False)
    # Alternates successful deliveries between AI-generated and imported source questions.
    source_mode: Mapped[str] = mapped_column(String(24), default="ai", nullable=False)
    # Bot-admin readiness is tracked for group onboarding and delayed reminders.
    bot_is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    bot_joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    admin_reminder_stage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    admin_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    group: Mapped[Group] = relationship(back_populates="settings")


class BotControl(TimestampMixin, Base):
    """Singleton bot-wide controls managed by configured bot administrators."""
    __tablename__ = "bot_control"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    question_delivery_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Question(TimestampMixin, Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    options: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    correct_option: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    key_point: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(64), nullable=False)
    topic: Mapped[str] = mapped_column(String(256), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    question_type: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="Hindi", nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="ai", nullable=False)
    source_group_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True)
    source_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("ix_questions_scope", "state", "subject", "difficulty"),
    )


class SourceDocument(TimestampMixin, Base):
    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_file_id: Mapped[str] = mapped_column(String(256), nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(64), nullable=True)
    class_exam: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="awaiting_metadata", nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_source_documents_scope_status", "state", "subject", "status"),
    )


class SourceChunk(TimestampMixin, Base):
    __tablename__ = "source_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(64), nullable=False)
    topic: Mapped[str] = mapped_column(String(256), default="Unclassified", nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    __table_args__ = (
        Index("ix_source_chunks_scope_topic", "state", "subject", "topic"),
    )


class QuizHistory(TimestampMixin, Base):
    __tablename__ = "quiz_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.telegram_chat_id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False)
    telegram_poll_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    quiz_kind: Mapped[str] = mapped_column(String(24), default="automatic", nullable=False)
    mock_test_id: Mapped[int | None] = mapped_column(ForeignKey("mock_tests.id", ondelete="SET NULL"), nullable=True)
    official_quiz_id: Mapped[int | None] = mapped_column(ForeignKey("official_quizzes.id", ondelete="SET NULL"), nullable=True)
    official_question_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    explanation_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (Index("ix_quiz_history_group_open", "group_id", "opened_at"),)


class UserAnswer(TimestampMixin, Base):
    __tablename__ = "user_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.telegram_chat_id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False)
    poll_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_user_id", ondelete="CASCADE"), nullable=False)
    selected_option: Mapped[int] = mapped_column(Integer, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    points_awarded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("poll_id", "user_id", name="uq_user_answers_poll_user"),
        Index("ix_user_answers_group_created", "group_id", "created_at"),
        Index("ix_user_answers_user_created", "user_id", "created_at"),
    )


class LeaderboardSnapshot(TimestampMixin, Base):
    """Optional durable snapshot record for reporting/auditing derived leaderboards."""
    __tablename__ = "leaderboards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.telegram_chat_id", ondelete="CASCADE"), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_user_id", ondelete="CASCADE"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, nullable=False)
    correct: Mapped[int] = mapped_column(Integer, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("group_id", "period", "user_id", "captured_at", name="uq_leaderboard_snapshot"),
        Index("ix_leaderboards_group_period", "group_id", "period", "captured_at"),
    )


class DailyChallenge(TimestampMixin, Base):
    __tablename__ = "daily_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.telegram_chat_id", ondelete="CASCADE"), nullable=False)
    challenge_date: Mapped[date] = mapped_column(Date, nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False)
    bonus_xp: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    poll_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (UniqueConstraint("group_id", "challenge_date", name="uq_daily_challenge_group_date"),)


class OfficialQuizDraft(TimestampMixin, Base):
    __tablename__ = "official_quiz_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    step: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class OfficialQuiz(TimestampMixin, Base):
    __tablename__ = "official_quizzes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    quiz_type: Mapped[str] = mapped_column(String(16), nullable=False)  # gsi | star
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    rules: Mapped[str] = mapped_column(Text, default="", nullable=False)
    month_key: Mapped[str] = mapped_column(String(7), nullable=False)
    config_group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    play_group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_group_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    round_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    question_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="lobby", nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    countdown_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_question_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    round_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_poll_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    halfway_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    winner_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        Index("ix_official_quizzes_status", "status", "play_group_id"),
        Index("ix_official_quizzes_type_month", "quiz_type", "month_key"),
    )


class OfficialQuizParticipant(TimestampMixin, Base):
    __tablename__ = "official_quiz_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("official_quizzes.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_user_id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("quiz_id", "user_id", name="uq_official_quiz_participant"),
        Index("ix_official_quiz_participants_quiz", "quiz_id"),
    )


class OfficialQuizResult(TimestampMixin, Base):
    __tablename__ = "official_quiz_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("official_quizzes.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_user_id", ondelete="CASCADE"), nullable=False)
    correct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wrong: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    percentage: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    award: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (UniqueConstraint("quiz_id", "user_id", name="uq_official_quiz_result"),)


class MockTest(TimestampMixin, Base):
    __tablename__ = "mock_tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.telegram_chat_id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    subjects: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="lobby", nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lobby_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    round_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    current_question_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    round_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_poll_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lobby_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (Index("ix_mock_tests_group_status", "group_id", "status"),)


class MockTestParticipant(TimestampMixin, Base):
    __tablename__ = "mock_test_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mock_test_id: Mapped[int] = mapped_column(ForeignKey("mock_tests.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_user_id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("mock_test_id", "user_id", name="uq_mock_participant_test_user"),
        Index("ix_mock_participants_test", "mock_test_id"),
    )


class MockTestResult(TimestampMixin, Base):
    __tablename__ = "mock_test_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mock_test_id: Mapped[int] = mapped_column(ForeignKey("mock_tests.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_user_id", ondelete="CASCADE"), nullable=False)
    correct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wrong: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    percentage: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (UniqueConstraint("mock_test_id", "user_id", name="uq_mock_result_test_user"),)


class DeliveryCampaign(TimestampMixin, Base):
    """Auditable admin-created targeted delivery or broadcast campaign."""
    __tablename__ = "delivery_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # targeted | broadcast
    audience: Mapped[str] = mapped_column(String(16), nullable=False)  # users | groups | both
    state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_type: Mapped[str] = mapped_column(String(16), nullable=False)  # text | poll | video
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class DeliveryReceipt(TimestampMixin, Base):
    """One durable receipt per campaign and destination chat to prevent duplicate sends."""
    __tablename__ = "delivery_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("delivery_campaigns.id", ondelete="CASCADE"), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("campaign_id", "chat_id", name="uq_delivery_receipt_campaign_chat"),
        Index("ix_delivery_receipts_campaign_status", "campaign_id", "status"),
    )

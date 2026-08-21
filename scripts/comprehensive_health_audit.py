from __future__ import annotations

import asyncio
from collections import Counter
from sqlalchemy import func, select

from bot.config import get_settings
from bot.database.database import Database
from bot.database.models import GroupSettings, MockTest, Question, SourceChunk, SourceDocument


async def main() -> None:
    settings = get_settings()
    print("=== CONFIG ===")
    print({
        "database": "configured",
        "gemini_key": bool(settings.gemini_api_key),
        "groq_key": bool(settings.groq_api_key),
        "mistral_key": bool(settings.mistral_api_key),
        "validator_enabled": settings.validator_enabled,
        "validator_threshold": settings.validator_confidence_threshold,
        "interval_allowed": sorted({10, 15, 20, 30, 60}),
        "question_pool": settings.question_pool_enabled,
        "pool_target": settings.question_pool_target,
        "ai_concurrency": settings.ai_max_concurrent_requests,
    })

    db = Database(settings.database_url)
    async with db.session_factory() as session:
        groups = list((await session.execute(select(GroupSettings))).scalars())
        questions = list((await session.execute(select(Question))).scalars())
        docs = list((await session.execute(select(SourceDocument))).scalars())
        chunks_count = int((await session.scalar(select(func.count()).select_from(SourceChunk))) or 0)
        active_mocks = list((await session.execute(select(MockTest).where(MockTest.status.in_(["lobby", "running"])))) .scalars())

        print("=== GROUP SETTINGS ===")
        intervals = [int(item.interval_minutes) for item in groups]
        print({
            "total_settings": len(groups),
            "invalid_below_10": sum(value < 10 for value in intervals),
            "interval_distribution": dict(Counter(intervals)),
            "active_quiz_settings": sum(bool(item.quiz_active) for item in groups),
        })

        active_questions = [item for item in questions if getattr(item, "is_active", True)]
        print("=== QUESTIONS ===")
        print({
            "total_historical": len(questions),
            "active": len(active_questions),
            "active_application_based": sum(item.question_type == "Application-based" for item in active_questions),
            "active_non_reasoning_ar": sum(item.question_type == "Assertion-Reason" and item.subject != "Reasoning" for item in active_questions),
            "source_questions": sum(item.source == "source" for item in active_questions),
            "ai_questions": sum(item.source in {"ai", "admin"} for item in active_questions),
        })

        print("=== SOURCES ===")
        print({
            "documents": len(docs),
            "ready_documents": sum(item.status == "ready" for item in docs),
            "failed_documents": sum(item.status == "failed" for item in docs),
            "chunks": chunks_count,
            "ready_titles": [item.title for item in docs if item.status == "ready"][:10],
        })

        print("=== MOCKS ===")
        print({
            "active_count": len(active_mocks),
            "active": [{"id": item.id, "group_id": item.group_id, "status": item.status, "round": item.current_question_number, "count": item.question_count} for item in active_mocks],
        })

    await db.dispose()


if __name__ == "__main__":
    asyncio.run(main())

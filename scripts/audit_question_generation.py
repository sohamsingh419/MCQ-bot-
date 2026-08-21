from __future__ import annotations

import asyncio
from collections import Counter

from sqlalchemy import func, select

from bot.config import get_settings
from bot.database.database import Database
from bot.database.models import Question, QuizHistory, SourceChunk, SourceDocument


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    async with database.session_factory() as session:
        total = await session.scalar(select(func.count(Question.id)))
        source_total = await session.scalar(select(func.count(Question.id)).where(Question.source_document_id.is_not(None)))
        source_label_total = await session.scalar(select(func.count(Question.id)).where(Question.source == "pdf"))
        print(f"TOTAL_QUESTIONS={total}")
        print(f"QUESTIONS_WITH_SOURCE_DOCUMENT={source_total}")
        print(f"QUESTIONS_SOURCE_LABEL_PDF={source_label_total}")
        print("QUESTION_COUNTS_BY_SOURCE")
        for source, count in (await session.execute(select(Question.source, func.count(Question.id)).group_by(Question.source))).all():
            print(f"  {source!r}: {count}")
        print("QUESTION_COUNTS_BY_DOCUMENT")
        rows = (await session.execute(
            select(Question.source_document_id, Question.source_title, func.count(Question.id))
            .where(Question.source_document_id.is_not(None))
            .group_by(Question.source_document_id, Question.source_title)
            .order_by(func.count(Question.id).desc())
        )).all()
        for document_id, title, count in rows:
            print(f"  document_id={document_id} title={title!r} count={count}")
        print("RECENT_QUESTIONS")
        recent = list((await session.execute(select(Question).order_by(Question.created_at.desc()).limit(20))).scalars())
        for question in recent:
            print({
                "id": question.id,
                "created_at": str(question.created_at),
                "state": question.state,
                "subject": question.subject,
                "topic": question.topic,
                "source": question.source,
                "source_document_id": question.source_document_id,
                "source_title": question.source_title,
                "pages": (question.source_page_start, question.source_page_end),
                "ai_model": question.ai_model,
                "used_count": question.used_count,
            })
        print("QUIZ_HISTORY_COUNTS")
        for group_id, count in (await session.execute(select(QuizHistory.group_id, func.count(QuizHistory.id)).group_by(QuizHistory.group_id))).all():
            print(f"  group_id={group_id} count={count}")
        print("SOURCE_CHUNK_COUNTS")
        for document_id, subject, count in (await session.execute(select(SourceChunk.document_id, SourceChunk.subject, func.count(SourceChunk.id)).group_by(SourceChunk.document_id, SourceChunk.subject))).all():
            print(f"  document_id={document_id} subject={subject!r} chunks={count}")
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())


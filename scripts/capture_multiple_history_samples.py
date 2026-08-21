from __future__ import annotations

import asyncio
import json

from bot.config import get_settings
from bot.database.database import Database
from bot.database.repositories import Repository
from bot.services.ai_generator import AIQuestionGenerator
from bot.services.quiz import QuizService, _topic_relevant_source_chunks

GROUP_ID = -1003799884627
ATTEMPTS = 5


def compact(payload: dict) -> dict:
    return {key: payload.get(key) for key in (
        "question", "options", "correct_option", "explanation", "key_point",
        "subject", "topic", "difficulty", "question_type", "language",
    )}


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    generator = AIQuestionGenerator(settings)
    try:
        async with database.session_factory() as session:
            repo = Repository(session)
            group_settings = await repo.get_settings(GROUP_ID)
            subject = "State History"
            topic = QuizService.topic_for_next_quiz(group_settings, subject)
            chunks = await repo.source_chunks_for_scope(state=group_settings.state, subject=subject, topic=topic, limit=3)
            if not chunks:
                candidates = await repo.source_chunks_for_scope(state=group_settings.state, subject=subject, limit=50)
                chunks = _topic_relevant_source_chunks(candidates, topic) or candidates[:3]
            source_context = "\n\n".join(
                f"[Source chunk, pages {chunk.page_start}-{chunk.page_end}]\n{chunk.text}" for chunk in chunks
            ) or None
            print(json.dumps({"state": group_settings.state, "subject": subject, "topic": topic, "chunks": [(c.page_start, c.page_end) for c in chunks]}, ensure_ascii=False))
            previous: list[str] = []
            for index in range(1, ATTEMPTS + 1):
                raw_payloads: list[dict] = []
                decisions: list[dict] = []
                original_request = generator._request
                original_validate = generator._validate_independently

                async def request_wrapper(prompt: str, _original=original_request, _raw=raw_payloads) -> dict:
                    payload = await _original(prompt)
                    _raw.append(dict(payload))
                    return payload

                async def validate_wrapper(question, source_context=None, _original=original_validate, _decisions=decisions):
                    decision = await _original(question, source_context)
                    _decisions.append({
                        "question": question.question,
                        "options": question.options,
                        "correct_option": question.correct_option,
                        "decision": getattr(decision, "__dict__", str(decision)),
                    })
                    return decision

                generator._request = request_wrapper
                generator._validate_independently = validate_wrapper
                try:
                    result = await generator.generate(
                        state=group_settings.state, subject=subject, topic=topic,
                        question_type="Conceptual",
                        language=group_settings.language, previous_questions=previous,
                        similarity_threshold=settings.question_similarity_threshold,
                        source_context=source_context,
                    )
                    print(json.dumps({"attempt": index, "accepted": True, "result": compact(result.__dict__), "validator_decisions": decisions}, ensure_ascii=False))
                    previous.append(result.question)
                except Exception as exc:
                    print(json.dumps({"attempt": index, "accepted": False, "error": type(exc).__name__, "message": str(exc), "raw_payloads": [compact(p) for p in raw_payloads], "validator_decisions": decisions}, ensure_ascii=False))
                finally:
                    generator._request = original_request
                    generator._validate_independently = original_validate
            await session.rollback()
    finally:
        await generator.close()
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())


from __future__ import annotations

import asyncio
import json

from bot.config import get_settings
from bot.database.database import Database
from bot.database.repositories import Repository
from bot.services.ai_generator import AIQuestionGenerator
from bot.services.quiz import QuizService, _topic_relevant_source_chunks

GROUP_ID = -1003799884627


def compact_payload(payload: dict) -> dict:
    return {key: payload.get(key) for key in (
        "question", "options", "correct_option", "explanation", "key_point",
        "subject", "topic", "difficulty", "question_type", "language",
    )}


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    generator = AIQuestionGenerator(settings)
    captured_payloads: list[dict] = []
    decisions: list[dict] = []
    original_request = generator._request
    original_validate = generator._validate_independently

    async def request_wrapper(prompt: str) -> dict:
        payload = await original_request(prompt)
        captured_payloads.append(dict(payload))
        return payload

    async def validate_wrapper(question, source_context=None):
        decision = await original_validate(question, source_context)
        decisions.append({
            "question": question.question,
            "options": question.options,
            "correct_option": question.correct_option,
            "source_context_supplied": bool(source_context),
            "decision": decision,
        })
        return decision

    generator._request = request_wrapper
    generator._validate_independently = validate_wrapper
    try:
        async with database.session_factory() as session:
            repo = Repository(session)
            group_settings = await repo.get_settings(GROUP_ID)
            subject = "State History"
            topic = QuizService.topic_for_next_quiz(group_settings, subject)
            chunks = await repo.source_chunks_for_scope(
                state=group_settings.state, subject=subject, topic=topic, limit=3
            )
            if not chunks:
                candidates = await repo.source_chunks_for_scope(
                    state=group_settings.state, subject=subject, limit=50
                )
                chunks = _topic_relevant_source_chunks(candidates, topic)
                if not chunks and candidates:
                    chunks = candidates[:3]
            source_context = "\n\n".join(
                f"[Source chunk, pages {chunk.page_start}-{chunk.page_end}]\n{chunk.text}" for chunk in chunks
            ) or None
            print(json.dumps({
                "state": group_settings.state,
                "subject": subject,
                "topic": topic,
                "source_chunks": [(chunk.chunk_index, chunk.page_start, chunk.page_end, chunk.topic) for chunk in chunks],
            }, ensure_ascii=False))
            try:
                result = await generator.generate(
                    state=group_settings.state,
                    subject=subject,
                    topic=topic,
                    question_type="Conceptual",
                    language=group_settings.language,
                    previous_questions=[],
                    similarity_threshold=settings.question_similarity_threshold,
                    source_context=source_context,
                )
                print(json.dumps({"FINAL_RESULT": compact_payload(result.__dict__)}, ensure_ascii=False))
            except Exception as exc:
                print(json.dumps({"FINAL_ERROR": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
            print("RAW_ATTEMPTS")
            for index, payload in enumerate(captured_payloads, 1):
                print(json.dumps({"attempt": index, "payload": compact_payload(payload)}, ensure_ascii=False))
            print("VALIDATOR_DECISIONS")
            for index, decision in enumerate(decisions, 1):
                item = dict(decision)
                item["decision"] = getattr(decision["decision"], "__dict__", str(decision["decision"]))
                print(json.dumps({"attempt": index, **item}, ensure_ascii=False))
            await session.rollback()
    finally:
        await generator.close()
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())


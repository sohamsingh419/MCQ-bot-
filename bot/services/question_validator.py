"""Validation for AI and admin-supplied MCQs before they can reach Telegram."""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from bot.config import VALID_DIFFICULTIES, VALID_LANGUAGES, VALID_QUESTION_TYPES, VALID_SUBJECTS


class QuestionValidationError(ValueError):
    pass


# Conservative limits keep every generated item readable in Telegram poll layouts.
POLL_QUESTION_MAX = 240
POLL_OPTION_MAX = 72


@dataclass(frozen=True)
class ValidQuestion:
    question: str
    options: list[str]
    correct_option: int
    explanation: str
    key_point: str
    subject: str
    topic: str
    difficulty: str
    question_type: str
    language: str


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", value.casefold())).strip()


_SOURCE_STOPWORDS = {
    "और", "का", "की", "के", "को", "में", "से", "पर", "यह", "वह", "एक", "है", "था", "थे",
    "दोनों", "सही", "गलत", "केवल", "नहीं", "अथवा", "तथा", "कारण", "व्याख्या",
    "the", "and", "of", "to", "in", "on", "is", "was", "were", "a", "an", "both", "correct", "incorrect",
    "only", "neither", "reason", "assertion", "source", "answer", "question",
}


def source_evidence_supports_question(question: "ValidQuestion", source_context: str) -> bool:
    """Require factual terms from the answer/explanation to exist in the supplied source excerpt.

    The correct option of Assertion–Reason and multiple-statement questions is
    often a generic phrase (for example, ``A and R are both correct``), not a
    factual entity. In that case the factual evidence is carried by the
    explanation and key point, so those fields are included in the evidence
    check instead of rejecting a valid source-grounded question.
    """
    source_tokens = set(normalize_text(source_context).split())
    evidence_text = " ".join([
        question.options[question.correct_option], question.explanation, question.key_point,
    ])
    evidence_tokens = [
        token for token in normalize_text(evidence_text).split()
        if len(token) >= 3 and token not in _SOURCE_STOPWORDS
    ]
    if not evidence_tokens:
        return False
    return any(token in source_tokens for token in evidence_tokens)


def similarity(first: str, second: str) -> float:
    return SequenceMatcher(None, normalize_text(first), normalize_text(second)).ratio()


def find_similar(candidate: str, previous_questions: list[str], threshold: float) -> str | None:
    normalized = normalize_text(candidate)
    for prior in previous_questions:
        if normalized == normalize_text(prior) or similarity(candidate, prior) >= threshold:
            return prior
    return None


def _clean_text(value: object, field: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str):
        raise QuestionValidationError(f"{field} must be text")
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not minimum <= len(cleaned) <= maximum:
        raise QuestionValidationError(f"{field} must contain {minimum}–{maximum} characters")
    return cleaned


def _contains_complete_numbered_statements(question: str) -> bool:
    """Require at least two numbered statements in the learner-visible stem."""
    markers = re.findall(r"(?:statement|कथन|वक्तव्य)?\s*[1-4१२३४]\s*[.)。：:\-]", question, flags=re.IGNORECASE)
    return len(set(markers)) >= 2


def is_structurally_complete(question_type: str, question: str) -> bool:
    """Return whether a structured MCQ contains the information learners need."""
    if question_type in {"Statement-based", "Multiple-statement"}:
        return _contains_complete_numbered_statements(question)
    return True


def validate_question(
    payload: dict[str, Any], *, expected_subject: str | None = None, expected_topic: str | None = None,
    expected_difficulty: str | None = None, expected_language: str | None = None,
) -> ValidQuestion:
    required = {"question", "options", "correct_option", "explanation", "subject", "topic", "difficulty", "language"}
    missing = required.difference(payload)
    if missing:
        raise QuestionValidationError(f"Missing required fields: {', '.join(sorted(missing))}")

    question = _clean_text(payload["question"], "question", 12, POLL_QUESTION_MAX)
    raw_options = payload["options"]
    if not isinstance(raw_options, list) or len(raw_options) != 4:
        raise QuestionValidationError("Exactly four options are required")
    options = [_clean_text(option, "option", 1, POLL_OPTION_MAX) for option in raw_options]
    if len({normalize_text(option) for option in options}) != 4:
        raise QuestionValidationError("Options must be unique")

    correct = payload["correct_option"]
    if isinstance(correct, bool) or not isinstance(correct, int) or not 0 <= correct < 4:
        raise QuestionValidationError("correct_option must be an integer from 0 to 3")

    explanation = _clean_text(payload["explanation"], "explanation", 15, 900)
    key_point = _clean_text(payload.get("key_point") or explanation, "key_point", 10, 500)
    subject = _clean_text(payload["subject"], "subject", 2, 64)
    topic = _clean_text(payload["topic"], "topic", 2, 256)
    difficulty = _clean_text(payload["difficulty"], "difficulty", 4, 16).title()
    question_type = _clean_text(payload.get("question_type") or "Conceptual", "question_type", 3, 64)
    language = _clean_text(payload["language"], "language", 4, 16).title()

    if question_type not in VALID_QUESTION_TYPES:
        raise QuestionValidationError(f"Unsupported question type: {question_type}")
    if not is_structurally_complete(question_type, question):
        raise QuestionValidationError("Statement-based questions must include all numbered statements in the question text")
    if question_type == "Assertion-Reason" and subject != "Reasoning":
        raise QuestionValidationError("Assertion-Reason is available only for the Reasoning subject")
    if subject not in VALID_SUBJECTS:
        raise QuestionValidationError(f"Unsupported subject: {subject}")
    if difficulty not in VALID_DIFFICULTIES:
        raise QuestionValidationError(f"Unsupported difficulty: {difficulty}")
    if expected_subject and subject != expected_subject:
        raise QuestionValidationError("AI returned an unexpected subject")
    if expected_topic and topic != expected_topic:
        raise QuestionValidationError("AI returned an unexpected syllabus topic")
    if expected_difficulty and difficulty != expected_difficulty:
        raise QuestionValidationError("AI returned an unexpected difficulty")
    if language not in VALID_LANGUAGES:
        raise QuestionValidationError(f"Unsupported language: {language}")
    if expected_language and language != expected_language:
        raise QuestionValidationError("AI returned an unexpected language")

    return ValidQuestion(
        question=question, options=options, correct_option=correct, explanation=explanation,
        key_point=key_point, subject=subject, topic=topic, difficulty=difficulty,
        question_type=question_type, language=language,
    )

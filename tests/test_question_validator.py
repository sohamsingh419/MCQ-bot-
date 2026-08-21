import pytest

from bot.services.question_validator import QuestionValidationError, find_similar, validate_question


VALID = {
    "question": "Which constitutional body conducts elections to Parliament and state legislatures in India?",
    "options": ["Election Commission of India", "Union Public Service Commission", "Finance Commission", "NITI Aayog"],
    "correct_option": 0,
    "explanation": "Article 324 vests the superintendence, direction and control of elections in the Election Commission of India.",
    "key_point": "Article 324 establishes the Election Commission's election-supervision role.",
    "subject": "Indian Polity",
    "topic": "Constitutional bodies",
    "difficulty": "Exam",
    "question_type": "Conceptual",
    "language": "English",
}


def test_valid_question_is_accepted() -> None:
    question = validate_question(VALID, expected_subject="Indian Polity", expected_difficulty="Exam", expected_language="English")
    assert question.correct_option == 0
    assert len(question.options) == 4


def test_duplicate_options_are_rejected() -> None:
    payload = {**VALID, "options": ["Same", "Same", "Third", "Fourth"]}
    with pytest.raises(QuestionValidationError, match="unique"):
        validate_question(payload)


def test_non_four_options_are_rejected() -> None:
    payload = {**VALID, "options": VALID["options"][:3]}
    with pytest.raises(QuestionValidationError, match="Exactly four"):
        validate_question(payload)


def test_out_of_range_correct_option_is_rejected() -> None:
    payload = {**VALID, "correct_option": 4}
    with pytest.raises(QuestionValidationError, match="0 to 3"):
        validate_question(payload)


def test_near_duplicate_is_detected() -> None:
    previous = ["Which constitutional body conducts elections to the Parliament and state legislatures of India?"]
    assert find_similar(VALID["question"], previous, 0.80) is not None


def test_question_type_is_canonical_and_supported() -> None:
    payload = {**VALID, "question_type": "Match-the-following"}
    assert validate_question(payload).question_type == "Match-the-following"
    with pytest.raises(QuestionValidationError, match="Unsupported question type"):
        validate_question({**VALID, "question_type": "Trick-question"})
    with pytest.raises(QuestionValidationError, match="Unsupported question type"):
        validate_question({**VALID, "question_type": "Application-based"})


def test_wrong_subject_is_rejected() -> None:
    payload = {**VALID, "subject": "Unknown Studies"}
    with pytest.raises(QuestionValidationError, match="Unsupported subject"):
        validate_question(payload)


def test_question_exceeding_readable_poll_limit_is_rejected() -> None:
    payload = {**VALID, "question": "क" * 241}
    with pytest.raises(QuestionValidationError, match="question must contain"):
        validate_question(payload)


def test_option_exceeding_readable_poll_limit_is_rejected() -> None:
    payload = {**VALID, "options": ["A" * 73, "B", "C", "D"]}
    with pytest.raises(QuestionValidationError, match="option must contain"):
        validate_question(payload)


def test_assertion_reason_is_reasoning_only() -> None:
    with pytest.raises(QuestionValidationError, match="only for the Reasoning subject"):
        validate_question({**VALID, "subject": "Indian Polity", "question_type": "Assertion-Reason"})

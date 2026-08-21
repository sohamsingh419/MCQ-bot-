from types import SimpleNamespace

import pytest

from bot.config import SYLLABUS_TOPIC_MAP, VALID_SUBJECTS, syllabus_source_guidance, syllabus_topics_for
from bot.services.ai_generator import AIQuestionGenerator
from bot.services.question_validator import QuestionValidationError, validate_question
from bot.services.quiz import QuizService


def valid_payload() -> dict[str, object]:
    return {
        "question": "भारतीय संविधान के मौलिक अधिकारों के संदर्भ में निम्नलिखित कथनों पर विचार कीजिए: 1. वे नागरिक स्वतंत्रताओं की रक्षा करते हैं। 2. वे केवल कर संग्रह से संबंधित हैं। सही कूट चुनिए।",
        "options": ["नागरिक स्वतंत्रताओं की रक्षा", "केवल कर संग्रह", "राज्य सूची बनाना", "चुनाव स्थगित करना"],
        "correct_option": 0,
        "explanation": "मौलिक अधिकार नागरिकों की स्वतंत्रता और समानता की संवैधानिक रक्षा करते हैं।",
        "key_point": "मौलिक अधिकार संविधान के भाग III में हैं।",
        "subject": "Indian Polity",
        "topic": "Fundamental Rights and Duties",
        "difficulty": "Exam",
        "question_type": "Statement-based",
        "language": "Hindi",
    }


def test_every_enabled_subject_has_an_explicit_syllabus_topic_map() -> None:
    assert VALID_SUBJECTS.issubset(SYLLABUS_TOPIC_MAP)
    assert all(len(topics) >= 5 for topics in SYLLABUS_TOPIC_MAP.values())


def test_state_topics_are_scoped_to_the_selected_state() -> None:
    topics = syllabus_topics_for("Rajasthan", "State Geography")
    assert len(topics) >= 5
    assert all(topic.startswith("Rajasthan: ") for topic in topics)
    assert syllabus_topics_for("All India", "Indian Polity")[0] == "संविधान की ऐतिहासिक पृष्ठभूमि"


def test_source_guidance_uses_rbse_for_rajasthan_without_false_page_claims() -> None:
    guidance = syllabus_source_guidance("Rajasthan", "State GK")
    assert "RBSE" in guidance
    assert "Do not claim a book, chapter, page" in guidance


def test_topic_metadata_must_match_the_requested_topic() -> None:
    payload = valid_payload()
    assert validate_question(payload, expected_topic="Fundamental Rights and Duties").topic == "Fundamental Rights and Duties"
    with pytest.raises(QuestionValidationError, match="unexpected syllabus topic"):
        validate_question(payload, expected_topic="Parliament and legislative procedure")


def test_generation_prompt_requires_the_selected_topic() -> None:
    generator = object.__new__(AIQuestionGenerator)
    prompt = generator._user_prompt(
        state="Rajasthan", subject="State Geography", topic="Rajasthan: Rivers and drainage",
        question_type="Statement-based", language="Hindi", previous_questions=[], current_facts=None,
    )
    assert "Required syllabus topic: Rajasthan: Rivers and drainage" in prompt
    assert "RBSE resources" in prompt
    assert "Set topic metadata exactly" in prompt


def test_quiz_topic_cursor_advances_per_subject() -> None:
    settings = SimpleNamespace(state="Rajasthan", topic_rotation_state={})
    subject = "State GK"
    first = QuizService.topic_for_next_quiz(settings, subject)
    QuizService.advance_topic(settings, subject)
    second = QuizService.topic_for_next_quiz(settings, subject)
    assert first != second
    assert settings.topic_rotation_state[subject] == 1

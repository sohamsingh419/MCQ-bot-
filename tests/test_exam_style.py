from types import SimpleNamespace

from bot.config import exam_style_guidance
from bot.services.ai_generator import AIQuestionGenerator, FACT_HEAVY_EXAM_ROTATION, QUESTION_TYPES, question_types_for_difficulty
from bot.services.quiz import QuizService


def test_state_specific_exam_style_guidance_is_explicit() -> None:
    guidance = exam_style_guidance("Rajasthan", "State Geography")
    assert "Rajasthan" in guidance
    assert "state-level competitive examination" in guidance
    assert "physiography" in guidance
    assert "precise" in guidance
    assert "syllabus-grounded" in guidance


def test_all_india_exam_style_guidance_excludes_state_scope() -> None:
    guidance = exam_style_guidance("All India", "Indian Polity")
    assert "India-wide competitive-exam standard" in guidance
    assert "Constitution" in guidance
    assert "precise" in guidance


def test_rotation_has_three_facts_then_one_structured_question() -> None:
    rotation = question_types_for_difficulty()
    assert len(rotation) % 4 == 0
    for index in range(0, len(rotation), 4):
        assert rotation[index:index + 3] == ("Conceptual", "Conceptual", "Conceptual")
        assert rotation[index + 3] != "Conceptual"


def test_unified_rotation_is_fact_heavy_and_reasoning_adds_assertion_reason() -> None:
    rotation = question_types_for_difficulty()
    assert rotation == FACT_HEAVY_EXAM_ROTATION
    assert set(rotation).issubset(set(QUESTION_TYPES))
    assert rotation.count("Conceptual") >= 2
    assert "Assertion-Reason" not in rotation
    reasoning = question_types_for_difficulty(subject="Reasoning")
    assert reasoning[-1] == "Assertion-Reason"
    assert reasoning[-4:-1] == ("Conceptual", "Conceptual", "Conceptual")


def test_exam_style_prompt_is_state_subject_and_unified_exam_aware() -> None:
    generator = object.__new__(AIQuestionGenerator)
    prompt = generator._user_prompt(
        state="Rajasthan", subject="State History", topic="Rajasthan: Dynasties and rulers",
        question_type="Chronology/order", language="Hindi", previous_questions=[], current_facts=None,
    )
    assert "Exam-style profile:" in prompt
    assert "Rajasthan" in prompt
    assert "dynasties" in prompt
    assert "Unified exam-level rule:" in prompt
    assert "precise high-information details" in prompt
    assert "realistic exam confusions" in prompt
    assert "Difficulty-depth rule:" not in prompt
    assert "exactly one correct option" in prompt


def test_all_question_types_have_unified_exam_rules() -> None:
    generator = object.__new__(AIQuestionGenerator)
    for question_type in QUESTION_TYPES:
        prompt = generator._user_prompt(
            state="All India", subject="Indian Polity", topic="Fundamental Rights and Duties",
            question_type=question_type, language="English",
            previous_questions=[], current_facts=None,
        )
        assert f"Question type: {question_type}" in prompt
        assert "Question-type rule:" in prompt
        assert "Unified exam-level rule:" in prompt
        assert "exactly one correct option" in prompt


def test_matching_prompt_is_compact_and_unambiguous() -> None:
    generator = object.__new__(AIQuestionGenerator)
    prompt = generator._user_prompt(
        state="Rajasthan", subject="State Geography", topic="Rivers and drainage",
        question_type="Match-the-following", language="Hindi", previous_questions=[], current_facts=None,
    )
    assert "exactly 3 compact items in each column" in prompt
    assert "every option only a mapping" in prompt


def test_question_card_identifies_exam_style_practice_not_past_paper() -> None:
    question = SimpleNamespace(
        language="Hindi", subject="State GK", difficulty="Exam",
        question_text="राजस्थान के प्रशासनिक एवं भौगोलिक विकास से संबंधित इस विस्तृत प्रश्न का सही उत्तर चुनिए।",
        options=["पहला विकल्प", "दूसरा विकल्प", "तीसरा विकल्प", "चौथा विकल्प"],
    )
    card = QuizService.full_question_card(question)
    assert card.startswith("प्रतियोगी परीक्षा अभ्यास • State GK")
    assert "• Exam" not in card
    assert "पिछले वर्ष" not in card


def test_matching_card_separates_mapping_options_and_instruction() -> None:
    question = SimpleNamespace(
        language="Hindi", subject="State History", difficulty="Exam", question_type="Match-the-following",
        question_text="कॉलम A: 1. किला 2. महल\nकॉलम B: (a) जयपुर (b) जैसलमेर",
        options=["1–a, 2–b", "1–b, 2–a", "1–a, 2–a", "1–b, 2–b"],
    )
    card = QuizService.full_question_card(question)
    assert "🔗 मिलान प्रश्न" in card
    assert "A) 1–a, 2–b" in card
    assert "कॉलम A के प्रत्येक item" in card
    assert "• Exam" not in card


def test_question_types_helper_always_uses_unified_rotation() -> None:
    assert question_types_for_difficulty() == FACT_HEAVY_EXAM_ROTATION
    assert question_types_for_difficulty(subject="Reasoning")[-1] == "Assertion-Reason"

from types import SimpleNamespace

from bot.config import QUESTION_LANGUAGE
from bot.services.ai_generator import AIQuestionGenerator
from bot.services.quiz import QuizService


def test_generated_question_language_is_hindi_only():
    assert QUESTION_LANGUAGE == "Hindi"
    generator = object.__new__(AIQuestionGenerator)
    prompt = generator._user_prompt(
        state="Rajasthan",
        subject="State History",
        topic="Ancient and medieval history",
        question_type="Conceptual",
        language="English",
        previous_questions=[],
        current_facts=None,
    )
    assert "Hindi only" in prompt
    assert "Devanagari Hindi" in prompt


def test_english_ui_uses_english_poll_instruction_for_hindi_question():
    question = SimpleNamespace(
        question_text="राजस्थान के इतिहास से संबंधित एक लंबा प्रश्न जिसमें पूरा विवरण दिया गया है?",
        options=["विकल्प A", "विकल्प B", "विकल्प C", "विकल्प D"],
        question_type="Statement-based",
        language="Hindi",
    )
    poll_question, poll_options = QuizService.poll_content(question, "English")
    assert poll_question == "Choose the correct answer"
    assert poll_options == ["A", "B", "C", "D"]


def test_short_hindi_question_keeps_full_content_even_with_english_ui():
    question = SimpleNamespace(
        question_text="राजस्थान की राजधानी क्या है?",
        options=["जयपुर", "जोधपुर", "उदयपुर", "अजमेर"],
        question_type="Conceptual",
        language="Hindi",
    )
    poll_question, poll_options = QuizService.poll_content(question, "English")
    assert poll_question == question.question_text
    assert poll_options == question.options


def test_mock_round_banner_is_not_part_of_delivery_source():
    import inspect
    from bot.services.quiz import QuizService as Service

    source = inspect.getsource(Service.send_next_mock_round)
    assert "Round {number}" not in source
    assert "separate Round 1/2 banner" in source



def test_mock_short_question_includes_visible_progress_header():
    question = SimpleNamespace(
        question_text="राजस्थान की राजधानी क्या है?",
        options=["जयपुर", "जोधपुर", "उदयपुर", "अजमेर"],
        question_type="Conceptual",
        language="Hindi",
    )
    poll_question, poll_options = QuizService.poll_content(question, "English", (1, 45))
    assert poll_question == "[1/45] राजस्थान की राजधानी क्या है?"
    assert poll_options == question.options


def test_mock_long_question_card_includes_progress_and_mock_test_label():
    question = SimpleNamespace(
        question_text="राजस्थान के इतिहास से संबंधित एक लंबा प्रश्न जिसमें पूरा विवरण दिया गया है?",
        options=["विकल्प A", "विकल्प B", "विकल्प C", "विकल्प D"],
        question_type="Statement-based",
        language="Hindi",
    )
    card = QuizService.full_question_card(question, "English", (12, 45))
    assert "MOCK TEST" in card
    assert "[12/45]" in card


def test_mock_lobby_uses_mock_test_not_quiz_wording():
    hindi = QuizService.mock_lobby_text("Rajasthan History", 45, 15, ui_language="Hindi")
    english = QuizService.mock_lobby_text("Rajasthan History", 45, 15, ui_language="English")
    assert "Mock Test" in hindi
    assert "कुल प्रश्न: *45*" in hindi
    assert "Quiz" not in hindi
    assert "Mock Test" in english
    assert "Total questions: *45*" in english
    assert "Quiz" not in english


def test_mock_messages_omit_outdated_joined_only_and_next_test_lines():
    hindi = QuizService.mock_lobby_text("Rajasthan History", 5, 30, ui_language="Hindi")
    english = QuizService.mock_lobby_text("Rajasthan History", 5, 30, ui_language="English")
    assert "Final ranking केवल joined participants की होगी" not in hindi
    assert "Final ranking" not in english
    assert "अगले mock test के लिए तैयार रहें" not in hindi
    assert "Get ready for the next mock test" not in english


def test_mock_live_message_source_mentions_question_progress_not_round_banner():
    import inspect
    from bot.services.quiz import QuizService as Service

    source = inspect.getsource(Service.start_mock_test)
    assert "Mock Test" in source
    assert "[1/{mock.question_count}]" in source
    assert "Rounds:" not in source

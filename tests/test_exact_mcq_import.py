from types import SimpleNamespace

from bot.services.source import extract_mcq_questions
from bot.handlers.bulk_import import _is_bulk_group, _language, _question_type


def test_pdf_mcq_parser_preserves_question_options_and_answer() -> None:
    pages = [(1, """1. राजस्थान का राज्य पक्षी कौन सा है?
A. मोर
B. गोडावण
C. सारस
D. कबूतर
सही उत्तर: B

2. Which body conducts elections in India?
A. UPSC
B. Election Commission
C. Finance Commission
D. NITI Aayog
Answer: B
""")]
    questions = extract_mcq_questions(pages)
    assert len(questions) == 2
    assert questions[0]["question_text"] == "राजस्थान का राज्य पक्षी कौन सा है?"
    assert questions[0]["options"] == ["मोर", "गोडावण", "सारस", "कबूतर"]
    assert questions[0]["correct_option"] == 1
    assert questions[1]["question_text"] == "Which body conducts elections in India?"
    assert questions[1]["correct_option"] == 1


def test_pdf_mcq_parser_skips_missing_answer_key() -> None:
    pages = [(1, """1. Incomplete question?
A. One
B. Two
C. Three
D. Four
""")]
    assert extract_mcq_questions(pages) == []


def test_imported_bulk_poll_helpers_preserve_language_and_type() -> None:
    question = "निम्नलिखित कथनों पर विचार कीजिए: 1. पहला कथन सही है। 2. दूसरा कथन गलत है।"
    assert _language(question, ["केवल 1", "केवल 2", "1 और 2", "न तो 1, न ही 2"]) == "Hindi"
    assert _question_type(question) == "Statement-based"
    assert _is_bulk_group(None, "supergroup") is False

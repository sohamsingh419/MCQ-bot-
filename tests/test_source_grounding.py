from bot.services.question_validator import ValidQuestion, source_evidence_supports_question


def _question(answer: str) -> ValidQuestion:
    return ValidQuestion(
        question="Which fact is supported by the source?",
        options=[answer, "Other fact", "Another fact", "None"],
        correct_option=0,
        explanation="The source supports the selected fact.",
        key_point="Use the supplied source.",
        subject="State Geography",
        topic="Rivers and drainage",
        difficulty="Exam",
        question_type="Conceptual",
        language="English",
    )


def test_source_evidence_accepts_supported_correct_answer() -> None:
    assert source_evidence_supports_question(
        _question("Ganga river system"),
        "The Ganga river system is described in this source excerpt.",
    ) is True


def test_source_evidence_rejects_unrelated_correct_answer() -> None:
    assert source_evidence_supports_question(
        _question("Black soil and cotton"),
        "This excerpt discusses Rajasthan folk deities and temple traditions.",
    ) is False


def test_source_evidence_uses_explanation_for_generic_assertion_reason_option() -> None:
    question = ValidQuestion(
        question="कथन (A) और कारण (R) के संबंध में सही विकल्प चुनें।",
        options=[
            "A और R दोनों सही हैं तथा R, A की सही व्याख्या है।",
            "A और R दोनों सही हैं, पर R, A की सही व्याख्या नहीं है।",
            "A सही है, R गलत है।",
            "A गलत है, R सही है।",
        ],
        correct_option=0,
        explanation="अरावली पर्वतमाला राजस्थान के दक्षिण-पश्चिम से उत्तर-पूर्व तक फैली है और पश्चिमी भाग में वर्षाछाया प्रभाव बनाती है।",
        key_point="अरावली और वर्षाछाया प्रभाव।",
        subject="State History",
        topic="Rajasthan: प्रमुख ऐतिहासिक स्थल",
        difficulty="Exam",
        question_type="Assertion-Reason",
        language="Hindi",
    )
    assert source_evidence_supports_question(
        question, "अरावली पर्वतमाला राजस्थान में वर्षाछाया प्रभाव और भौगोलिक संरचना को प्रभावित करती है।"
    ) is True

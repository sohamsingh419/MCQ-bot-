import json
from types import SimpleNamespace

import pytest

from bot.services.ai_generator import (
    AICompletionUnavailableError,
    AIProviderRateLimitError,
    AIQuestionGenerator,
    AIValidationUnavailableError,
    ValidationDecision,
)
from bot.services.question_validator import ValidQuestion


@pytest.mark.asyncio
async def test_provider_order_is_gemini_then_groq_then_legacy() -> None:
    generator = object.__new__(AIQuestionGenerator)
    calls: list[str] = []

    async def gemini(_: str):
        calls.append("gemini")
        raise AICompletionUnavailableError("Gemini unavailable")

    async def groq(_: str):
        calls.append("groq")
        return {"provider": "groq"}

    async def legacy(_: str):
        calls.append("legacy")
        return {"provider": "legacy"}

    generator._request_gemini = gemini
    generator._request_groq = groq
    generator._request_openai_compatible = legacy

    result = await generator._request("test prompt")
    assert result == {"provider": "groq"}
    assert calls == ["gemini", "groq"]


@pytest.mark.asyncio
async def test_mistral_provider_is_used_before_legacy_fallback() -> None:
    generator = object.__new__(AIQuestionGenerator)
    calls: list[str] = []

    async def unavailable(_: str):
        calls.append("unavailable")
        raise AICompletionUnavailableError("provider unavailable")

    async def mistral(_: str):
        calls.append("mistral")
        return {"provider": "mistral"}

    generator._request_gemini = unavailable
    generator._request_groq = unavailable
    generator._request_mistral = mistral
    generator._request_openai_compatible = unavailable

    assert await generator._request("test prompt") == {"provider": "mistral"}
    assert calls == ["unavailable", "unavailable", "mistral"]


@pytest.mark.asyncio
async def test_legacy_provider_is_last_resort() -> None:
    generator = object.__new__(AIQuestionGenerator)
    calls: list[str] = []

    async def unavailable(_: str):
        calls.append("unavailable")
        raise AICompletionUnavailableError("provider unavailable")

    async def legacy(_: str):
        calls.append("legacy")
        return {"provider": "legacy"}

    generator._request_gemini = unavailable
    generator._request_groq = unavailable
    generator._request_mistral = unavailable
    generator._request_openai_compatible = legacy

    assert await generator._request("test prompt") == {"provider": "legacy"}
    assert calls == ["unavailable", "unavailable", "unavailable", "legacy"]


@pytest.mark.asyncio
async def test_provider_cooldown_skips_repeated_rate_limited_calls() -> None:
    generator = object.__new__(AIQuestionGenerator)
    generator.settings = SimpleNamespace(ai_provider_cooldown_seconds=30, ai_provider_min_interval_seconds=0.0)
    calls: list[str] = []

    async def rate_limited(_: str):
        calls.append("rate-limited")
        raise AIProviderRateLimitError("429")

    generator._request_gemini = rate_limited
    generator._request_groq = rate_limited
    generator._request_mistral = rate_limited
    generator._request_openai_compatible = rate_limited

    with pytest.raises(AICompletionUnavailableError):
        await generator._request("test prompt")
    first_call_count = len(calls)
    with pytest.raises(AICompletionUnavailableError):
        await generator._request("test prompt")
    assert first_call_count == 4
    assert len(calls) == first_call_count


def test_provider_json_parser_rejects_malformed_content() -> None:
    generator = object.__new__(AIQuestionGenerator)
    with pytest.raises(AICompletionUnavailableError):
        generator._parse_json_content("")


def _valid_question() -> ValidQuestion:
    return ValidQuestion(
        question="Which body conducts elections in India?",
        options=["Election Commission", "Finance Commission", "UPSC", "NITI Aayog"],
        correct_option=0,
        explanation="The Election Commission conducts elections under Article 324.",
        key_point="Article 324",
        subject="Indian Polity",
        topic="Constitutional bodies",
        difficulty="Exam",
        question_type="Conceptual",
        language="English",
    )


def _validator_settings() -> SimpleNamespace:
    return SimpleNamespace(
        validator_enabled=True,
        validator_confidence_threshold=0.70,
        validator_cooldown_seconds=120,
        groq_model="validator-model",
        ai_model="fallback-model",
    )


@pytest.mark.asyncio
async def test_validator_approval_allows_question() -> None:
    generator = object.__new__(AIQuestionGenerator)
    generator.settings = _validator_settings()
    generator._validator_cooldown_until = 0.0

    async def approved(_: str) -> ValidationDecision:
        return ValidationDecision(True, 0.95, 0, [], "Unique correct answer")

    generator._request_validator_groq = approved
    assert await generator._validate_independently(_valid_question()) is True


@pytest.mark.asyncio
async def test_validator_rejects_when_all_available_validators_disagree() -> None:
    generator = object.__new__(AIQuestionGenerator)
    generator.settings = _validator_settings()
    generator._validator_cooldown_until = 0.0

    async def disagreement(_: str) -> ValidationDecision:
        return ValidationDecision(True, 0.99, 1, [], "Different option is correct")

    async def unavailable(_: str) -> ValidationDecision:
        raise AIValidationUnavailableError("unavailable")

    generator._request_validator_groq = disagreement
    generator._request_validator_mistral = unavailable
    generator._request_validator_openai_compatible = unavailable
    assert await generator._validate_independently(_valid_question()) is False


@pytest.mark.asyncio
async def test_validator_rechecks_after_disagreement_and_accepts_second_approval() -> None:
    generator = object.__new__(AIQuestionGenerator)
    generator.settings = _validator_settings()
    generator._validator_cooldown_until = 0.0
    calls: list[str] = []

    async def disagreement(_: str) -> ValidationDecision:
        calls.append("disagreement")
        return ValidationDecision(True, 0.99, 1, [], "Different option is correct")

    async def approval(_: str) -> ValidationDecision:
        calls.append("approval")
        return ValidationDecision(True, 0.70, 0, [], "The supplied answer is supported")

    generator._request_validator_groq = disagreement
    generator._request_validator_mistral = approval
    assert await generator._validate_independently(_valid_question()) is True
    assert calls == ["disagreement", "approval"]


def test_validator_parser_rejects_malformed_decision() -> None:
    with pytest.raises(AIValidationUnavailableError):
        AIQuestionGenerator._parse_validation_decision(json.dumps({"approved": "yes"}))


@pytest.mark.asyncio
async def test_validator_limit_falls_back_to_structural_validation_with_cooldown() -> None:
    generator = object.__new__(AIQuestionGenerator)
    generator.settings = _validator_settings()
    generator._validator_cooldown_until = 0.0

    async def unavailable(_: str) -> ValidationDecision:
        raise AIValidationUnavailableError("rate limited")

    generator._request_validator_groq = unavailable
    generator._request_validator_mistral = unavailable
    generator._request_validator_openai_compatible = unavailable
    assert await generator._validate_independently(_valid_question()) is None
    assert generator._validator_cooldown_until > 0


def test_gemini_schema_removes_openai_only_constraints() -> None:
    schema = AIQuestionGenerator._gemini_schema()
    serialized = str(schema)
    assert "additionalProperties" not in serialized
    assert "minLength" not in serialized
    assert "maxLength" not in serialized
    assert schema["properties"]["options"]["minItems"] == 4



def test_provider_metadata_is_canonicalized_to_requested_scope() -> None:
    payload = {
        "question": "Which dynasty ruled the region?",
        "options": ["Dynasty A", "Dynasty B", "Dynasty C", "Dynasty D"],
        "correct_option": 0,
        "explanation": "The source identifies Dynasty A.",
        "key_point": "Dynasty A.",
        "subject": "History",
        "topic": "translated topic",
        "difficulty": "Exam",
        "language": "English",
    }
    canonical = AIQuestionGenerator._canonicalize_metadata(
        payload, subject="State History", topic="Rajasthan: प्रमुख राजवंश", difficulty="Exam", language="Hindi"
    )
    assert canonical["subject"] == "State History"
    assert canonical["topic"] == "Rajasthan: प्रमुख राजवंश"
    assert canonical["difficulty"] == "Exam"
    assert canonical["language"] == "Hindi"

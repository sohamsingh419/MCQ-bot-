"""AI-backed, structured question generation with strict validation."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx
from openai import AsyncOpenAI, APIConnectionError, APIStatusError, APITimeoutError

from bot.config import QUESTION_LANGUAGE, Settings, UNIFIED_EXAM_LEVEL, exam_style_guidance
from bot.services.question_validator import QuestionValidationError, ValidQuestion, validate_question

logger = logging.getLogger(__name__)

QUESTION_TYPES = [
    "Conceptual", "Analytical", "Statement-based",
    "Match-the-following", "Chronology/order", "Case-based", "Multiple-statement",
]
# Fact/recall formats deliberately occur more often than thought-heavy formats.
FACT_HEAVY_EXAM_ROTATION = (
    "Conceptual", "Conceptual", "Conceptual", "Statement-based",
    "Conceptual", "Conceptual", "Conceptual", "Match-the-following",
    "Conceptual", "Conceptual", "Conceptual", "Chronology/order",
    "Conceptual", "Conceptual", "Conceptual", "Multiple-statement",
    "Conceptual", "Conceptual", "Conceptual", "Analytical",
)
REASONING_QUESTION_TYPES = [
    *FACT_HEAVY_EXAM_ROTATION,
    "Conceptual", "Conceptual", "Conceptual", "Assertion-Reason",
]
QUESTION_TYPES_BY_DIFFICULTY = {UNIFIED_EXAM_LEVEL: FACT_HEAVY_EXAM_ROTATION}
QUESTION_TYPE_GUIDANCE = {
    "Conceptual": "Prefer a precise, syllabus-grounded factual recall question; test one clearly verifiable fact rather than vague trivia.",
    "Analytical": "Use a smaller share of comparison, cause-effect, or elimination questions using only the supplied topic.",
    "Statement-based": "Put the complete numbered statements inside the question field before the answer prompt, for example ‘Statement 1: … Statement 2: …’. Never omit or place essential statements outside the question. Ask which combination is correct; keep every statement independently meaningful. Options must contain only concise combinations such as ‘Only 1’, ‘Only 2’, ‘1 and 2’, or ‘Neither 1 nor 2’.",
    "Assertion-Reason": "Provide a distinct Assertion and Reason and make the logical relationship unambiguous.",
    "Match-the-following": "Create exactly two clearly labeled compact lists with exactly 3 items: Column A items 1–3 and Column B items (a)–(c). Keep each item short, specific, and on the same syllabus topic. Put the complete lists in the question text, each on a separate line. Answer options must contain only concise mappings such as ‘1–b, 2–c, 3–a’. Keep all four mapping options visibly distinct, make exactly one mapping correct, and never hide list items or merge them into a paragraph.",
    "Chronology/order": "Use events, stages, or processes from the topic and ask for their correct order.",
    "Case-based": "Give a concise, realistic case with all information needed to reach one defensible answer.",
    "Multiple-statement": "Put every precise numbered statement inside the question field before the answer prompt. Never provide an incomplete stem or hide statements outside the question. Ensure exactly one option has the correct combination.",
}
EXAM_LEVEL_GUIDANCE = "Use one unified serious competitive-exam standard. Make concise factual recall and precise syllabus facts the clear majority. Make facts deep and difficult through exact material, date, location, dynasty, person, feature, institution, sequence, classification, exception, or comparison details—not through long stories. Use a smaller share of statement, matching, chronology, and analytical formats. Never use case-based, patient-scenario, application-based, narrative, or situation-based questions in the normal delivery rotation. Never use ambiguity or unsupported trivia."


def question_types_for_exam(subject: str | None = None) -> tuple[str, ...]:
    return tuple(REASONING_QUESTION_TYPES if subject == "Reasoning" else FACT_HEAVY_EXAM_ROTATION)


def question_types_for_difficulty(difficulty: str = UNIFIED_EXAM_LEVEL, subject: str | None = None) -> tuple[str, ...]:
    """Backward-compatible helper; all new questions use one unified exam-level rotation."""
    return question_types_for_exam(subject)


class AIQuestionGenerationError(RuntimeError):
    pass


class AICompletionUnavailableError(AIQuestionGenerationError):
    """The provider responded successfully but supplied no usable completion."""


class AIProviderRateLimitError(AIQuestionGenerationError):
    """A provider returned a rate-limit or temporary-capacity response."""


class AIValidationUnavailableError(AIQuestionGenerationError):
    """The independent validator could not be reached or returned unusable data."""


@dataclass(frozen=True)
class ValidationDecision:
    approved: bool
    confidence: float
    correct_option_verified: int | None
    issues: list[str]
    reason: str


class CurrentAffairsProvider:
    """Supplies source-backed facts only when a current-information API is configured."""

    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.news_api_key
        self.url = settings.news_api_url

    async def facts(self, *, state: str, subject: str) -> list[str]:
        if not self.api_key:
            raise AIQuestionGenerationError(
                "Current Affairs requires NEWS_API_KEY. The bot will not fabricate live facts."
            )
        query = f"{state} {subject}" if state != "General" else "India current affairs"
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.get(
                    self.url,
                    params={"apiKey": self.api_key, "q": query, "language": "en", "pageSize": 5},
                )
                response.raise_for_status()
                articles = response.json().get("articles", [])
        except httpx.HTTPError as exc:
            raise AIQuestionGenerationError("Current-affairs source is temporarily unavailable") from exc
        facts = []
        for article in articles:
            title = (article.get("title") or "").strip()
            description = (article.get("description") or "").strip()
            published = (article.get("publishedAt") or "").strip()
            source = (article.get("source") or {}).get("name", "configured source")
            if title:
                facts.append(f"{title}. {description} Published: {published}. Source: {source}.")
        if not facts:
            raise AIQuestionGenerationError("Current-affairs source returned no usable facts")
        return facts


class AIQuestionGenerator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        kwargs: dict[str, Any] = {"api_key": settings.ai_api_key, "timeout": 35.0, "max_retries": 0}
        if settings.ai_base_url:
            kwargs["base_url"] = settings.ai_base_url
        self.client = AsyncOpenAI(**kwargs)
        self.groq_client = AsyncOpenAI(
            api_key=settings.groq_api_key or "unused-groq-key",
            base_url="https://api.groq.com/openai/v1",
            timeout=35.0,
            max_retries=0,
        ) if settings.groq_api_key else None
        self.mistral_client = AsyncOpenAI(
            api_key=settings.mistral_api_key or "unused-mistral-key",
            base_url=settings.mistral_base_url,
            timeout=35.0,
            max_retries=0,
        ) if settings.mistral_api_key else None
        self.current_affairs = CurrentAffairsProvider(settings)
        self._validator_cooldown_until = 0.0
        self._request_slots = asyncio.Semaphore(int(getattr(settings, "ai_max_concurrent_requests", 4)))
        self._provider_locks = {
            name: asyncio.Lock() for name in ("gemini", "groq", "mistral", "openai-compatible")
        }
        self._provider_cooldown_until: dict[str, float] = {}
        self._provider_next_request_at: dict[str, float] = {}

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are a meticulous Indian competitive-exam MCQ author. Produce one rigorous exam-style practice "
            "question matching the requested state, subject, and question pattern. It must feel like a "
            "serious competitive-exam item, but never claim it was copied from a past paper or that it appeared in an exam. "
            "Always write all learner-facing question text, options, explanation, and key point in clear Devanagari Hindi. "
            "Use only stable, supportable facts; never invent a statistic, scheme, event, constitutional provision, "
            "official title, or place-specific detail. The answer must be uniquely correct and the explanation must justify it. "
            "Return strict JSON only, with keys: "
            "question, options, correct_option (zero-based integer), explanation, key_point, subject, topic, "
            "difficulty (always exactly 'Exam'), question_type, language. Do not add markdown or commentary."
        )

    def _user_prompt(
        self, *, state: str, subject: str, topic: str, question_type: str, language: str, previous_questions: list[str],
        current_facts: list[str] | None, source_context: str | None = None,
    ) -> str:
        duplicates = "\n".join(f"- {item}" for item in previous_questions[-12:]) or "None"
        facts = "\n".join(f"- {item}" for item in (current_facts or [])) or "Not applicable"
        source_material = source_context or "No PDF source material supplied; use only stable syllabus facts."
        profile = exam_style_guidance(state, subject)
        type_guidance = QUESTION_TYPE_GUIDANCE[question_type]
        return f"""Create exactly one exam-level {question_type} competitive-exam practice MCQ.
Exam-style profile: {profile}
Subject: {subject}
Required syllabus topic: {topic}
Question type: {question_type}
Unified exam-level rule: {EXAM_LEVEL_GUIDANCE}
Question-type rule: {type_guidance}
Required learner-facing language: Hindi only. Write the question, all options, explanation, and key point entirely in clear Devanagari Hindi. Keep metadata values such as subject, topic, question_type, difficulty, and language in their canonical forms.
Use precisely 4 distinct, plausible options. For Statement-based and Multiple-statement types, the question field itself must include all numbered statements; the options must only describe the valid combination. For Match-the-following, use exactly 3 compact items in each column, keep each item short, place Column A and Column B on separate lines, and make every option only a mapping. Distractors must come from the same syllabus area and represent realistic exam confusions, not absurd choices. Make direct factual questions the majority of the rotation. A direct fact should be short and clear, similar to: ‘विटामिन बी-12 की कमी से कौन-सा रोग होता है?’ Make such questions deep and tough by testing a precise, less-obvious but syllabus-grounded exam fact, not by adding a long patient story or unnecessary context. Prefer precise high-information details—exact material, date, place, dynasty, person, feature, institution, sequence, classification, exception, or comparison details—over generic definitions.
 Do not use case-based, application-based, situation-based, patient-story, or narrative framing. Use statement, matching, chronology, and analytical formats in a smaller balanced share. The question must be a standalone prompt of at most 240 characters; aim for 30–140 characters for direct factual questions. Each option must be complete, concise and at most 72 characters; never use ellipses, cut-off phrases, tables, or multi-part option text. Set topic metadata exactly to the Required syllabus topic. Return one correct option as its zero-based index. There must be exactly one correct option; reject your own draft if two options could reasonably be correct or if the explanation does not prove uniqueness.
Do not ask any question substantially similar to these previous questions:
{duplicates}
For Current Affairs, use only the following provided, source-backed facts; otherwise, do not use current-affairs claims:
{facts}

PDF Source Mode material (when supplied) is authoritative for this question. Use only facts explicitly supported by the excerpts below. Do not use general knowledge to fill gaps. The correct answer, explanation, and key point must be traceable to the supplied excerpt; if the excerpt does not mention or support the answer, reject the draft and create a different question. Never attach a PDF source citation to a question merely because the PDF has the same state or subject:
{source_material}
"""

    @staticmethod
    def _json_schema() -> dict[str, Any]:
        return {
            "name": "validated_mcq",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "minLength": 12, "maxLength": 240},
                    "options": {
                        "type": "array", "minItems": 4, "maxItems": 4,
                        "items": {"type": "string", "minLength": 1, "maxLength": 72},
                    },
                    "correct_option": {"type": "integer", "minimum": 0, "maximum": 3},
                    "explanation": {"type": "string", "minLength": 15, "maxLength": 900},
                    "key_point": {"type": "string", "minLength": 10, "maxLength": 500},
                    "subject": {"type": "string", "minLength": 2, "maxLength": 64},
                    "topic": {"type": "string", "minLength": 2, "maxLength": 256},
                    "difficulty": {"type": "string", "minLength": 4, "maxLength": 16},
                    "question_type": {"type": "string", "minLength": 3, "maxLength": 64},
                    "language": {"type": "string", "enum": ["Hindi"]},
                },
                "required": [
                    "question", "options", "correct_option", "explanation", "key_point", "subject",
                    "topic", "difficulty", "question_type", "language",
                ],
                "additionalProperties": False,
            },
        }

    @staticmethod
    def _gemini_schema() -> dict[str, Any]:
        """Translate the shared schema to Gemini's supported JSON Schema subset."""
        schema = json.loads(json.dumps(AIQuestionGenerator._json_schema()["schema"]))

        def strip_unsupported(node: Any) -> None:
            if isinstance(node, dict):
                node.pop("minLength", None)
                node.pop("maxLength", None)
                node.pop("additionalProperties", None)
                for value in node.values():
                    strip_unsupported(value)
            elif isinstance(node, list):
                for value in node:
                    strip_unsupported(value)

        strip_unsupported(schema)
        return schema

    @staticmethod
    def _parse_json_content(content: str | None) -> dict[str, Any]:
        if not content:
            raise AICompletionUnavailableError("AI provider returned an empty completion")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AIQuestionGenerationError("AI returned malformed JSON") from exc
        if not isinstance(parsed, dict):
            raise AIQuestionGenerationError("AI did not return a JSON object")
        return parsed

    async def _request_gemini(self, user_prompt: str) -> dict[str, Any]:
        if not self.settings.gemini_api_key:
            raise AICompletionUnavailableError("Gemini API key is not configured")
        payload = {
            "contents": [{"role": "user", "parts": [{"text": self._system_prompt() + "\\n\\n" + user_prompt}]}],
            "generationConfig": {
                "temperature": 0.25,
                "maxOutputTokens": 1000,
                "responseMimeType": "application/json",
                "responseSchema": self._gemini_schema(),
            },
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.settings.gemini_model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                response = await client.post(url, params={"key": self.settings.gemini_api_key}, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {429, 502, 503, 504}:
                raise AIProviderRateLimitError(f"Gemini temporary capacity/rate-limit response {exc.response.status_code}") from exc
            raise AIQuestionGenerationError("Gemini request failed") from exc
        except httpx.HTTPError as exc:
            raise AIQuestionGenerationError("Gemini request failed") from exc
        candidates = data.get("candidates") or []
        if not candidates:
            raise AICompletionUnavailableError("Gemini returned no completion")
        parts = ((candidates[0].get("content") or {}).get("parts") or [])
        content = parts[0].get("text") if parts else None
        return self._parse_json_content(content)

    async def _request_groq(self, user_prompt: str) -> dict[str, Any]:
        if self.groq_client is None:
            raise AICompletionUnavailableError("Groq API key is not configured")
        response = await self.groq_client.chat.completions.create(
            model=self.settings.groq_model,
            temperature=0.25,
            max_tokens=1000,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self._system_prompt() + " Return valid JSON only."},
                {"role": "user", "content": user_prompt},
            ],
        )
        choices = response.choices or []
        if not choices:
            raise AICompletionUnavailableError("Groq returned no completion")
        return self._parse_json_content(choices[0].message.content)

    async def _request_mistral(self, user_prompt: str) -> dict[str, Any]:
        if self.mistral_client is None:
            raise AICompletionUnavailableError("Mistral API key is not configured")
        response = await self.mistral_client.chat.completions.create(
            model=self.settings.mistral_model,
            temperature=0.25,
            max_tokens=1000,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self._system_prompt() + " Return valid JSON only."},
                {"role": "user", "content": user_prompt},
            ],
        )
        choices = response.choices or []
        if not choices:
            raise AICompletionUnavailableError("Mistral returned no completion")
        return self._parse_json_content(choices[0].message.content)

    async def _request_openai_compatible(self, user_prompt: str) -> dict[str, Any]:
        response = await self.client.chat.completions.create(
            model=self.settings.ai_model,
            temperature=0.25,
            max_completion_tokens=1000,
            response_format={"type": "json_schema", "json_schema": self._json_schema()},
            messages=[
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
        )
        choices = response.choices or []
        if not choices:
            detail = getattr(response, "details", None) or getattr(response, "error", None)
            logger.warning("OpenAI-compatible provider returned no completion choices: %s", detail or "no details")
            raise AICompletionUnavailableError("OpenAI-compatible provider returned no completion")
        return self._parse_json_content(choices[0].message.content)

    @staticmethod
    def _validator_prompt(question: ValidQuestion, source_context: str | None = None) -> str:
        payload = {
            "question": question.question,
            "options": question.options,
            "correct_option": question.correct_option,
            "explanation": question.explanation,
            "subject": question.subject,
            "topic": question.topic,
            "difficulty": question.difficulty,
            "question_type": question.question_type,
            "language": question.language,
        }
        return f"""Independently audit this competitive-exam MCQ. Do not rewrite it and do not guess.
Check factual correctness, whether exactly one option is correct, whether the explanation supports the answer, whether it matches the subject/topic/type and canonical Exam metadata, and whether the wording is clear rather than ambiguous. For this unified Exam-level standard, verify that precise material/date/location/person/chronology details are correct, syllabus-relevant, and distinguish the answer from realistic same-domain distractors rather than relying on obscure or unsupported trivia.
Return JSON only with exactly these keys: approved (boolean), confidence (number from 0 to 1), correct_option_verified (integer 0 to 3 or null), issues (array of short strings), reason (short string).
Approve only when the supplied correct option is uniquely and defensibly correct. Reject if two options could reasonably be correct, the answer is unsupported, or the question is materially ambiguous.
MCQ:
{json.dumps(payload, ensure_ascii=False)}
PDF source excerpt for verification (if supplied):
{source_context or 'No PDF source supplied.'}

Validator rule: when a PDF excerpt is supplied, approve only if the correct answer is explicitly supported by that excerpt. If you cannot quote or point to the supporting fact in the excerpt, return approved=false. Do not approve based on outside knowledge or on state/subject similarity."""

    @staticmethod
    def _parse_validation_decision(content: str | None) -> ValidationDecision:
        parsed = AIQuestionGenerator._parse_json_content(content)
        approved = parsed.get("approved")
        confidence = parsed.get("confidence")
        verified = parsed.get("correct_option_verified")
        issues = parsed.get("issues", [])
        reason = parsed.get("reason", "")
        if not isinstance(approved, bool):
            raise AIValidationUnavailableError("Validator returned an invalid approval flag")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise AIValidationUnavailableError("Validator returned an invalid confidence score")
        if verified is not None and (isinstance(verified, bool) or not isinstance(verified, int) or not 0 <= verified < 4):
            raise AIValidationUnavailableError("Validator returned an invalid verified option")
        if not isinstance(issues, list) or not all(isinstance(item, str) for item in issues):
            raise AIValidationUnavailableError("Validator returned invalid issues")
        if not isinstance(reason, str):
            raise AIValidationUnavailableError("Validator returned an invalid reason")
        return ValidationDecision(bool(approved), float(confidence), verified, issues, reason)

    async def _request_validator_groq(self, prompt: str) -> ValidationDecision:
        if self.groq_client is None:
            raise AIValidationUnavailableError("Groq validator is not configured")
        response = await self.groq_client.chat.completions.create(
            model=self.settings.groq_model,
            temperature=0,
            max_tokens=300,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are an independent MCQ fact and ambiguity validator. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        choices = response.choices or []
        if not choices:
            raise AIValidationUnavailableError("Groq validator returned no completion")
        return self._parse_validation_decision(choices[0].message.content)

    async def _request_validator_mistral(self, prompt: str) -> ValidationDecision:
        if self.mistral_client is None:
            raise AIValidationUnavailableError("Mistral validator is not configured")
        response = await self.mistral_client.chat.completions.create(
            model=self.settings.mistral_model,
            temperature=0,
            max_tokens=300,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are an independent MCQ fact and ambiguity validator. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        choices = response.choices or []
        if not choices:
            raise AIValidationUnavailableError("Mistral validator returned no completion")
        return self._parse_validation_decision(choices[0].message.content)

    async def _request_validator_openai_compatible(self, prompt: str) -> ValidationDecision:
        response = await self.client.chat.completions.create(
            model=self.settings.ai_model,
            temperature=0,
            max_completion_tokens=300,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are an independent MCQ fact and ambiguity validator. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        choices = response.choices or []
        if not choices:
            raise AIValidationUnavailableError("OpenAI-compatible validator returned no completion")
        return self._parse_validation_decision(choices[0].message.content)

    async def _call_provider(self, name: str, request: Any, prompt: str) -> Any:
        """Serialize calls per provider and cool down providers that are over capacity."""
        if not hasattr(self, "_provider_locks"):
            generator_settings = getattr(self, "settings", None)
            self._request_slots = asyncio.Semaphore(int(getattr(generator_settings, "ai_max_concurrent_requests", 4)))
            self._provider_locks = {
                provider: asyncio.Lock() for provider in ("gemini", "groq", "mistral", "openai-compatible")
            }
            self._provider_cooldown_until = {}
            self._provider_next_request_at = {}
        lock = self._provider_locks[name]
        async with lock:
            now = time.monotonic()
            cooldown_until = self._provider_cooldown_until.get(name, 0.0)
            if cooldown_until > now:
                raise AIProviderRateLimitError(f"{name} is cooling down")
            next_request_at = self._provider_next_request_at.get(name, 0.0)
            if next_request_at > now:
                await asyncio.sleep(next_request_at - now)
            async with self._request_slots:
                try:
                    result = await request(prompt)
                except (AIProviderRateLimitError, APIStatusError) as exc:
                    status = getattr(exc, "status_code", None)
                    if status in {429, 502, 503, 504} or isinstance(exc, AIProviderRateLimitError):
                        generator_settings = getattr(self, "settings", None)
                        cooldown = float(getattr(generator_settings, "ai_provider_cooldown_seconds", 30))
                        self._provider_cooldown_until[name] = time.monotonic() + cooldown
                        logger.warning("Provider %s entered cooldown for %.0fs", name, cooldown)
                    raise
                finally:
                    self._provider_next_request_at[name] = time.monotonic() + float(
                        getattr(getattr(self, "settings", None), "ai_provider_min_interval_seconds", 0.5)
                    )
                return result

    async def _validate_independently(self, question: ValidQuestion, source_context: str | None = None) -> bool | None:
        settings = self.settings
        if not getattr(settings, "validator_enabled", True):
            return None
        now = time.monotonic()
        if now < getattr(self, "_validator_cooldown_until", 0.0):
            logger.info("Independent validator is in cooldown; using structural validation only")
            return None
        prompt = self._validator_prompt(question, source_context=source_context)
        providers = (
            ("groq-validator", self._request_validator_groq),
            ("mistral-validator", self._request_validator_mistral),
            ("openai-compatible-validator", self._request_validator_openai_compatible),
        )
        errors: list[str] = []
        decisions_received = 0
        threshold = float(getattr(settings, "validator_confidence_threshold", 0.70))
        for name, request in providers:
            try:
                decision = await self._call_provider(name.removesuffix("-validator"), request, prompt)
                decisions_received += 1
                if decision.correct_option_verified != question.correct_option:
                    logger.warning("%s disagreed with the generated correct option; trying the next validator", name)
                    continue
                approved = decision.approved and decision.confidence >= threshold
                if approved:
                    logger.info("%s approved MCQ after independent validation", name)
                    return True
                logger.warning("%s rejected MCQ: %s; trying the next validator", name, decision.reason or decision.issues)
            except (AIValidationUnavailableError, AIQuestionGenerationError, APIConnectionError, APITimeoutError, APIStatusError) as exc:
                errors.append(f"{name}: {type(exc).__name__}")
                logger.warning("%s unavailable; trying next validator", name)
        if decisions_received:
            logger.warning("All available validators rejected or disagreed with the MCQ")
            return False
        cooldown = int(getattr(settings, "validator_cooldown_seconds", 120))
        self._validator_cooldown_until = time.monotonic() + cooldown
        logger.warning("All independent validators unavailable; bypassing validator for %ss: %s", cooldown, ", ".join(errors))
        return None

    async def _request(self, user_prompt: str) -> dict[str, Any]:
        providers = (
            ("gemini", self._request_gemini),
            ("groq", self._request_groq),
            ("mistral", self._request_mistral),
            ("openai-compatible", self._request_openai_compatible),
        )
        errors: list[str] = []
        for name, request in providers:
            try:
                payload = await self._call_provider(name, request, user_prompt)
                logger.info("MCQ generated via %s provider", name)
                return payload
            except (AIQuestionGenerationError, APIConnectionError, APITimeoutError, APIStatusError) as exc:
                errors.append(f"{name}: {type(exc).__name__}")
                logger.warning("MCQ provider %s unavailable; trying next provider", name)
        raise AICompletionUnavailableError("All configured MCQ providers failed: " + ", ".join(errors))

    @staticmethod
    def _canonicalize_metadata(
        payload: dict[str, Any], *, subject: str, topic: str, difficulty: str, language: str
    ) -> dict[str, Any]:
        """Keep provider metadata aligned with the requested quiz scope.

        Providers sometimes translate or paraphrase metadata even when the
        question itself follows the requested prompt. Scope is selected by the
        application, so canonical metadata must come from the application.
        """
        canonical = dict(payload)
        canonical.update(subject=subject, topic=topic, difficulty=UNIFIED_EXAM_LEVEL, language=QUESTION_LANGUAGE)
        return canonical

    async def generate(
        self, *, state: str, subject: str, topic: str, question_type: str, language: str,
        previous_questions: list[str], similarity_threshold: float, source_context: str | None = None,
    ) -> ValidQuestion:
        current_facts = await self.current_affairs.facts(state=state, subject=subject) if subject in {"Current Affairs", "State Current Affairs"} else None
        prompt = self._user_prompt(
            state=state, subject=subject, topic=topic, question_type=question_type, language=QUESTION_LANGUAGE,
            previous_questions=previous_questions, current_facts=current_facts, source_context=source_context,
        )
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                payload = await self._request(prompt)
                payload = self._canonicalize_metadata(
                    payload, subject=subject, topic=topic, difficulty=UNIFIED_EXAM_LEVEL, language=language
                )
                valid = validate_question(
                    payload, expected_subject=subject, expected_topic=topic, expected_difficulty=UNIFIED_EXAM_LEVEL, expected_language=QUESTION_LANGUAGE
                )
                from bot.services.question_validator import find_similar
                if find_similar(valid.question, previous_questions, similarity_threshold):
                    raise QuestionValidationError("Question is too similar to a previous item")
                validator_result = await self._validate_independently(valid, source_context=source_context)
                if validator_result is False:
                    raise QuestionValidationError("Independent validator rejected the MCQ")
                return valid
            except AICompletionUnavailableError:
                # Retrying malformed generation can help, but a provider with no completion
                # cannot help this chat; return promptly so the quiz service can use its cache.
                raise
            except (AIQuestionGenerationError, QuestionValidationError, APIConnectionError, APITimeoutError, APIStatusError) as exc:
                last_error = exc
                logger.warning("Question-generation attempt %s rejected: %s", attempt, exc)
                prompt += "\nYour prior answer was rejected. Produce a different, valid JSON question and follow every constraint."
        raise AIQuestionGenerationError("AI could not produce a valid unique question after three attempts") from last_error

    async def close(self) -> None:
        await self.client.close()
        if self.groq_client is not None:
            await self.groq_client.close()
        if self.mistral_client is not None:
            await self.mistral_client.close()

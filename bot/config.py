"""Configuration loaded exclusively from environment variables."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from bot.data.internal_topic_master import INTERNAL_TOPIC_MASTER


class Settings(BaseSettings):
    """Application settings. Secrets are never logged or persisted."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN", min_length=20)
    database_url: str = Field(alias="DATABASE_URL")
    ai_api_key: str = Field(alias="AI_API_KEY", min_length=8)
    ai_model: str = Field(default="gpt-4.1-mini", alias="AI_MODEL")
    ai_base_url: str | None = Field(default=None, alias="AI_BASE_URL")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.6-flash", alias="GEMINI_MODEL")
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")
    mistral_api_key: str | None = Field(default=None, alias="MISTRAL_API_KEY")
    mistral_model: str = Field(default="mistral-small-latest", alias="MISTRAL_MODEL")
    mistral_base_url: str = Field(default="https://api.mistral.ai/v1", alias="MISTRAL_BASE_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(default="runtime_test.log", alias="LOG_FILE")
    timezone: str = Field(default="Asia/Kolkata", alias="TIMEZONE")
    scheduler_tick_seconds: int = Field(default=15, alias="SCHEDULER_TICK_SECONDS", ge=5, le=60)
    question_similarity_threshold: float = Field(default=0.86, alias="QUESTION_SIMILARITY_THRESHOLD", ge=0.70, le=0.99)
    news_api_key: str | None = Field(default=None, alias="NEWS_API_KEY")
    news_api_url: str = Field(default="https://newsapi.org/v2/top-headlines", alias="NEWS_API_URL")
    admin_user_ids: str | None = Field(default=None, alias="ADMIN_USER_IDS")
    validator_enabled: bool = Field(default=True, alias="VALIDATOR_ENABLED")
    validator_confidence_threshold: float = Field(default=0.70, alias="VALIDATOR_CONFIDENCE_THRESHOLD", ge=0.5, le=1.0)
    validator_cooldown_seconds: int = Field(default=120, alias="VALIDATOR_COOLDOWN_SECONDS", ge=30, le=3600)
    source_storage_dir: str = Field(default="source_storage", alias="SOURCE_STORAGE_DIR")
    source_max_pdf_mb: int = Field(default=50, alias="SOURCE_MAX_PDF_MB", ge=1, le=500)
    source_ocr_enabled: bool = Field(default=False, alias="SOURCE_OCR_ENABLED")
    source_ingest_timeout_seconds: int = Field(default=1800, alias="SOURCE_INGEST_TIMEOUT_SECONDS", ge=60, le=7200)
    source_group_id: int | None = Field(default=None, alias="SOURCE_GROUP_ID")
    bulk_source_group_id: int | None = Field(default=None, alias="BULK_SOURCE_GROUP_ID")
    official_quiz_config_group_id: int | None = Field(default=None, alias="OFFICIAL_QUIZ_CONFIG_GROUP_ID")
    official_quiz_play_group_id: int | None = Field(default=None, alias="OFFICIAL_QUIZ_PLAY_GROUP_ID")
    question_pool_enabled: bool = Field(default=True, alias="QUESTION_POOL_ENABLED")
    question_pool_target: int = Field(default=10, alias="QUESTION_POOL_TARGET", ge=1, le=100)
    question_pool_fill_per_tick: int = Field(default=1, alias="QUESTION_POOL_FILL_PER_TICK", ge=1, le=10)
    question_pool_max_groups_per_tick: int = Field(default=2, alias="QUESTION_POOL_MAX_GROUPS_PER_TICK", ge=1, le=20)
    ai_max_concurrent_requests: int = Field(default=4, alias="AI_MAX_CONCURRENT_REQUESTS", ge=1, le=32)
    ai_provider_cooldown_seconds: int = Field(default=30, alias="AI_PROVIDER_COOLDOWN_SECONDS", ge=5, le=3600)
    ai_provider_min_interval_seconds: float = Field(default=0.5, alias="AI_PROVIDER_MIN_INTERVAL_SECONDS", ge=0.0, le=60.0)
    support_channel_url: str = Field(default="https://t.me/GSI_QUIZ", alias="SUPPORT_CHANNEL_URL")
    support_group_url: str = Field(default="https://t.me/+OzztqZ23h8AxYWZl", alias="SUPPORT_GROUP_URL")
    owner_contact_url: str = Field(default="https://t.me/Global_X_SohaN", alias="OWNER_CONTACT_URL")

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            value = "postgresql+asyncpg://" + value.removeprefix("postgres://")
        elif value.startswith("postgresql://"):
            value = "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        if value.startswith("postgresql+asyncpg://"):
            # Render commonly supplies libpq's `sslmode=require` query
            # parameter. asyncpg rejects that keyword and expects `ssl`.
            # Translate it at the configuration boundary so the rest of the
            # database layer can use one consistent async URL.
            parts = urlsplit(value)
            query_pairs = parse_qsl(parts.query, keep_blank_values=True)
            sslmode: str | None = None
            normalized_pairs: list[tuple[str, str]] = []
            has_ssl = False
            for key, item in query_pairs:
                if key == "sslmode":
                    sslmode = item
                    continue
                if key == "channel_binding":
                    # channel_binding is a libpq keyword and is not accepted
                    # by the installed asyncpg connect() implementation.
                    continue
                if key == "ssl":
                    has_ssl = True
                normalized_pairs.append((key, item))
            if sslmode and not has_ssl:
                # Render uses `require`; preserve other libpq modes as the
                # closest asyncpg string value when they are supplied.
                normalized_pairs.append(("ssl", sslmode))
            value = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(normalized_pairs), parts.fragment))
            return value
        if value.startswith("sqlite:///" ) and not value.startswith("sqlite+aiosqlite:///" ):
            return "sqlite+aiosqlite:///" + value.removeprefix("sqlite:///")
        if not value.startswith("sqlite+aiosqlite://"):
            raise ValueError("DATABASE_URL must be a PostgreSQL or SQLite SQLAlchemy async URL")
        return value

    @property
    def global_admin_ids(self) -> set[int]:
        if not self.admin_user_ids:
            return set()
        return {int(item.strip()) for item in self.admin_user_ids.split(",") if item.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


VALID_INTERVALS = {10, 15, 20, 30, 60}
DEFAULT_LANGUAGE = "Hindi"
QUESTION_LANGUAGE = "Hindi"
VALID_LANGUAGES = {"English", "Hindi"}
LANGUAGE_ALIASES = {"english": "English", "en": "English", "hindi": "Hindi", "hi": "Hindi", "हिंदी": "Hindi", "हिन्दी": "Hindi"}
UNIFIED_EXAM_LEVEL = "Exam"
VALID_DIFFICULTIES = {UNIFIED_EXAM_LEVEL}
LEGACY_DIFFICULTIES = {"Easy", "Medium", "Hard", "Advanced", "Expert"}
VALID_QUESTION_TYPES = {
    "Conceptual", "Analytical", "Statement-based", "Assertion-Reason",
    "Match-the-following", "Chronology/order", "Case-based", "Multiple-statement",
}
XP_DEFAULTS = {"Exam": 10, "Easy": 10, "Medium": 10, "Hard": 10, "Advanced": 10, "Expert": 10}
STREAK_BONUSES = {3: 5, 5: 10, 10: 25}
XP_DAILY_CHALLENGE_BONUS = 20
XP_DAILY_TARGET = 10
XP_LEVELS = (
    (0, "New Learner", "नया विद्यार्थी"),
    (500, "Regular Scholar", "नियमित विद्यार्थी"),
    (1500, "Focused Scholar", "केंद्रित विद्यार्थी"),
    (3000, "Exam Warrior", "परीक्षा योद्धा"),
    (6000, "Elite Scholar", "एलीट विद्यार्थी"),
    (10000, "Master Scholar", "मास्टर विद्यार्थी"),
    (20000, "Grand Scholar", "ग्रैंड स्कॉलर"),
)

VALID_STATES = {
    "All India", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
    "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha",
    "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh",
    "Uttarakhand", "West Bengal", "General",
}
STATE_ALIASES = {
    "all india": "All India", "india": "All India", "up": "Uttar Pradesh", "mp": "Madhya Pradesh",
    "uk": "Uttarakhand", "ap": "Andhra Pradesh", "general": "General",
}

NATIONAL_SUBJECTS = (
    "All India GK", "Indian Polity", "Indian History", "Indian Geography", "General Science", "Economics", "Current Affairs",
    "Environment", "Computer", "Reasoning", "General Knowledge", "Indian Culture",
)
STATE_SPECIFIC_SUBJECTS = (
    "State GK", "State History", "State Art & Culture", "State Geography", "State Polity & Administration", "State Current Affairs",
)
VALID_SUBJECTS = {
    *NATIONAL_SUBJECTS, *STATE_SPECIFIC_SUBJECTS, "State History & Culture", "History", "Geography", "All India GK", "Constitution", "Physics", "Chemistry", "Biology",
    "World Geography", "World History",
}
SUBJECT_ALIASES = {
    "all india gk": "All India GK", "all india general knowledge": "All India GK", "india gk": "All India GK",
    "polity": "Indian Polity", "indian polity": "Indian Polity", "science": "General Science",
    "gk": "General Knowledge", "state gk": "State GK", "economy": "Economics",
    "computer science": "Computer", "culture": "Indian Culture", "भारत gk": "All India GK", "state history & culture": "State History & Culture",
}

DEFAULT_SUBJECTS = ["Indian Polity", "Indian History", "Indian Geography", "General Science"]
DEFAULT_XP_MAP = XP_DEFAULTS.copy()
OFFICIAL_QUIZ_CONFIG_GROUP_ID = -1003511361627
OFFICIAL_QUIZ_PLAY_GROUP_ID = -1003799884627
GSI_HONOR_TAG = "⟦𝙂𝙎𝙄✦⟧"
GSI_HONOR_MEANING = "Grand Scholar of India"
STAR_TITLE = "Star Quizzer"

EXAM_LEVEL_GUIDANCE = "Use one serious unified exam-level standard. Prefer precise, less-obvious but syllabus-grounded facts—such as material, date, location, dynasty, person, feature, institution, sequence, or classification—over generic definitions. Make factual recall the majority and use close same-topic distractors that differ by one checkable detail. Never rely on ambiguity or unsupported trivia."

SYLLABUS_TOPIC_MAP = {
    "State GK": ("State symbols and identity", "Districts and administrative divisions", "Major cities and landmarks", "Personalities and awards", "Fairs, festivals and folk traditions", "Natural resources and industries", "State institutions and schemes"),
    "State History": ("Ancient and medieval history", "Modern history and freedom movement", "Dynasties and rulers", "Major historical wars and treaties", "1857 revolt", "Freedom movement", "Peasant and tribal movements", "Social and religious reform movements", "State formation and reorganization", "Historical personalities"),
    "State Art & Culture": ("Forts and palaces", "Ancient monuments and archaeological sites", "Temple architecture", "Buddhist and Jain architecture", "Painting styles", "Handicrafts", "Folk deities and goddesses", "Saints and sects", "Folk dances", "Folk theatre", "Folk instruments", "Folk music", "Fairs and festivals", "Customs and traditions", "Dress and ornaments", "Languages and dialects", "Folk literature", "Literature and writers", "Cultural institutions", "UNESCO heritage sites"),
    "State History & Culture": ("Ancient and medieval history", "Modern history and freedom movement", "Dynasties and rulers", "Architecture and heritage", "Art, literature and languages", "Folk music, dance and theatre", "Religious and cultural traditions"),
    "State Geography": ("Physiographic divisions", "Rivers and drainage", "Climate and rainfall", "Soils and agriculture", "Minerals and energy resources", "National parks and biodiversity", "District geography and map locations"),
    "State Polity & Administration": ("Governor and state executive", "State legislature", "High Court and judiciary", "Local self-government", "State commissions and bodies", "Administrative structure", "Constitutional and statutory provisions"),
    "State Current Affairs": ("Government decisions and programmes", "Awards, appointments and achievements", "Infrastructure and development", "Sports and cultural events", "Environment and public initiatives"),
    "All India GK": ("Indian Polity", "Indian Geography", "Indian History", "Indian Culture", "Current Affairs"),
    "Current Affairs": ("National government decisions", "International developments", "Awards, appointments and achievements", "Economy and infrastructure", "Science, environment and sports"),
    "Indian Polity": ("Preamble and constitutional philosophy", "Fundamental Rights and Duties", "Directive Principles", "Parliament and legislative procedure", "President, Prime Minister and Council of Ministers", "Judiciary and judicial review", "Federalism and centre-state relations", "Constitutional bodies and elections", "Emergency provisions and amendments", "Local governance"),
    "History": ("Indus Valley and ancient India", "Vedic age and Mahajanapadas", "Maurya and Gupta periods", "Medieval kingdoms and culture", "Delhi Sultanate and Mughals", "Regional powers", "Modern India and colonial rule", "Freedom struggle", "Socio-religious reform movements", "Art and cultural heritage"),
    "Indian History": ("Indus Valley and ancient India", "Vedic age and Mahajanapadas", "Maurya and Gupta periods", "Medieval kingdoms and culture", "Delhi Sultanate and Mughals", "Regional powers", "Modern India and colonial rule", "Freedom struggle", "Socio-religious reform movements", "Art and cultural heritage"),
    "Geography": ("Earth and geomorphology", "Climate and monsoon", "Oceans and water resources", "Indian physiography", "Rivers and drainage", "Soils and natural vegetation", "Agriculture and minerals", "Population and settlements", "World geography and mapping"),
    "Indian Geography": ("Indian physiography", "Himalayas and northern plains", "Peninsular plateau and coastal plains", "Indian rivers and drainage", "Indian climate and monsoon", "Soils and natural vegetation", "Agriculture and minerals", "Population and settlements", "Indian mapping and locations"),
    "General Science": ("Physics in daily life", "Motion, force and energy", "Matter and chemistry", "Acids, bases and salts", "Human biology", "Plants and animals", "Health and nutrition", "Environment and ecology", "Space and technology"),
    "Economics": ("Basic economic concepts", "National income and growth", "Inflation and monetary policy", "Banking and financial system", "Budget and fiscal policy", "Taxation and public finance", "Agriculture and rural economy", "Industry and infrastructure", "External sector and trade", "Poverty, employment and inclusion"),
    "Environment": ("Ecosystem and food chains", "Biodiversity and conservation", "Protected areas and species", "Climate change", "Pollution and waste", "Environmental laws and institutions", "Sustainable development", "International environmental conventions"),
    "Computer": ("Computer fundamentals", "Hardware and input-output devices", "Operating systems and software", "Internet and networking", "Cybersecurity", "Office productivity tools", "Databases and cloud basics", "Digital governance"),
    "Reasoning": ("Analogy and classification", "Number and letter series", "Coding-decoding", "Direction and distance", "Blood relations", "Syllogism", "Statements and conclusions", "Seating arrangement", "Ranking and order", "Data sufficiency"),
    "General Knowledge": ("National symbols and institutions", "Awards and honours", "Sports", "Books and authors", "Important days and organizations", "Science and technology", "Art and culture", "India and world facts"),
    "Indian Culture": ("Classical arts", "Folk traditions", "Architecture", "Religion and philosophy", "Literature and languages", "UNESCO heritage", "Festivals and cultural institutions"),
    "Constitution": ("Constitutional history", "Preamble", "Rights and duties", "Union government", "State government", "Judiciary", "Amendments and emergency provisions"),
    "Physics": ("Mechanics", "Heat and thermodynamics", "Light and optics", "Sound", "Electricity and magnetism", "Modern physics"),
    "Chemistry": ("Matter and atomic structure", "Chemical bonding", "Acids, bases and salts", "Metals and non-metals", "Carbon compounds", "Periodic classification", "Chemistry in daily life"),
    "Biology": ("Cell and tissues", "Human body systems", "Plant physiology", "Genetics and evolution", "Microorganisms", "Health and disease", "Ecology"),
    "World Geography": ("Continents and oceans", "Landforms", "Climate regions", "Rivers and lakes", "Resources and agriculture", "Countries, capitals and mapping"),
    "World History": ("Ancient civilizations", "Renaissance and Reformation", "Industrial Revolution", "World wars", "Revolutions", "Cold War and international order"),
}


EXAM_STYLE_SUBJECT_GUIDANCE = {
    "State GK": "Focus on stable state facts: districts, landmarks, institutions, personalities, resources, fairs, awards, and official symbols.",
    "State History": "Focus on state dynasties, movements, chronology, historical personalities, battles, reforms, and the freedom movement.",
    "State Art & Culture": "Focus on state architecture, monuments, art forms, literature, folk traditions, music, dance, festivals, and cultural institutions.",
    "State History & Culture": "Focus on state dynasties, movements, architecture, art forms, literature, folk traditions, and historical chronology for backward-compatible saved groups.",
    "State Geography": "Focus on physiography, rivers, climate, soils, crops, minerals, protected areas, and district-level geography.",
    "State Polity & Administration": "Focus on the state constitutional and administrative structure, local governance, commissions, and stable policy frameworks.",
    "State Current Affairs": "Use only source-backed current facts supplied by the application; never invent a recent event or scheme.",
    "All India GK": "Rotate across Indian Polity, Indian Geography, Indian History, Indian Culture, and source-backed Current Affairs. Keep the questions India-wide and competitive-exam focused.",
    "Indian Polity": "Focus on the Constitution, articles, schedules, constitutional bodies, Parliament, judiciary, federalism, and governance concepts.",
    "History": "Focus on chronology, causes and effects, sources, movements, personalities, and cultural context from Indian history.",
    "Indian History": "Focus on chronology, causes and effects, sources, movements, personalities, and cultural context from Indian history.",
    "Geography": "Focus on map-linked physical and Indian geography, resources, climate, agriculture, and human geography concepts.",
    "Indian Geography": "Focus on map-linked physical and Indian geography, resources, climate, agriculture, and human geography concepts.",
    "General Science": "Focus on school-to-competitive-exam science concepts and real-world applications with a single verifiable answer.",
    "Economics": "Focus on foundational Indian economy, fiscal and monetary concepts, institutions, data interpretation, and public policy basics.",
    "Environment": "Focus on ecology, biodiversity, climate concepts, conservation instruments, and Indian environmental institutions.",
    "Reasoning": "Use an exam-style logical, analytical, coding-decoding, series, direction, relation, or syllogism problem with all required information in the question.",
    "Computer": "Focus on fundamentals, hardware, software, networking, cybersecurity, office tools, and digital-governance basics.",
}


def syllabus_topics_for(state: str, subject: str) -> tuple[str, ...]:
    """Return hidden internal topics for the selected state/subject with legacy fallback."""
    scope = "All India" if state in {"All India", "General"} else state
    internal_subjects = INTERNAL_TOPIC_MASTER.get(scope, {})
    topics = list(internal_subjects.get(subject, ()))
    if subject == "State GK" and state not in {"All India", "General"}:
        for internal_subject in ("State History", "State Art & Culture", "State Geography", "State Polity & Administration", "State Current Affairs"):
            for topic in internal_subjects.get(internal_subject, ()):
                if topic not in topics:
                    topics.append(topic)
    if subject == "State History & Culture" and state not in {"All India", "General"}:
        for internal_subject in ("State History", "State Art & Culture"):
            for topic in internal_subjects.get(internal_subject, ()):
                if topic not in topics:
                    topics.append(topic)
    if subject == "All India GK" and state in {"All India", "General"}:
        for internal_subject in ("Indian Polity", "Geography", "History", "Indian Culture", "Current Affairs"):
            for topic in internal_subjects.get(internal_subject, ()):
                if topic not in topics:
                    topics.append(topic)
        if not topics:
            topics = ["Indian Polity", "Indian Geography", "Indian History", "Indian Culture", "Current Affairs"]
    if subject == "General Knowledge" and state in {"All India", "General"}:
        for internal_subject in ("History", "Geography", "Indian Culture", "Indian Polity", "Current Affairs"):
            for topic in internal_subjects.get(internal_subject, ()):
                if topic not in topics:
                    topics.append(topic)
    if not topics:
        topics = list(SYLLABUS_TOPIC_MAP.get(subject, (f"{subject} fundamentals",)))
    if subject.startswith("State ") and state not in {"All India", "General"}:
        return tuple(f"{state}: {topic}" for topic in topics)
    return tuple(topics)


def syllabus_source_guidance(state: str, subject: str) -> str:
    if state == "Rajasthan":
        state_basis = "For Rajasthan-specific material, use stable facts commonly taught in RBSE resources and official Rajasthan references."
    elif state not in {"All India", "General"}:
        state_basis = f"For {state}-specific material, use stable facts commonly taught in the state-board syllabus, official state references, and standard state-exam preparation resources."
    else:
        state_basis = "For national material, use stable NCERT-level concepts and widely accepted competitive-exam syllabus facts."
    if subject in {"Current Affairs", "State Current Affairs"}:
        return "Use only application-supplied source-backed current facts; do not infer or invent a current event."
    return state_basis + " Do not claim a book, chapter, page, guide book, or past-paper source unless it was supplied to the application."


def exam_style_guidance(state: str, subject: str) -> str:
    """Return a transparent competitive-exam practice profile without claiming a copied past-paper source."""
    if state in {"All India", "General"}:
        state_guidance = "Use an India-wide competitive-exam standard; avoid state-specific facts."
    else:
        state_guidance = (
            f"Use the standard of a serious {state} state-level competitive examination. "
            f"For state-specific subjects, keep the fact pattern explicitly tied to {state}."
        )
    subject_guidance = EXAM_STYLE_SUBJECT_GUIDANCE.get(
        subject, "Use a syllabus-aligned competitive-exam concept with a uniquely verifiable answer."
    )
    return f"{state_guidance} {subject_guidance} {EXAM_LEVEL_GUIDANCE} {syllabus_source_guidance(state, subject)}"


def subjects_for_state(state: str) -> list[str]:
    """Return the selectable subject catalog appropriate to a national or state-focused study profile."""
    if state in {"All India", "General"}:
        return list(NATIONAL_SUBJECTS)
    national_subjects = [subject for subject in NATIONAL_SUBJECTS if subject != "All India GK"]
    return [*STATE_SPECIFIC_SUBJECTS, *national_subjects]


def default_subjects_for_state(state: str) -> list[str]:
    """Return the single umbrella subject that activates hidden syllabus rotation."""
    if state in {"All India", "General"}:
        return ["All India GK"]
    return ["State GK"]


def toggle_subject_selection(state: str, selected_subjects: list[str] | None, subject: str) -> list[str]:
    """Toggle a subject while keeping the state/all-India umbrella as the default fallback."""
    umbrella = "All India GK" if state in {"All India", "General"} else "State GK"
    selected = list(dict.fromkeys(selected_subjects or []))
    if subject == umbrella:
        return [umbrella]
    if selected == [umbrella]:
        selected = []
    if subject in selected:
        selected.remove(subject)
    else:
        selected.append(subject)
    return selected or [umbrella]


def display_subject_for_state(state: str, subject: str) -> str:
    """Return a friendly UI label without changing the canonical subject value."""
    if state not in {"All India", "General"} and subject.startswith("State "):
        return f"{state} {subject.removeprefix('State ')}"
    if subject == "History":
        return "Indian History"
    if subject == "Geography":
        return "Indian Geography"
    return subject


def normalize_language(value: str) -> str | None:
    return LANGUAGE_ALIASES.get(value.strip().casefold())


def normalize_state(value: str) -> str | None:
    normalized = value.strip().casefold()
    return STATE_ALIASES.get(normalized) or next(
        (state for state in VALID_STATES if state.casefold() == normalized), None
    )


def normalize_subject(value: str) -> str | None:
    normalized = value.strip().casefold()
    return SUBJECT_ALIASES.get(normalized) or next(
        (subject for subject in VALID_SUBJECTS if subject.casefold() == normalized), None
    )

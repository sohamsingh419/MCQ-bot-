"""Text normalization helpers shared by source ingestion and persistence."""
from __future__ import annotations


def sanitize_text(value: str | None) -> str:
    """Remove NUL characters that PostgreSQL text/JSON values cannot store."""
    return (value or "").replace("\x00", "")

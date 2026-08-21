from bot.handlers.admin import _log_snapshot, _report_chunks


def test_log_snapshot_extracts_generation_and_errors() -> None:
    snapshot = _log_snapshot(
        "MCQ generated via gemini provider\n"
        "groq-validator unavailable; trying next validator\n"
        "No unseen question available for group\n"
        "ERROR scheduler failed\n"
        "Traceback (most recent call last):\n"
    )
    assert snapshot["generated"] == ["gemini"]
    assert snapshot["unavailable"] == 1
    assert snapshot["no_fresh"] == 1
    assert snapshot["errors"]


def test_report_chunks_stay_below_telegram_safe_limit() -> None:
    chunks = _report_chunks("\n\n".join(["section " + ("x" * 900) for _ in range(6)]), limit=1000)
    assert len(chunks) > 1
    assert all(len(chunk) <= 1000 for chunk in chunks)

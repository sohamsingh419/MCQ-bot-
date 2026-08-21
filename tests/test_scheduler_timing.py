from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from bot.services.scheduler import SchedulerService


def test_mock_final_results_wait_for_last_poll_timer() -> None:
    now = datetime.now(timezone.utc)
    mock = SimpleNamespace(round_ends_at=now + timedelta(seconds=8))
    assert SchedulerService._mock_round_has_expired(mock, now) is False
    assert SchedulerService._mock_round_has_expired(mock, now + timedelta(seconds=9)) is True


def test_mock_final_results_allow_missing_round_deadline_fallback() -> None:
    now = datetime.now(timezone.utc)
    mock = SimpleNamespace(round_ends_at=None)
    assert SchedulerService._mock_round_has_expired(mock, now) is True

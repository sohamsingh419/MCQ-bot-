from datetime import date, datetime, timezone
from types import SimpleNamespace

from bot.services.quiz import QuizService
from bot.services.scheduler import SchedulerService


def test_quiet_hours_use_configured_timezone() -> None:
    service = QuizService.__new__(QuizService)
    service.settings = SimpleNamespace(timezone="Asia/Kolkata")
    midnight_ist = datetime(2026, 8, 18, 0, 30, tzinfo=timezone.utc)
    morning_ist = datetime(2026, 8, 18, 1, 0, tzinfo=timezone.utc)
    after_quiet_ist = datetime(2026, 8, 18, 2, 0, tzinfo=timezone.utc)
    assert service.is_quiet_hours(midnight_ist) is True
    assert service.is_quiet_hours(morning_ist) is True
    assert service.is_quiet_hours(after_quiet_ist) is False


def test_scheduler_quiet_hours_boundary() -> None:
    assert SchedulerService.is_quiet_hours(datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc).astimezone()) is True
    assert SchedulerService.is_quiet_hours(datetime(2026, 8, 18, 7, 0, tzinfo=timezone.utc).astimezone()) is False


def test_daily_routine_messages_are_decorated_and_slot_specific() -> None:
    day = date(2026, 8, 18)
    night = SchedulerService._routine_message("night", day)
    morning = SchedulerService._routine_message("morning", day)
    assert "<b>" in night and "🌙" in night and "Good night, all friends!" in night
    assert "<b>" in morning and "🌅" in morning and "Good morning, friends!" in morning
    assert SchedulerService._motivation_for_slot("night", day) in night
    assert SchedulerService._motivation_for_slot("morning", day) in morning
    assert SchedulerService._motivation_for_slot("night", day) != SchedulerService._motivation_for_slot("morning", day)
    assert night != morning

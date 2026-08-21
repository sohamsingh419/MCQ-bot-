from types import SimpleNamespace

from bot.handlers.source import _is_bot_admin, _is_configured_source_group


def test_source_intake_requires_the_single_configured_group() -> None:
    settings = SimpleNamespace(source_group_id=-100987654321, global_admin_ids={7028236763})
    assert _is_configured_source_group(-100987654321, settings) is True
    assert _is_configured_source_group(-100111111111, settings) is False
    assert _is_configured_source_group(-100987654321, SimpleNamespace(source_group_id=None)) is False


def test_source_intake_requires_global_bot_admin_not_group_admin() -> None:
    settings = SimpleNamespace(source_group_id=-100987654321, global_admin_ids={7028236763})
    assert _is_bot_admin(7028236763, settings) is True
    assert _is_bot_admin(123456789, settings) is False

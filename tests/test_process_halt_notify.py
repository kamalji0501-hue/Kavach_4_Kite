"""Crash-exit Telegram targets (OQ-P1-22 — notify wired after SARANSH)."""

from __future__ import annotations

from core.process_halt_notify import halt_notify_message, halt_notify_targets


def test_halt_targets_core_vs_saransh() -> None:
    assert halt_notify_targets("kavach") == [("kavach", "batman_alerts")]
    assert halt_notify_targets("saransh") == [("saransh", "non_critical")]


def test_halt_message_includes_start_bat() -> None:
    msg = halt_notify_message("saransh", error_summary="boom")
    assert "Saransh.bat" in msg
    assert "boom" in msg

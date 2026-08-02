"""Default JAGRAN severity routing per domain/scenario (independence-friendly)."""

from __future__ import annotations

# (domain, scenario) -> severity: info | warning | critical
_DEFAULT_SEVERITY: dict[tuple[str, str], str] = {
    ("drishti", "ltp_fetch_failure"): "warning",
    ("drishti", "nifty_ltp_stale_cache"): "warning",
    ("drishti", "nifty_ltp_stale_price"): "warning",
    ("drishti", "stale_token"): "critical",
    ("drishti", "token_update_failure"): "critical",
    ("drishti", "broker_connection_failure"): "warning",
    ("drishti", "websocket_retry_exhaustion"): "warning",
    ("kavach", "order_rejection"): "critical",
    ("kavach", "margin_shortfall"): "critical",
    ("kavach", "archive_completion_failure"): "critical",
    ("kavach", "managed_qty_mismatch"): "critical",
    ("kavach", "hedge_box_execution_failure"): "critical",
    ("kavach", "hedge_box_verification_failure"): "warning",
    ("kavach", "module_error"): "warning",
    ("kavach", "manual_protect_full_exit"): "critical",
    ("kavach2", "order_rejection"): "critical",
    ("kavach2", "margin_shortfall"): "critical",
    ("kavach2", "archive_completion_failure"): "critical",
    ("kavach2", "managed_qty_mismatch"): "critical",
    ("kavach2", "hedge_box_execution_failure"): "critical",
    ("kavach2", "hedge_box_verification_failure"): "warning",
    ("kavach2", "module_error"): "warning",
    ("kavach2", "manual_protect_full_exit"): "critical",
    ("kavach2", "ato_order_failure"): "critical",
    ("jagran", "test_alert"): "info",
    ("start_all", "start_all_timeout"): "warning",
    ("start_all", "start_all_abort"): "warning",
    ("stop_all", "stop_all_incomplete"): "warning",
    ("main", "heartbeat_loop_error"): "critical",
}


def resolve_incident_severity(
    domain: str,
    scenario: str,
    explicit: str | None = None,
) -> str:
    """Map generic 'error' to domain-specific severity when no explicit override."""
    if explicit and explicit.lower() not in ("error", "err", ""):
        return explicit.lower()
    key = (domain.lower(), scenario.lower())
    return _DEFAULT_SEVERITY.get(key, "warning")

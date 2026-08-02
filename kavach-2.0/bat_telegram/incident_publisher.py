from __future__ import annotations

import csv
import json
import logging
import threading
import zoneinfo
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from telegram import Bot

from core.telegram_delivery import send_with_retry

logger = logging.getLogger("batman.incidents")

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_INCIDENTS_LOCK = threading.Lock()
_LEDGER_LOCK = threading.Lock()
_EXPORT_RETRY_STATE: dict[str, dict[str, Any]] = {}

_INCIDENT_LEDGER_HEADERS = [
    "ts_ist",
    "date_ist",
    "event_type",
    "status_label",
    "source",
    "scenario",
    "severity",
    "category",
    "title",
    "error_message",
    "next_action",
    "resolution_message",
    "incident_id",
    "repeat_count",
    "routed_to_source",
    "source_delivery_ok",
    "routed_to_jagran",
    "jagran_delivery_ok",
]


def _phase1_root() -> Path:
    """Parent Phase 1 tree (JAGRAN token + run_jagran live here; kavach-2.0 is a subproject)."""
    from core.batman_mode import workspace_root

    base = workspace_root().resolve()
    if base.name == "kavach-2.0":
        parent = base.parent
        if (parent / "run_jagran.py").is_file() or (
            parent / "telegram" / "bots" / "jagran" / "token.env"
        ).is_file():
            return parent
    return base


def _jagran_params_path() -> Path:
    phase1 = _phase1_root() / "telegram" / "bots" / "jagran" / "params.json"
    if phase1.is_file():
        return phase1
    return Path(__file__).resolve().parent.parent / "telegram" / "bots" / "jagran" / "params.json"


def _jagran_token_path() -> Path:
    phase1 = _phase1_root() / "telegram" / "bots" / "jagran" / "token.env"
    if phase1.is_file():
        return phase1
    return Path(__file__).resolve().parent.parent / "telegram" / "bots" / "jagran" / "token.env"


def _incident_ledger_dir() -> Path:
    from core.batman_mode import incidents_root

    return incidents_root()


@dataclass
class _IncidentState:
    fingerprint: str
    first_seen: datetime
    last_sent: datetime
    repeat_count: int
    routed_to_jagran: bool
    source: str
    scenario: str
    severity: str
    category: str
    title: str


_ACTIVE_INCIDENTS: dict[str, _IncidentState] = {}

_KAVACH_FAMILY_SCENARIOS: set[str] = {
    "margin_shortfall",
    "order_rejection",
    "archive_completion_failure",
    "hedge_box_execution_failure",
    "hedge_box_verification_failure",
    "managed_qty_mismatch",
    "module_error",
    "ato_order_failure",
    "manual_protect_full_exit",
    "batman_cleanup_failed",
    "position_book_unreadable",
    "position_book_recovered",
    "log_error",
    "incident_repeat_escalation",
}

_JAGRAN_ALLOWLIST: dict[str, set[str]] = {
    "drishti": {
        "ltp_fetch_failure",
        "broker_connection_failure",
        "stale_token",
        "token_update_failure",
        "websocket_retry_exhaustion",
        "nifty_ltp_stale_price",
        "nifty_ltp_stale_cache",
        "incident_repeat_escalation",
    },
    "kavach": set(_KAVACH_FAMILY_SCENARIOS),
    "kavach2": set(_KAVACH_FAMILY_SCENARIOS),
    "main": {
        "heartbeat_loop_error",
        "module_offline_*",
        "logging_sink_failure_*",
        "incident_repeat_escalation",
    },
    "jagran": {
        "test_alert",
        "incident_repeat_escalation",
        "log_error",
    },
    "launcher": {
        "start_all_failure",
        "start_all_timeout",
        "start_all_abort",
        "stop_all_failure",
        "stop_all_incomplete",
        "incident_repeat_escalation",
    },
}


def append_ledger_row_sync(row: dict[str, Any], ts: datetime | None = None) -> None:
    """Append one row to the global incident ledger (sync — for incident_tracker)."""
    when = ts or datetime.now(_IST)
    _append_incident_ledger_row(row, when, _load_jagran_params())


def _load_jagran_params() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "enabled": True,
        "dedup_window_seconds": 300,
        "still_failing_interval_seconds": 1800,
        "send_recovery": True,
        "ledger_write_csv": True,
        "ledger_export_excel": True,
        "ledger_retry_interval_seconds": 180,
        "ledger_max_export_retries": 3,
    }
    path = _jagran_params_path()
    if not path.exists():
        return defaults
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            defaults.update(raw)
    except Exception as exc:
        logger.warning("JAGRAN params load failed: %s", exc)
    return defaults


def _can_route_to_jagran(source: str, scenario: str) -> bool:
    allowed = _JAGRAN_ALLOWLIST.get(source.lower(), set())
    if scenario in allowed:
        return True
    for pattern in allowed:
        if pattern.endswith("*") and scenario.startswith(pattern[:-1]):
            return True
    return False


def _kavach_deployment_confirmed() -> bool:
    try:
        from core.batman_mode import state_path

        path = state_path()
        if not path.exists():
            return False
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        deployment = data.get("deployment") or {}
        return bool(deployment.get("confirmed", False))
    except Exception:
        return False


def active_incident_count() -> int:
    with _INCIDENTS_LOCK:
        return len(_ACTIVE_INCIDENTS)


def active_incident_ids() -> list[str]:
    with _INCIDENTS_LOCK:
        return sorted(_ACTIVE_INCIDENTS.keys())


def _incident_key(source: str, scenario: str) -> str:
    return f"{source.lower()}::{scenario}"


def _format_timestamp(ts: datetime) -> str:
    return ts.astimezone(_IST).strftime("%H:%M IST, %d %b %Y")


def _normalize_fingerprint(title: str, error_message: str) -> str:
    return f"{title.strip()}::{error_message.strip()}".lower()


def _build_error_sentence(part: str, timestamp: datetime, error_message: str) -> str:
    return (
        f"{part} has thrown an error at {_format_timestamp(timestamp)}. "
        f"Error message: {error_message}"
    )


def _build_alert_text(
    *,
    part: str,
    severity: str,
    category: str,
    title: str,
    error_message: str,
    first_seen: datetime,
    repeat_count: int,
    next_action: str,
    incident_key: str,
    status_label: str,
) -> str:
    return (
        f"[{status_label}] {part} | {severity.upper()} | {category}\n"
        f"{title}\n"
        f"{_build_error_sentence(part, first_seen, error_message)}\n"
        f"First seen: {_format_timestamp(first_seen)}\n"
        f"Repeat count: {repeat_count}\n"
        f"Incident ID: {incident_key}\n"
        f"Next action: {next_action}"
    )


async def _send_message(bot, chat_id: str, text: str) -> None:
    ok = await send_with_retry(
        bot.send_message,
        chat_id=chat_id,
        text=text,
        log_prefix="Incident source delivery",
    )
    if not ok:
        raise RuntimeError("Incident source delivery failed after retries")


async def _send_to_jagran(text: str) -> bool:
    token_path = _jagran_token_path()
    if not token_path.exists():
        logger.warning("JAGRAN publish skipped: token missing at %s", token_path)
        return False
    try:
        from bat_telegram.loader import load_bot_config

        cfg = load_bot_config("jagran", reload_token=True, reload_params=True)
        bot = Bot(token=cfg.bot_token)
        chat_id = cfg.chat_id
    except Exception:
        from dotenv import dotenv_values

        vals = dotenv_values(token_path)
        bot_token = (vals.get("JAGRAN_BOT_TOKEN") or vals.get("BOT_TOKEN") or "").strip()
        chat_id = (vals.get("JAGRAN_CHAT_ID") or vals.get("CHAT_ID") or "").strip()
        if not bot_token or not chat_id:
            logger.warning("JAGRAN publish skipped: token/chat incomplete in %s", token_path)
            return False
        bot = Bot(token=bot_token)
    try:
        return await send_with_retry(
            bot.send_message,
            chat_id=chat_id,
            text=text,
            log_prefix="JAGRAN incident publish",
        )
    except Exception as exc:
        logger.warning("JAGRAN publish failed: %s", exc)
        return False


def _ledger_csv_path(ts: datetime) -> Path:
    return _incident_ledger_dir() / f"incident_ledger_{ts.strftime('%Y%m%d')}.csv"


def _ledger_xlsx_path(ts: datetime) -> Path:
    return _incident_ledger_dir() / f"incident_ledger_{ts.strftime('%Y%m%d')}.xlsx"


def _ledger_stream_path(ts: datetime) -> Path:
    return _incident_ledger_dir() / f"incident_ledger_{ts.strftime('%Y%m%d')}.log"


def _stream_line(row: dict[str, Any]) -> str:
    return (
        f"{row.get('ts_ist', '')} | {row.get('event_type', '')} | "
        f"{row.get('status_label', '')} | {row.get('source', '')} | "
        f"{row.get('scenario', '')} | {row.get('severity', '')} | "
        f"{row.get('category', '')} | {row.get('incident_id', '')} | "
        f"repeat={row.get('repeat_count', 0)} | msg={row.get('error_message', '')}"
    )


def _write_stream_row(row: dict[str, Any], ts: datetime) -> None:
    path = _ledger_stream_path(ts)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(_stream_line(row) + "\n")


def _try_export_workbook(csv_path: Path, xlsx_path: Path) -> None:
    df = pd.read_csv(csv_path)
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        incidents = df[df["event_type"] == "incident"]
        recoveries = df[df["event_type"] == "recovery"]
        incidents.to_excel(writer, sheet_name="Incidents", index=False)
        recoveries.to_excel(writer, sheet_name="Recoveries", index=False)
        df.to_excel(writer, sheet_name="Combined", index=False)


def _export_with_retry_policy(ts: datetime, params: dict[str, Any]) -> None:
    if not bool(params.get("ledger_export_excel", True)):
        return

    day_key = ts.strftime("%Y%m%d")
    state = _EXPORT_RETRY_STATE.get(
        day_key, {"attempts": 0, "next_try": datetime.min.replace(tzinfo=_IST)}
    )
    now = datetime.now(_IST)
    max_retries = int(params.get("ledger_max_export_retries", 3) or 3)
    retry_interval = int(params.get("ledger_retry_interval_seconds", 180) or 180)

    if state["attempts"] >= max_retries:
        return
    if now < state["next_try"]:
        return

    csv_path = _ledger_csv_path(ts)
    xlsx_path = _ledger_xlsx_path(ts)
    try:
        _try_export_workbook(csv_path, xlsx_path)
        _EXPORT_RETRY_STATE[day_key] = {"attempts": 0, "next_try": now}
    except Exception as exc:
        state["attempts"] += 1
        state["next_try"] = now + timedelta(seconds=retry_interval)
        _EXPORT_RETRY_STATE[day_key] = state
        logger.warning(
            "Incident ledger XLSX export failed (attempt %d/%d): %s",
            state["attempts"],
            max_retries,
            exc,
        )


def _append_incident_ledger_row(row: dict[str, Any], ts: datetime, params: dict[str, Any]) -> None:
    _incident_ledger_dir().mkdir(parents=True, exist_ok=True)
    csv_path = _ledger_csv_path(ts)
    with _LEDGER_LOCK:
        try:
            _write_stream_row(row, ts)
        except Exception as exc:
            logger.warning("Incident ledger stream append failed: %s", exc)

        if bool(params.get("ledger_write_csv", True)):
            try:
                file_exists = csv_path.exists()
                with open(csv_path, "a", encoding="utf-8", newline="") as fh:
                    writer = csv.DictWriter(fh, fieldnames=_INCIDENT_LEDGER_HEADERS)
                    if not file_exists:
                        writer.writeheader()
                    writer.writerow(row)
            except Exception as exc:
                logger.warning("Incident ledger CSV append failed: %s", exc)

        if bool(params.get("ledger_write_csv", True)):
            _export_with_retry_policy(ts, params)


async def publish_incident(
    *,
    source: str,
    scenario: str,
    severity: str = "warning",
    category: str,
    title: str,
    error_message: str,
    next_action: str,
    source_bot=None,
    source_chat_id: str | None = None,
    send_to_source: bool = True,
    route_to_jagran: bool | None = None,
) -> None:
    from core.incident_severity import resolve_incident_severity

    severity = resolve_incident_severity(source, scenario, severity)
    params = _load_jagran_params()
    now = datetime.now(_IST)
    fingerprint = _normalize_fingerprint(title, error_message)
    key = _incident_key(source, scenario)
    dedup_window = int(params.get("dedup_window_seconds", 300) or 300)
    still_failing_every = int(params.get("still_failing_interval_seconds", 1800) or 1800)

    allowlisted = _can_route_to_jagran(source, scenario)
    src = source.lower()
    if route_to_jagran is False:
        jagran_ok = False
    elif route_to_jagran is True:
        # Explicit force (tracker escalations / critical publishes).
        jagran_ok = True
    elif src in {"kavach", "kavach2"}:
        jagran_ok = allowlisted and _kavach_deployment_confirmed()
    else:
        jagran_ok = allowlisted

    routed_to_jagran = bool(params.get("enabled", True)) and jagran_ok

    with _INCIDENTS_LOCK:
        state = _ACTIVE_INCIDENTS.get(key)
        if state is None or state.fingerprint != fingerprint:
            state = _IncidentState(
                fingerprint=fingerprint,
                first_seen=now,
                last_sent=now,
                repeat_count=1,
                routed_to_jagran=routed_to_jagran,
                source=source.upper(),
                scenario=scenario,
                severity=severity,
                category=category,
                title=title,
            )
            _ACTIVE_INCIDENTS[key] = state
            status_label = "TRIGGERED"
        else:
            since_last = now - state.last_sent
            if since_last < timedelta(seconds=dedup_window):
                _append_incident_ledger_row(
                    {
                        "ts_ist": _format_timestamp(now),
                        "date_ist": now.strftime("%Y-%m-%d"),
                        "event_type": "incident",
                        "status_label": "SUPPRESSED_NOTIFICATION",
                        "source": source.upper(),
                        "scenario": scenario,
                        "severity": severity,
                        "category": category,
                        "title": title,
                        "error_message": error_message,
                        "next_action": next_action,
                        "resolution_message": "",
                        "incident_id": key,
                        "repeat_count": state.repeat_count,
                        "routed_to_source": send_to_source
                        and source_bot is not None
                        and bool(source_chat_id),
                        "source_delivery_ok": False,
                        "routed_to_jagran": state.routed_to_jagran,
                        "jagran_delivery_ok": False,
                    },
                    now,
                    params,
                )
                return
            if since_last < timedelta(seconds=still_failing_every):
                _append_incident_ledger_row(
                    {
                        "ts_ist": _format_timestamp(now),
                        "date_ist": now.strftime("%Y-%m-%d"),
                        "event_type": "incident",
                        "status_label": "SUPPRESSED_NOTIFICATION",
                        "source": source.upper(),
                        "scenario": scenario,
                        "severity": severity,
                        "category": category,
                        "title": title,
                        "error_message": error_message,
                        "next_action": next_action,
                        "resolution_message": "",
                        "incident_id": key,
                        "repeat_count": state.repeat_count,
                        "routed_to_source": send_to_source
                        and source_bot is not None
                        and bool(source_chat_id),
                        "source_delivery_ok": False,
                        "routed_to_jagran": state.routed_to_jagran,
                        "jagran_delivery_ok": False,
                    },
                    now,
                    params,
                )
                return
            state.last_sent = now
            state.repeat_count += 1
            state.routed_to_jagran = state.routed_to_jagran or routed_to_jagran
            status_label = "STILL FAILING"

    text = _build_alert_text(
        part=source.upper(),
        severity=severity,
        category=category,
        title=title,
        error_message=error_message,
        first_seen=state.first_seen,
        repeat_count=state.repeat_count,
        next_action=next_action,
        incident_key=key,
        status_label=status_label,
    )

    if send_to_source and source_bot is not None and source_chat_id:
        try:
            await _send_message(source_bot, source_chat_id, text)
            source_delivery_ok = True
        except Exception as exc:
            source_delivery_ok = False
            logger.warning("Source incident publish failed for %s: %s", key, exc)
    else:
        source_delivery_ok = False

    if state.routed_to_jagran:
        sent = await _send_to_jagran(text)
        if not sent:
            logger.info("JAGRAN not configured or unavailable; source alert only for %s", key)
        jagran_delivery_ok = sent
    else:
        jagran_delivery_ok = False

    _append_incident_ledger_row(
        {
            "ts_ist": _format_timestamp(now),
            "date_ist": now.strftime("%Y-%m-%d"),
            "event_type": "incident",
            "status_label": status_label,
            "source": source.upper(),
            "scenario": scenario,
            "severity": severity,
            "category": category,
            "title": title,
            "error_message": error_message,
            "next_action": next_action,
            "resolution_message": "",
            "incident_id": key,
            "repeat_count": state.repeat_count,
            "routed_to_source": send_to_source and source_bot is not None and bool(source_chat_id),
            "source_delivery_ok": source_delivery_ok,
            "routed_to_jagran": state.routed_to_jagran,
            "jagran_delivery_ok": jagran_delivery_ok,
        },
        now,
        params,
    )


async def resolve_incident(
    *,
    source: str,
    scenario: str,
    resolution_message: str,
    source_bot=None,
    source_chat_id: str | None = None,
    send_to_source: bool = True,
) -> None:
    params = _load_jagran_params()
    key = _incident_key(source, scenario)

    with _INCIDENTS_LOCK:
        state = _ACTIVE_INCIDENTS.pop(key, None)

    if state is None:
        return
    if not params.get("send_recovery", True):
        return

    now = datetime.now(_IST)
    text = (
        f"[RECOVERED] {state.source} | {state.severity.upper()} | {state.category}\n"
        f"{state.title}\n"
        f"Recovered at: {_format_timestamp(now)}\n"
        f"Incident ID: {key}\n"
        f"Resolution: {resolution_message}"
    )

    if send_to_source and source_bot is not None and source_chat_id:
        try:
            await _send_message(source_bot, source_chat_id, text)
            source_delivery_ok = True
        except Exception as exc:
            source_delivery_ok = False
            logger.warning("Source recovery publish failed for %s: %s", key, exc)
    else:
        source_delivery_ok = False

    if state.routed_to_jagran:
        jagran_delivery_ok = await _send_to_jagran(text)
    else:
        jagran_delivery_ok = False

    _append_incident_ledger_row(
        {
            "ts_ist": _format_timestamp(now),
            "date_ist": now.strftime("%Y-%m-%d"),
            "event_type": "recovery",
            "status_label": "RECOVERED",
            "source": state.source,
            "scenario": state.scenario,
            "severity": state.severity,
            "category": state.category,
            "title": state.title,
            "error_message": "",
            "next_action": "",
            "resolution_message": resolution_message,
            "incident_id": key,
            "repeat_count": state.repeat_count,
            "routed_to_source": send_to_source and source_bot is not None and bool(source_chat_id),
            "source_delivery_ok": source_delivery_ok,
            "routed_to_jagran": state.routed_to_jagran,
            "jagran_delivery_ok": jagran_delivery_ok,
        },
        now,
        params,
    )

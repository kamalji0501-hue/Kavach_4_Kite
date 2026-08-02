"""Domain-scoped incident/error tracker (bots, launchers, main orchestrator)."""

from __future__ import annotations

import csv
import json
import logging
import threading
import traceback
import zoneinfo
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_LOCK = threading.Lock()
_LOG = logging.getLogger("batman.incident_tracker")

ROOT = Path(__file__).resolve().parents[1]


def incidents_root_dir() -> Path:
    from core.batman_mode import incidents_root

    return incidents_root()


def by_domain_dir() -> Path:
    return incidents_root_dir() / "by_domain"


def open_registry_path() -> Path:
    return incidents_root_dir() / "open_registry.json"


def __getattr__(name: str) -> Path:
    """Back-compat for tests that monkeypatch module-level path constants."""
    if name == "INCIDENTS_ROOT":
        return incidents_root_dir()
    if name == "BY_DOMAIN_DIR":
        return by_domain_dir()
    if name == "OPEN_REGISTRY_PATH":
        return open_registry_path()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# Phase 1 bots + bulk launchers + five-bot main.py runtime
INCIDENT_DOMAINS = frozenset({"drishti", "kavach", "jagran", "start_all", "stop_all", "main"})
INCIDENT_DOMAINS_ORDERED = (
    "drishti",
    "kavach",
    "jagran",
    "main",
    "start_all",
    "stop_all",
)

_DOMAIN_HEADERS = [
    "ts_ist",
    "date_ist",
    "incident_id",
    "status",
    "operator_status",
    "event_type",
    "domain",
    "module",
    "scenario",
    "severity",
    "error_type",
    "message",
    "cause_hint",
    "repeat_count",
    "context_json",
]

_DOMAIN_TO_SOURCE: dict[str, str] = {
    "drishti": "drishti",
    "kavach": "kavach",
    "jagran": "jagran",
    "main": "main",
    "start_all": "launcher",
    "stop_all": "launcher",
}

_DEDUP_SECONDS = 120
_REPEAT_JAGRAN_THRESHOLD = 3
_REPEAT_JAGRAN_SCENARIO = "incident_repeat_escalation"


@dataclass
class _DomainIncidentState:
    fingerprint: str
    first_seen: datetime
    last_seen: datetime
    repeat_count: int
    title: str
    repeat_jagran_sent: bool = field(default=False)


_ACTIVE: dict[str, _DomainIncidentState] = {}
_registry_loaded = False


def domain_dir(domain: str) -> Path:
    key = domain.lower()
    if key not in INCIDENT_DOMAINS:
        raise ValueError(f"Unknown incident domain: {domain}")
    return by_domain_dir() / key


def domain_csv_path(domain: str, ts: datetime | None = None) -> Path:
    when = ts or datetime.now(_IST)
    return domain_dir(domain) / f"incidents_{when.strftime('%Y%m%d')}.csv"


def domain_errors_log_path(domain: str, ts: datetime | None = None) -> Path:
    when = ts or datetime.now(_IST)
    return domain_dir(domain) / f"errors_{when.strftime('%Y%m%d')}.log"


def _incident_key(domain: str, scenario: str) -> str:
    return f"{domain.lower()}::{scenario}"


def _fingerprint(title: str, message: str) -> str:
    return f"{title.strip()}::{message.strip()}".lower()


def _format_ts(ts: datetime) -> str:
    return ts.astimezone(_IST).strftime("%H:%M:%S.%f")[:-3] + " IST"


def _ensure_registry_loaded() -> None:
    global _registry_loaded
    if _registry_loaded:
        return
    _load_open_registry_from_disk()
    _registry_loaded = True


def _load_open_registry_from_disk() -> None:
    path = open_registry_path()
    if not path.exists():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("open_registry load failed: %s", exc)
        return
    if not isinstance(raw, dict):
        return
    with _LOCK:
        for incident_id, rec in raw.items():
            if not isinstance(rec, dict) or rec.get("operator_status") != "open":
                continue
            if incident_id in _ACTIVE:
                continue
            try:
                first = datetime.fromisoformat(str(rec["first_seen"]))
                last = datetime.fromisoformat(str(rec["last_seen"]))
            except (KeyError, ValueError):
                continue
            _ACTIVE[incident_id] = _DomainIncidentState(
                fingerprint=str(rec.get("fingerprint", "")),
                first_seen=first,
                last_seen=last,
                repeat_count=int(rec.get("repeat_count", 1)),
                title=str(rec.get("title", "")),
                repeat_jagran_sent=bool(rec.get("repeat_jagran_sent", False)),
            )


def _persist_open_registry() -> None:
    root = incidents_root_dir()
    root.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    with _LOCK:
        for incident_id, state in _ACTIVE.items():
            domain, scenario = incident_id.split("::", 1)
            payload[incident_id] = {
                "operator_status": "open",
                "domain": domain,
                "scenario": scenario,
                "fingerprint": state.fingerprint,
                "first_seen": state.first_seen.isoformat(),
                "last_seen": state.last_seen.isoformat(),
                "repeat_count": state.repeat_count,
                "title": state.title,
                "repeat_jagran_sent": state.repeat_jagran_sent,
            }
    try:
        open_registry_path().write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError as exc:
        _LOG.warning("open_registry save failed: %s", exc)


def _append_domain_row(row: dict[str, str], domain: str, ts: datetime) -> None:
    path = domain_csv_path(domain, ts)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        exists = path.exists()
        with open(path, "a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=_DOMAIN_HEADERS, extrasaction="ignore")
            if not exists:
                writer.writeheader()
            writer.writerow({k: row.get(k, "") for k in _DOMAIN_HEADERS})


def _append_domain_error_line(domain: str, line: str, ts: datetime) -> None:
    path = domain_errors_log_path(domain, ts)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _mirror_global_ledger(
    *,
    domain: str,
    scenario: str,
    status_label: str,
    severity: str,
    title: str,
    message: str,
    cause_hint: str,
    repeat_count: int,
    incident_id: str,
    event_type: str,
    ts: datetime,
) -> None:
    try:
        from bat_telegram.incident_publisher import append_ledger_row_sync
    except ImportError:
        return
    source = _DOMAIN_TO_SOURCE.get(domain, domain)
    append_ledger_row_sync(
        {
            "ts_ist": _format_ts(ts),
            "date_ist": ts.strftime("%Y-%m-%d"),
            "event_type": event_type,
            "status_label": status_label,
            "source": source.upper(),
            "scenario": scenario,
            "severity": severity,
            "category": domain,
            "title": title,
            "error_message": message[:2000],
            "next_action": cause_hint[:500],
            "resolution_message": "",
            "incident_id": incident_id,
            "repeat_count": repeat_count,
            "routed_to_source": False,
            "source_delivery_ok": False,
            "routed_to_jagran": False,
            "jagran_delivery_ok": False,
        },
        ts,
    )


def _notify_jagran_async(
    *,
    domain: str,
    scenario: str,
    severity: str,
    title: str,
    message: str,
    next_action: str,
) -> None:
    import asyncio

    source = _DOMAIN_TO_SOURCE.get(domain, domain)

    async def _run() -> None:
        from bat_telegram.incident_publisher import publish_incident

        await publish_incident(
            source=source,
            scenario=scenario,
            severity=severity,
            category=domain,
            title=title,
            error_message=message,
            next_action=next_action or "See domain incident CSV and logs.",
            send_to_source=False,
            route_to_jagran=True,
        )

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        try:
            asyncio.run(_run())
        except Exception as exc:
            _LOG.warning("JAGRAN notify failed for %s/%s: %s", domain, scenario, exc)


def _maybe_notify_repeat_escalation(
    *,
    domain: str,
    scenario: str,
    state: _DomainIncidentState,
    message: str,
    cause_hint: str,
) -> None:
    if state.repeat_count < _REPEAT_JAGRAN_THRESHOLD or state.repeat_jagran_sent:
        return
    state.repeat_jagran_sent = True
    title = f"Repeating incident ({state.repeat_count}x): {state.title}"
    body = (
        f"Domain: {domain.upper()} | Scenario: {scenario}\n"
        f"Repeat count: {state.repeat_count} (threshold {_REPEAT_JAGRAN_THRESHOLD})\n"
        f"Last error: {message[:800]}\n"
        f"Cause hint: {cause_hint[:400]}"
    )
    _notify_jagran_async(
        domain=domain,
        scenario=_REPEAT_JAGRAN_SCENARIO,
        severity="major",
        title=title,
        message=body,
        next_action="Inspect incident_dashboard.xlsx and domain CSV under data/analytics/incidents/by_domain/",
    )


def record_incident(
    *,
    domain: str,
    scenario: str,
    message: str,
    severity: str = "error",
    title: str | None = None,
    cause_hint: str = "",
    module: str = "",
    error_type: str = "",
    context: dict[str, Any] | None = None,
    event_type: str = "incident",
    notify_jagran: bool = False,
    next_action: str = "",
) -> str:
    """Record an error/incident. Returns incident_id."""
    from core.incident_severity import resolve_incident_severity

    _ensure_registry_loaded()
    key = domain.lower()
    if key not in INCIDENT_DOMAINS:
        raise ValueError(f"Unknown incident domain: {domain}")

    severity = resolve_incident_severity(key, scenario, severity)

    now = datetime.now(_IST)
    incident_id = _incident_key(key, scenario)
    title = title or scenario.replace("_", " ").title()
    fp = _fingerprint(title, message)

    with _LOCK:
        state = _ACTIVE.get(incident_id)
        if state is None or state.fingerprint != fp:
            state = _DomainIncidentState(
                fingerprint=fp,
                first_seen=now,
                last_seen=now,
                repeat_count=1,
                title=title,
            )
            _ACTIVE[incident_id] = state
            status = "TRIGGERED"
        else:
            if (now - state.last_seen).total_seconds() < _DEDUP_SECONDS:
                status = "SUPPRESSED"
            else:
                state.repeat_count += 1
                state.last_seen = now
                status = "REPEAT" if state.repeat_count > 1 else "TRIGGERED"

    if status == "SUPPRESSED":
        return incident_id

    operator_status = "open"
    ctx_json = json.dumps(context or {}, default=str)[:4000]
    row = {
        "ts_ist": _format_ts(now),
        "date_ist": now.strftime("%Y-%m-%d"),
        "incident_id": incident_id,
        "status": status,
        "operator_status": operator_status,
        "event_type": event_type,
        "domain": key,
        "module": module,
        "scenario": scenario,
        "severity": severity,
        "error_type": error_type,
        "message": message[:4000],
        "cause_hint": cause_hint[:1000],
        "repeat_count": str(state.repeat_count),
        "context_json": ctx_json,
    }
    _append_domain_row(row, key, now)
    log_line = (
        f"{row['ts_ist']} | {severity.upper()} | {module or key} | {scenario} | "
        f"{status} | op={operator_status} | repeat={state.repeat_count} | {message[:500]}"
    )
    if cause_hint:
        log_line += f" | cause: {cause_hint[:300]}"
    _append_domain_error_line(key, log_line, now)

    _mirror_global_ledger(
        domain=key,
        scenario=scenario,
        status_label=status,
        severity=severity,
        title=title,
        message=message,
        cause_hint=cause_hint or next_action,
        repeat_count=state.repeat_count,
        incident_id=incident_id,
        event_type=event_type,
        ts=now,
    )

    _maybe_notify_repeat_escalation(
        domain=key,
        scenario=scenario,
        state=state,
        message=message,
        cause_hint=cause_hint,
    )

    if notify_jagran and status in ("TRIGGERED", "REPEAT"):
        _notify_jagran_async(
            domain=key,
            scenario=scenario,
            severity=severity,
            title=title,
            message=message,
            next_action=next_action or cause_hint,
        )

    _persist_open_registry()
    return incident_id


def record_exception(
    *,
    domain: str,
    scenario: str,
    exc: BaseException,
    cause_hint: str = "",
    module: str = "",
    context: dict[str, Any] | None = None,
    notify_jagran: bool = False,
) -> str:
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-3000:]
    ctx = dict(context or {})
    ctx["traceback_tail"] = tb
    return record_incident(
        domain=domain,
        scenario=scenario,
        message=str(exc),
        severity="critical",
        error_type=type(exc).__name__,
        cause_hint=cause_hint,
        module=module,
        context=ctx,
        notify_jagran=notify_jagran,
    )


def close_incident(
    *,
    incident_id: str | None = None,
    domain: str | None = None,
    scenario: str | None = None,
    note: str = "Closed by operator",
) -> bool:
    """Close an open incident (registry + RECOVERED row with operator_status=closed)."""
    dom = domain
    sc = scenario
    if incident_id:
        parts = incident_id.split("::", 1)
        if len(parts) != 2:
            return False
        dom, sc = parts[0], parts[1]
    if not dom or not sc:
        return False
    key = _incident_key(dom, sc)
    _ensure_registry_loaded()
    with _LOCK:
        if key not in _ACTIVE:
            return False
    resolve_domain_incident(domain=dom, scenario=sc, resolution_message=note)
    return True


def resolve_domain_incident(
    *,
    domain: str,
    scenario: str,
    resolution_message: str,
) -> None:
    _ensure_registry_loaded()
    key = _incident_key(domain, scenario)
    with _LOCK:
        state = _ACTIVE.pop(key, None)
    if state is None:
        return
    now = datetime.now(_IST)
    row = {
        "ts_ist": _format_ts(now),
        "date_ist": now.strftime("%Y-%m-%d"),
        "incident_id": key,
        "status": "RECOVERED",
        "operator_status": "closed",
        "event_type": "recovery",
        "domain": domain.lower(),
        "module": "",
        "scenario": scenario,
        "severity": "info",
        "error_type": "",
        "message": resolution_message[:4000],
        "cause_hint": "",
        "repeat_count": str(state.repeat_count),
        "context_json": "{}",
    }
    _append_domain_row(row, domain.lower(), now)
    _mirror_global_ledger(
        domain=domain.lower(),
        scenario=scenario,
        status_label="RECOVERED",
        severity="info",
        title=state.title,
        message=resolution_message,
        cause_hint="",
        repeat_count=state.repeat_count,
        incident_id=key,
        event_type="recovery",
        ts=now,
    )
    _persist_open_registry()


def list_open_incidents(domain: str | None = None) -> list[dict[str, Any]]:
    _ensure_registry_loaded()
    out: list[dict[str, Any]] = []
    with _LOCK:
        for incident_id, state in _ACTIVE.items():
            dom, scenario = incident_id.split("::", 1)
            if domain and dom != domain.lower():
                continue
            out.append(
                {
                    "incident_id": incident_id,
                    "domain": dom,
                    "scenario": scenario,
                    "operator_status": "open",
                    "repeat_count": state.repeat_count,
                    "title": state.title,
                    "first_seen": state.first_seen.isoformat(),
                    "last_seen": state.last_seen.isoformat(),
                }
            )
    return sorted(out, key=lambda x: x["incident_id"])


def read_domain_csv_rows(domain: str, day: datetime) -> list[dict[str, str]]:
    path = domain_csv_path(domain, day)
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def collect_incidents_between(
    *,
    days: int = 7,
    end: datetime | None = None,
) -> list[dict[str, str]]:
    """Load incident rows from all domains for the last ``days`` IST days (inclusive)."""
    end_dt = end or datetime.now(_IST)
    rows: list[dict[str, str]] = []
    for offset in range(max(1, days)):
        day = end_dt - timedelta(days=offset)
        for domain in INCIDENT_DOMAINS_ORDERED:
            for row in read_domain_csv_rows(domain, day):
                if row.get("event_type") == "incident":
                    rows.append(row)
    return rows


def build_weekly_rollup(*, days: int = 7, end: datetime | None = None) -> dict[str, Any]:
    """Aggregate repeating scenarios and open incidents for dashboard export."""
    end_dt = end or datetime.now(_IST)
    start_dt = end_dt - timedelta(days=max(1, days) - 1)
    rows = collect_incidents_between(days=days, end=end_dt)

    by_domain_scenario: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        dom = row.get("domain", "?")
        sc = row.get("scenario", "?")
        k = (dom, sc)
        try:
            rc = int(row.get("repeat_count") or 1)
        except ValueError:
            rc = 1
        entry = by_domain_scenario.setdefault(
            k,
            {
                "domain": dom,
                "scenario": sc,
                "event_count": 0,
                "max_repeat_count": 0,
                "last_ts": "",
                "last_message": "",
                "open_count": 0,
            },
        )
        entry["event_count"] += 1
        entry["max_repeat_count"] = max(entry["max_repeat_count"], rc)
        ts = row.get("ts_ist", "")
        if ts >= entry["last_ts"]:
            entry["last_ts"] = ts
            entry["last_message"] = (row.get("message") or "")[:200]
        if row.get("operator_status") == "open":
            entry["open_count"] += 1

    top = sorted(
        by_domain_scenario.values(),
        key=lambda x: (-x["max_repeat_count"], -x["event_count"], x["domain"]),
    )

    open_now = list_open_incidents()
    by_domain_totals: dict[str, int] = {}
    for row in rows:
        by_domain_totals[row.get("domain", "?")] = (
            by_domain_totals.get(row.get("domain", "?"), 0) + 1
        )

    return {
        "period_start": start_dt.strftime("%Y-%m-%d"),
        "period_end": end_dt.strftime("%Y-%m-%d"),
        "days": days,
        "total_incidents": len(rows),
        "by_domain_totals": by_domain_totals,
        "top_scenarios": top,
        "open_incidents": open_now,
    }


def export_dashboard_xlsx(
    output_path: Path,
    *,
    days: int = 7,
    end: datetime | None = None,
) -> Path:
    import pandas as pd

    rollup = build_weekly_rollup(days=days, end=end)
    rows = collect_incidents_between(days=days, end=end)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary = pd.DataFrame(
            [
                {"metric": "period_start", "value": rollup["period_start"]},
                {"metric": "period_end", "value": rollup["period_end"]},
                {"metric": "days", "value": rollup["days"]},
                {"metric": "total_incidents", "value": rollup["total_incidents"]},
                {"metric": "open_incidents_now", "value": len(rollup["open_incidents"])},
            ]
        )
        summary.to_excel(writer, sheet_name="Summary", index=False)

        if rollup["by_domain_totals"]:
            pd.DataFrame(
                [{"domain": k, "incident_rows": v} for k, v in rollup["by_domain_totals"].items()]
            ).to_excel(writer, sheet_name="By_Domain", index=False)

        if rollup["top_scenarios"]:
            pd.DataFrame(rollup["top_scenarios"]).to_excel(
                writer, sheet_name="Top_Scenarios", index=False
            )

        if rollup["open_incidents"]:
            pd.DataFrame(rollup["open_incidents"]).to_excel(
                writer, sheet_name="Open_Now", index=False
            )

        if rows:
            pd.DataFrame(rows).to_excel(writer, sheet_name="All_Events", index=False)

    return output_path


def record_from_log_record(
    workspace_root: Path,
    default_domain: str,
    record: logging.LogRecord,
) -> None:
    if record.levelno < logging.ERROR:
        return
    message = record.getMessage()
    exc = None
    if record.exc_info and record.exc_info[1]:
        exc = record.exc_info[1]
        message = f"{message} | {type(exc).__name__}: {exc}"

    module = _module_for_record(record)
    scenario = f"log_{record.levelname.lower()}"
    cause_hint = ""
    if record.levelno >= logging.CRITICAL:
        cause_hint = "Critical log level — inspect stack trace and robot health."
    elif "stale" in message.lower() or "ltp" in message.lower():
        cause_hint = "LTP/cache or feed issue — check DRISHTI feed and market hours."
    elif "token" in message.lower():
        cause_hint = "Broker token issue — refresh JWT via DRISHTI."

    ctx: dict[str, Any] = {
        "logger": record.name,
        "pathname": record.pathname,
        "lineno": record.lineno,
        "funcName": record.funcName,
    }
    if exc:
        ctx["exception_type"] = type(exc).__name__

    record_incident(
        domain=default_domain,
        scenario=scenario,
        message=message,
        severity="critical" if record.levelno >= logging.CRITICAL else "error",
        module=module,
        error_type=type(exc).__name__ if exc else "",
        cause_hint=cause_hint,
        context=ctx,
    )


def _module_for_record(record: logging.LogRecord) -> str:
    name = (record.name or "").lower()
    for part in ("drishti", "kavach", "jagran", "ato_protection", "nifty_ltp", "main"):
        if part in name:
            return part
    return name.split(".")[-1] if "." in name else name


def summarize_domain_day(domain: str, *, day: str | None = None) -> dict[str, Any]:
    _ensure_registry_loaded()
    if day:
        ts = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=_IST)
    else:
        ts = datetime.now(_IST)
    path = domain_csv_path(domain, ts)
    if not path.exists():
        return {
            "domain": domain,
            "total": 0,
            "by_scenario": {},
            "open_ids": active_incident_ids(domain),
            "open_registry_count": len(list_open_incidents(domain)),
        }

    file_rows: list[dict[str, str]] = []
    with open(path, encoding="utf-8", newline="") as fh:
        file_rows = list(csv.DictReader(fh))

    by_scenario: dict[str, int] = {}
    for r in file_rows:
        if r.get("event_type") != "incident":
            continue
        sc = r.get("scenario", "?")
        by_scenario[sc] = by_scenario.get(sc, 0) + 1

    return {
        "domain": domain,
        "path": str(path),
        "total": len(file_rows),
        "incidents": sum(1 for r in file_rows if r.get("event_type") == "incident"),
        "by_scenario": by_scenario,
        "open_ids": active_incident_ids(domain),
        "open_registry_count": len(list_open_incidents(domain)),
    }


def active_incident_ids(domain: str | None = None) -> list[str]:
    _ensure_registry_loaded()
    with _LOCK:
        keys = list(_ACTIVE.keys())
    if domain is None:
        return sorted(keys)
    prefix = f"{domain.lower()}::"
    return sorted(k for k in keys if k.startswith(prefix))

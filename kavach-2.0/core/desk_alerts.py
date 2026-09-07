"""Desk notification bus: in-memory ring + daily JSONL for the Kavach web desk."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger("batman.desk_alerts")

IST = ZoneInfo("Asia/Kolkata")
_LOCK = threading.Lock()
_RING: deque[dict[str, Any]] = deque(maxlen=200)
_LOADED_DAY = ""
SEVERITIES = ("red", "orange", "green")

_RED_READY = {
    "datafeedbot_down",
    "kavach2_down",
    "pe_side_halted",
    "ce_side_halted",
    "all_sides_halted",
}


def option_side(symbol_or_side: Any) -> str | None:
    s = str(symbol_or_side or "").strip().upper()
    if s in ("PE", "CE"):
        return s
    if s.endswith("PE"):
        return "PE"
    if s.endswith("CE"):
        return "CE"
    return None


def _runtime_root() -> Path:
    env = (os.environ.get("BATMAN_RUNTIME_ROOT") or os.environ.get("TRADING_RUNTIME") or "").strip()
    if env:
        return Path(env)
    return Path("/home/ubuntu/Trading_Runtime_Rahul")


def _log_path(now: datetime | None = None) -> Path:
    stamp = now or datetime.now(IST)
    return (
        _runtime_root()
        / "Logs"
        / "prod"
        / stamp.strftime("%Y-%m")
        / stamp.strftime("%Y-%m-%d")
        / "kavach2"
        / "desk_alerts.jsonl"
    )


def _ensure_loaded() -> None:
    global _LOADED_DAY
    day = datetime.now(IST).strftime("%Y-%m-%d")
    if _LOADED_DAY == day:
        return
    _RING.clear()
    path = _log_path()
    if path.is_file():
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict) and row.get("id"):
                        _RING.append(row)
        except OSError as exc:
            logger.debug("desk_alerts load: %s", exc)
    _LOADED_DAY = day


def _append_jsonl(row: dict[str, Any]) -> None:
    path = _log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")
    except OSError as exc:
        logger.debug("desk_alerts write: %s", exc)


def emit_desk_alert(
    *,
    severity: str,
    category: str,
    alert: str,
    log: str = "",
    side: str | None = None,
) -> dict[str, Any] | None:
    """Record one desk alert. Never raises — trading paths must stay safe."""
    try:
        sev = str(severity or "orange").strip().lower()
        if sev not in SEVERITIES:
            sev = "orange"
        cat = str(category or "Desk").strip() or "Desk"
        line = str(alert or "").strip()
        if not line:
            return None
        side_n = option_side(side) if side else None
        now = datetime.now(IST)
        row = {
            "id": uuid.uuid4().hex[:12],
            "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
            "severity": sev,
            "category": cat,
            "alert": line,
            "log": str(log or line).strip(),
            "side": side_n,
        }
        with _LOCK:
            _ensure_loaded()
            _RING.append(row)
            _append_jsonl(row)
        return row
    except Exception as exc:
        logger.debug("emit_desk_alert failed: %s", exc)
        return None


def recent(limit: int = 30) -> list[dict[str, Any]]:
    try:
        n = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        n = 30
    with _LOCK:
        _ensure_loaded()
        rows = list(_RING)
    return rows[-n:]


def for_day(limit: int = 200) -> list[dict[str, Any]]:
    return recent(limit=limit)


def tag_result(
    result: dict[str, Any] | None,
    *,
    category: str,
    ok_alert: str,
    fail_severity: str = "orange",
    fail_alert: str | None = None,
) -> dict[str, Any]:
    """Attach a desk_alert onto a web-command dict and persist it."""
    data = result if isinstance(result, dict) else {"ok": False, "error": "failed"}
    try:
        ok = bool(data.get("ok"))
        if ok:
            row = emit_desk_alert(
                severity="green",
                category=category,
                alert=ok_alert,
                log=str(data.get("text") or ok_alert),
            )
        else:
            err = str(data.get("error") or data.get("text") or "failed")
            line = fail_alert or err
            row = emit_desk_alert(
                severity=fail_severity,
                category=category,
                alert=line,
                log=err,
            )
        if row:
            data["desk_alert"] = row
    except Exception as exc:
        logger.debug("tag_result: %s", exc)
    return data


_PREV_READY: dict[str, Any] = {
    "primed": False,
    "armed": None,
    "hard_key": "",
    "paused": None,
    "broker": None,
}


def _notice_for_reason(reason: str, labels: dict[str, Any]) -> tuple[str, str, str, str | None]:
    """severity, category, alert, side."""
    raw = str(labels.get(reason) or reason)
    if reason == "pe_side_halted":
        return "red", "Side halted", "PE protection is halted — that side will not buy.", "PE"
    if reason == "ce_side_halted":
        return "red", "Side halted", "CE protection is halted — that side will not buy.", "CE"
    if reason == "all_sides_halted":
        return "red", "Side halted", "Both CE and PE protection are halted.", None
    if reason == "datafeedbot_down":
        return "red", "Market feed", "Datafeedbot service is not running.", None
    if reason == "kavach2_down":
        return "red", "Desk", "Kavach service itself is not running.", None
    if reason == "nifty_cache_missing":
        return "orange", "ATO blocked", "Nifty price file is missing — check Datafeedbot.", None
    if reason == "nifty_cache_stale":
        return "orange", "ATO blocked", "Nifty price is old — check Datafeedbot.", None
    if reason == "feed_unhealthy":
        return "orange", "ATO blocked", "Nifty feed marked unhealthy — check Datafeedbot.", None
    if reason == "feeder_ipc_down":
        return "orange", "Market feed", "Kavach cannot talk to the feeder socket.", None
    if reason == "deployment_not_confirmed":
        return "orange", "ATO blocked", "Batman is not armed yet — Register / Arm Kavach first.", None
    if reason == "algo_paused":
        return "orange", "ATO blocked", "Kavach is paused — tap Resume when the feed is healthy.", None
    if reason == "outside_monitoring_window":
        return "orange", "ATO blocked", "Outside the ATO watch window — protection will not fire yet.", None
    if reason == "pe_protect_in_book":
        return "orange", "Protect in book", "PE protect is already in the broker book — no second buy.", "PE"
    if reason == "ce_protect_in_book":
        return "orange", "Protect in book", "CE protect is already in the broker book — no second buy.", "CE"
    sev = "red" if reason in _RED_READY else "orange"
    return sev, "ATO blocked", raw, None


def emit_readiness_edges(
    ato_readiness: dict[str, Any] | None,
    *,
    paused: bool,
    broker_ok: bool,
) -> None:
    """Edge-detect ATO readiness / broker so the 2s WS snapshot does not spam."""
    try:
        ar = ato_readiness or {}
        armed = bool(ar.get("armed"))
        hard = [str(x) for x in (ar.get("hard_blocked_reasons") or ar.get("blocked_reasons") or [])]
        labels = ar.get("reason_labels") or {}
        hard_key = "|".join(hard)
        if not _PREV_READY["primed"]:
            _PREV_READY.update(
                primed=True,
                armed=armed,
                hard_key=hard_key,
                paused=bool(paused),
                broker=bool(broker_ok),
            )
            return
        prev_armed = _PREV_READY.get("armed")
        if prev_armed is False and armed:
            emit_desk_alert(
                severity="green",
                category="ATO ready",
                alert="ATO is armed again — feed is OK.",
                log=str(ar.get("summary_line") or "ATO ARMED"),
            )
        elif (not armed) and (prev_armed is True or hard_key != _PREV_READY.get("hard_key")):
            top = hard[:2] or ["blocked"]
            for reason in top:
                sev, cat, line, side = _notice_for_reason(reason, labels)
                emit_desk_alert(
                    severity=sev,
                    category=cat,
                    alert=line,
                    log=str(labels.get(reason) or ar.get("summary_line") or reason),
                    side=side,
                )
                break
        if bool(paused) and not _PREV_READY.get("paused"):
            emit_desk_alert(
                severity="orange",
                category="ATO blocked",
                alert="Kavach is paused — tap Resume when the feed is healthy.",
                log="algo.paused=true",
            )
        if _PREV_READY.get("broker") and not broker_ok:
            emit_desk_alert(
                severity="red",
                category="Tokens",
                alert="Kite token is off — live orders are blocked until you save a new one.",
                log="snapshot.broker=false",
            )
        _PREV_READY.update(
            armed=armed,
            hard_key=hard_key,
            paused=bool(paused),
            broker=bool(broker_ok),
        )
    except Exception as exc:
        logger.debug("emit_readiness_edges: %s", exc)

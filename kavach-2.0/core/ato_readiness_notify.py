"""Edge-triggered Telegram alerts for ATO ARMED ↔ BLOCKED."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("batman.ato_readiness_notify")

_STOP = threading.Event()
_THREAD: threading.Thread | None = None

_STATE_PATH = Path(
    os.environ.get(
        "ATO_READINESS_NOTIFY_STATE",
        "/home/ubuntu/Trading_Runtime_Rahul/Data/data/shared/ato_readiness_notify_state.json",
    )
)
_REALERT_SECONDS = int(os.environ.get("ATO_READINESS_REALERT_SECONDS", "300"))
_POLL_SECONDS = float(os.environ.get("ATO_READINESS_NOTIFY_POLL", "5"))


def _load_creds() -> tuple[str, str]:
    token = (os.environ.get("KAVACH2_BOT_TOKEN") or "").strip()
    chat = (os.environ.get("KAVACH2_CHAT_ID") or "").strip()
    if token and chat:
        return token, chat
    candidates = [
        Path("/home/ubuntu/Trading_Runtime_Rahul/Credentials/telegram/bots/kavach2/token.env"),
        Path("/home/ubuntu/Trading_Runtime_Rahul/Credentials/telegram/bots.env"),
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == "KAVACH2_BOT_TOKEN" and v:
                    token = token or v
                if k == "KAVACH2_CHAT_ID" and v:
                    chat = chat or v
        except Exception as exc:
            logger.debug("cred read %s: %s", path, exc)
    return token, chat


def _send_telegram(text: str) -> bool:
    token, chat = _load_creds()
    if not token or not chat:
        logger.warning("ATO readiness notify: missing KAVACH2 bot token/chat")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode(
        {"chat_id": chat, "text": text, "disable_web_page_preview": "1"}
    ).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw else {}
        return bool(data.get("ok"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("ATO readiness Telegram send failed: %s", exc)
        return False


def _read_persist() -> dict[str, Any]:
    try:
        if _STATE_PATH.is_file():
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_persist(blob: dict[str, Any]) -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(blob, indent=2) + "\n", encoding="utf-8")
        tmp.replace(_STATE_PATH)
    except Exception as exc:
        logger.debug("notify state write: %s", exc)


def _message_for(snap: dict[str, Any], *, armed_now: bool) -> str:
    levels = snap.get("ato_levels") or {}
    pe = levels.get("pe_entry") or "?"
    if armed_now:
        return f"ATO ARMED again. Feed OK. PE entry <= {pe}."
    labels = snap.get("reason_labels") or {}
    hard = snap.get("hard_blocked_reasons") or snap.get("blocked_reasons") or []
    bits = [labels.get(r, r) for r in hard[:2]]
    detail = "; ".join(bits) if bits else (snap.get("summary_line") or "blocked")
    action = "Check Datafeedbot."
    if any(r in hard for r in ("datafeedbot_down", "kavach2_down")):
        action = "Check VPS services (Datafeedbot / Kavach2)."
    elif "algo_paused" in hard:
        action = "Resume Kavach when feed is healthy."
    elif "deployment_not_confirmed" in hard:
        action = "Register / Arm Kavach first."
    return f"ATO BLOCKED: {detail}. {action}"


def tick(snapshot_fn: Callable[[], dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Evaluate readiness once; send Telegram on edge (or 5 min re-alert)."""
    if snapshot_fn is None:
        from core.ato_readiness import ato_readiness_snapshot

        snapshot_fn = ato_readiness_snapshot
    try:
        snap = snapshot_fn()
    except Exception as exc:
        logger.warning("ato readiness snapshot failed: %s", exc)
        return None

    armed = bool(snap.get("armed"))
    hard_key = "|".join(snap.get("hard_blocked_reasons") or [])
    now = time.time()
    prev = _read_persist()
    prev_armed = prev.get("armed")
    last_sent = float(prev.get("last_sent_ts") or 0)
    last_key = str(prev.get("hard_key") or "")

    should_send = False
    if prev_armed is None:
        # First run: only alert if currently blocked (avoid noisy ARMED on boot)
        if not armed:
            should_send = True
    elif bool(prev_armed) != armed:
        should_send = True
    elif (not armed) and hard_key and hard_key == last_key:
        if (now - last_sent) >= _REALERT_SECONDS:
            should_send = True
    elif (not armed) and hard_key != last_key:
        should_send = True

    if should_send:
        text = _message_for(snap, armed_now=armed)
        ok = _send_telegram(text)
        logger.info("ATO readiness Telegram (%s): %s", "sent" if ok else "failed", text)
        prev["last_sent_ts"] = now
        prev["last_text"] = text

    prev["armed"] = armed
    prev["hard_key"] = hard_key
    prev["summary"] = snap.get("summary_line")
    prev["checked_at"] = snap.get("checked_at")
    _write_persist(prev)
    return snap


def _loop(snapshot_fn: Callable[[], dict[str, Any]] | None) -> None:
    logger.info(
        "ATO readiness notifier started (poll=%.1fs re-alert=%ss)",
        _POLL_SECONDS,
        _REALERT_SECONDS,
    )
    while not _STOP.wait(_POLL_SECONDS):
        try:
            tick(snapshot_fn)
        except Exception as exc:
            logger.warning("ato readiness notify loop: %s", exc)


def start_ato_readiness_notifier(
    snapshot_fn: Callable[[], dict[str, Any]] | None = None,
) -> None:
    global _THREAD
    if _THREAD is not None and _THREAD.is_alive():
        return
    _STOP.clear()
    _THREAD = threading.Thread(
        target=_loop,
        args=(snapshot_fn,),
        name="ato-readiness-notify",
        daemon=True,
    )
    _THREAD.start()


def stop_ato_readiness_notifier() -> None:
    _STOP.set()

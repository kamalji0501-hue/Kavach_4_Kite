"""
Batman v3 — JSON state persistence.

Saves strategy state to ``data/batman_state.json`` after every significant
change.  On startup the last state is restored, enabling crash recovery.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from .exceptions import StateError
from .process_lock import exclusive_file_lock

logger = logging.getLogger(__name__)


_DEFAULT_STATE: dict[str, Any] = {
    "session_id": None,
    "started_at": None,
    # Per-session flags (reset on new session)
    "session": {
        "emergency_exited": False,  # Prevents re-entry after an emergency exit
    },
    # Batman iron condor legs (filled by /confirm_deploy via deploy_handler)
    "positions": {
        "ce_sell": None,  # {"symbol", "strike", "qty", "order_id", "avg_price"}
        "ce_buy": None,
        "pe_sell": None,
        "pe_buy": None,
    },
    # ATO protection state (managed by ato_protection module)
    "ato": {
        # Breach / retrace flags — managed per trading session
        "ce_triggered": False,  # True when CE ATO protection is active
        "pe_triggered": False,  # True when PE ATO protection is active
        "ce_ato_active": False,  # Alias for ce_triggered (legacy compat)
        "pe_ato_active": False,  # Alias for pe_triggered (legacy compat)
        # Active ATO order IDs
        "ce_order_id": None,
        "pe_order_id": None,
        "ce_ato_exit_order_id": None,
        "pe_ato_exit_order_id": None,
        # ATO protect symbols — derived from sell strikes + strike_offset
        # Set by deploy_handler when /confirm_deploy is processed
        "ce_protect_symbol": None,
        "pe_protect_symbol": None,
        "ce_protect_strike": None,
        "pe_protect_strike": None,
        "manage_sides": "both",
        "ce_entry_buffer_points": 0,
        "pe_entry_buffer_points": 0,
        "ce_retrace_points": 5,
        "pe_retrace_points": 5,
        "poll_interval_seconds": None,
        # Configurable retrace cushion (index pts market must pull back past sell
        # strike before ATO position is exited).  Single canonical term —
        # legacy name "exit_points" is retired.  Changed live via /ato command.
        "retrace_points": 5,
    },
    "risk": {
        "break_even": {
            "pe": None,
            "ce": None,
            "confirmed": False,
            "source": {
                "pe": None,
                "ce": None,
            },
            "skipped": False,
        }
    },
    "modules": {
        "ratripal": {
            "enabled": False,
        },
        "prabhat_mukti": {
            "enabled": False,
        },
    },
    "ratripal": {
        "last_run_date": None,
        "last_decision": None,
        "pending": {
            "request_id": None,
            "response": None,
            "sent_at": None,
        },
    },
    "prabhat_mukti": {
        "handoff_file": None,
    },
    # Profit trailing (managed by profit_trailing module)
    "trailing": {
        "active": False,
        "peak_profit": 0,
        "trailing_stop": None,
        "hard_stop_hit": False,
    },
    # Overnight hedge (managed manually by user on Dhan app — state keys retained for reference)
    "hedge": {
        "active": False,
        "ce_symbol": None,
        "pe_symbol": None,
        "ce_order_id": None,
        "pe_order_id": None,
    },
    # Which modules were running
    "active_modules": [],
    # Deployment confirmation (managed by /confirm_deploy and /batman_complete)
    "deployment": {
        "confirmed": False,  # True after user confirms legs via /confirm_deploy
        "batman_complete": False,  # True after /batman_complete — algo cleaned up, awaiting next deploy
        "positions_confirmed_date": None,  # ISO date string when confirmed
        "next_entry_date": None,  # ISO date string for next Batman cycle (informational only)
    },
    # Algo run/pause (KAVACH Resume/Pause; DRISHTI feed may auto-pause)
    "algo": {
        "paused": False,
        "pause_reason": None,
        "paused_at": None,
        "paused_by": None,
    },
}


class StateManager:
    """Thread-safe JSON state manager.

    Usage::

        sm = StateManager("data/batman_state.json")
        sm.set("ato.ce_triggered", True)
        sm.set("positions.ce_sell", {"symbol": "...", "qty": -130})
        val = sm.get("ato.retrace_points")   # → 5
        sm.save()
    """

    def __init__(self, path: str | Path = "data/batman_state.json"):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._load()

    # ── Public API ───────────────────────────────────────────

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Read value at dot-separated path."""
        with self._lock:
            return self._resolve(dotted_key, default)

    def set(self, dotted_key: str, value: Any, *, save: bool = True) -> None:
        """Set value at dot-separated path and optionally persist."""
        with self._lock:
            self._assign(dotted_key, value)
        if save:
            self.save()

    def save(self) -> None:
        """Atomically write state to disk."""
        with self._lock:
            data_copy = json.loads(json.dumps(self._data, default=str))

        tmp = self._path.with_suffix(".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with exclusive_file_lock(self._path):
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(data_copy, fh, indent=2, default=str)
                tmp.replace(self._path)
        except Exception as exc:
            logger.error("State save failed: %s", exc)
            raise StateError(f"Cannot save state: {exc}") from exc

    def refresh_algo_flags_from_disk(self) -> None:
        """Reload ``algo.*`` pause flags written by another process (e.g. DRISHTI)."""
        if not self._path.exists():
            return
        try:
            with exclusive_file_lock(self._path, timeout=2.0):
                with open(self._path, encoding="utf-8") as fh:
                    disk = json.load(fh)
            algo = disk.get("algo")
            if not isinstance(algo, dict):
                return
            with self._lock:
                node = self._data.setdefault("algo", {})
                if isinstance(node, dict):
                    node.update(algo)
        except Exception as exc:
            logger.warning("Could not refresh algo flags from disk: %s", exc)

    def reset(self, *, backup: bool = True) -> None:
        """Reset state to defaults, keeping a .bak copy."""
        with self._lock:
            if backup and self._path.exists():
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                bak = self._path.with_suffix(f".{ts}.bak")
                shutil.copy2(self._path, bak)
                logger.info("State backed up → %s", bak)
            self._data = json.loads(json.dumps(_DEFAULT_STATE))
            self._data["session_id"] = datetime.now().strftime("%Y%m%d-%H%M%S")
            self._data["started_at"] = datetime.now().isoformat()
        self.save()
        logger.info("State reset to defaults")

    @property
    def data(self) -> dict[str, Any]:
        """Snapshot of the full state dict (copy)."""
        with self._lock:
            return cast(dict[str, Any], json.loads(json.dumps(self._data, default=str)))

    # ── Internal ─────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path) as fh:
                    self._data = json.load(fh)
                logger.info("State loaded from %s", self._path)
                return
            except Exception as exc:
                logger.warning("Corrupt state file, resetting: %s", exc)

        # First run or corrupt — start with defaults
        self._data = json.loads(json.dumps(_DEFAULT_STATE))
        self._data["session_id"] = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._data["started_at"] = datetime.now().isoformat()
        self.save()
        logger.info("Fresh state created at %s", self._path)

    def _resolve(self, dotted_key: str, default: Any = None) -> Any:
        keys = dotted_key.split(".")
        node = self._data
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return default
        return node

    def _assign(self, dotted_key: str, value: Any) -> None:
        keys = dotted_key.split(".")
        node = self._data
        for k in keys[:-1]:
            if k not in node or not isinstance(node[k], dict):
                node[k] = {}
            node = node[k]
        node[keys[-1]] = value

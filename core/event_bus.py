"""
Batman v3 — Thread-safe event bus (pub/sub).

Modules publish events; any subscriber (including Telegram handlers)
can listen for them without tight coupling.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class Event(StrEnum):
    """All event types used across the system."""

    # Broker
    BROKER_CONNECTED = "broker.connected"
    BROKER_RECONNECTED = "broker.reconnected"

    # Batman entry
    ENTRY_STARTED = "entry.started"
    ENTRY_COMPLETED = "entry.completed"
    ENTRY_FAILED = "entry.failed"

    # ATO protection
    ATO_CE_TRIGGERED = "ato.ce_triggered"
    ATO_PE_TRIGGERED = "ato.pe_triggered"
    ATO_CE_EXITED = "ato.ce_exited"
    ATO_PE_EXITED = "ato.pe_exited"
    ATO_EXIT_POINTS_CHANGED = (
        "ato.exit_points_changed"  # kept for wire-compat; prefer ATO_RETRACE_POINTS_CHANGED
    )
    ATO_RETRACE_POINTS_CHANGED = "ato.retrace_points_changed"
    ATO_STARTUP_SCAN_DONE = "ato.startup_scan_done"
    ATO_STARTUP_QTY_MISMATCH = "ato.startup_qty_mismatch"
    ATO_MAX_CYCLES_REACHED = "ato.max_cycles_reached"
    ATO_MONITOR_BREACH = "ato.monitor_breach"
    DYN_HEDGE_EXITED = "dyn_hedge.exited"

    # Trailing
    TRAILING_ACTIVATED = "trailing.activated"
    TRAILING_STOP_HIT = "trailing.stop_hit"
    HARD_STOP_HIT = "trailing.hard_stop_hit"
    PROFIT_TARGET_HIT = "trailing.profit_target_hit"

    # Hedge
    HEDGE_PLACED = "hedge.placed"
    HEDGE_CLOSED = "hedge.closed"
    HEDGE_BOX_CONFIRMATION_REQUEST = "hedge_box.confirmation_request"
    HEDGE_BOX_EXECUTED = "hedge_box.executed"

    # Position monitor
    MTM_UPDATE = "monitor.mtm_update"
    MTM_ALERT = "monitor.mtm_alert"

    # Emergency
    EMERGENCY_EXIT = "emergency.exit"
    ALL_POSITIONS_CLOSED = "emergency.all_closed"

    # Module lifecycle
    MODULE_STARTED = "module.started"
    MODULE_STOPPED = "module.stopped"
    MODULE_ERROR = "module.error"

    # Deployment
    DEPLOYMENT_CONFIRMED = "deployment.confirmed"
    BATMAN_COMPLETE = "deployment.batman_complete"
    DEPLOYMENT_RESTORED = "deployment.restored"  # auto-restore succeeded, all positions validated
    DEPLOYMENT_RESTORE_MISMATCH = (
        "deployment.restore_mismatch"  # file found but broker positions don't fully match
    )

    # System
    SYSTEM_STARTED = "system.started"
    SYSTEM_SHUTDOWN = "system.shutdown"


Subscriber = Callable[[Event, dict[str, Any]], None]


class EventBus:
    """Thread-safe publish / subscribe event bus.

    Usage::

        bus = EventBus()
        bus.subscribe(Event.ATO_CE_TRIGGERED, my_callback)
        bus.publish(Event.ATO_CE_TRIGGERED, {"strike": 25500, "spot": 25510})
    """

    def __init__(self, history_size: int = 500):
        self._subscribers: dict[Event, list[Subscriber]] = defaultdict(list)
        self._history: list[dict[str, Any]] = []
        self._history_size = history_size
        self._lock = threading.Lock()

    def subscribe(self, event: Event, callback: Subscriber) -> None:
        """Register *callback* for *event*."""
        with self._lock:
            self._subscribers[event].append(callback)

    def unsubscribe(self, event: Event, callback: Subscriber) -> None:
        """Remove *callback* from *event*."""
        with self._lock:
            try:
                self._subscribers[event].remove(callback)
            except ValueError:
                pass

    def publish(self, event: Event, data: dict[str, Any] | None = None) -> None:
        """Publish *event* with optional *data* to all subscribers."""
        data = data or {}
        record = {
            "event": event.value,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }

        with self._lock:
            self._history.append(record)
            if len(self._history) > self._history_size:
                self._history = self._history[-self._history_size :]
            listeners = list(self._subscribers.get(event, []))

        for cb in listeners:
            try:
                cb(event, data)
            except Exception:
                logger.exception("Event subscriber error for %s", event.value)

    def get_history(self, event: Event | None = None, last_n: int = 20) -> list[dict[str, Any]]:
        """Return recent event history, optionally filtered."""
        with self._lock:
            if event is None:
                return list(self._history[-last_n:])
            return [r for r in self._history if r["event"] == event.value][-last_n:]

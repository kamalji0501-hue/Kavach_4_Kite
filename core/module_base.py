"""
Batman v3 — Abstract module base class.

Every trading module (ATO, Batman entry, trailing, hedge, etc.)
extends ``ModuleBase``.  ``main.py`` manages them via a uniform
interface: ``start() / stop() / is_enabled() / status()``.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from .config import Config
from .event_bus import Event, EventBus
from .state import StateManager


class ModuleBase(ABC):
    """Base class for every Batman module.

    Sub-classes must:

    * Set ``name`` — unique slug used in config/state keys.
    * Implement ``_run()`` — the module's main logic loop.
    * Optionally override ``_on_stop()`` for cleanup.

    Lifecycle::

        module.start()   →  spawns a daemon thread running ``_run``
        module.stop()    →  sets ``_stop_event``, waits for thread

    Auto-restart: If a module crashes, it automatically restarts up to
    ``max_restarts`` times (default 3).  A 10-second cooldown prevents
    tight crash loops.
    """

    name: str = "base"

    # Auto-restart configuration
    MAX_RESTARTS = 3
    RESTART_COOLDOWN = 10.0  # seconds

    def __init__(
        self,
        broker,  # core.broker.BatmanBroker
        config: Config,
        state: StateManager,
        event_bus: EventBus,
        logger_name: str | None = None,
    ):
        self.broker = broker
        self.config = config
        self.state = state
        self.events = event_bus
        self.log = logging.getLogger(logger_name or f"batman.{self.name}")

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started_at: datetime | None = None
        self._error: str | None = None
        self._restart_count: int = 0

    # ── Lifecycle ────────────────────────────────────────────

    def is_enabled(self) -> bool:
        """True if module is enabled in config."""
        return bool(self.config.get(f"modules.{self.name}.enabled", False))

    def start(self) -> None:
        """Start the module in a background daemon thread."""
        if not self.is_enabled():
            self.log.info("[%s] Disabled in config — skipping", self.name)
            return

        if self._thread and self._thread.is_alive():
            self.log.warning("[%s] Already running", self.name)
            return

        self._stop_event.clear()
        self._error = None
        self._started_at = datetime.now()
        self._thread = threading.Thread(target=self._safe_run, daemon=True, name=f"mod-{self.name}")
        self._thread.start()
        self.events.publish(Event.MODULE_STARTED, {"module": self.name})
        self.log.info("[%s] Started", self.name)

    def stop(self, timeout: float = 10) -> None:
        """Signal the module to stop and wait for the thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._on_stop()
        self.events.publish(Event.MODULE_STOPPED, {"module": self.name})
        self.log.info("[%s] Stopped", self.name)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict[str, Any]:
        """Return a JSON-serializable summary of module health."""
        return {
            "name": self.name,
            "enabled": self.is_enabled(),
            "running": self.is_running,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "error": self._error,
            "restart_count": self._restart_count,
        }

    # ── Override these ───────────────────────────────────────

    @abstractmethod
    def _run(self) -> None:
        """Module's main loop.  Check ``self._stop_event.is_set()``
        frequently and return when it becomes True."""
        ...

    def _on_stop(self) -> None:
        """Optional cleanup called after thread exits."""
        return None

    # ── Internal ─────────────────────────────────────────────

    def _safe_run(self) -> None:
        """Run _run() with auto-restart on crash."""
        while not self._stop_event.is_set():
            try:
                self._run()
                break  # Normal exit from _run() — no restart needed
            except Exception as exc:
                self._error = str(exc)
                self.log.exception("[%s] Unhandled error", self.name)
                self.events.publish(
                    Event.MODULE_ERROR,
                    {"module": self.name, "error": str(exc), "restart_count": self._restart_count},
                )

                # Auto-restart logic
                if self._stop_event.is_set():
                    break

                if self._restart_count < self.MAX_RESTARTS:
                    self._restart_count += 1
                    self.log.warning(
                        "[%s] Auto-restarting (%d/%d) in %.0fs …",
                        self.name,
                        self._restart_count,
                        self.MAX_RESTARTS,
                        self.RESTART_COOLDOWN,
                    )
                    if self._stop_event.wait(timeout=self.RESTART_COOLDOWN):
                        break  # Stop requested during cooldown
                    # Loop back to retry _run()
                else:
                    self.log.error(
                        "[%s] Max restarts (%d) exhausted — module offline",
                        self.name,
                        self.MAX_RESTARTS,
                    )
                    self.events.publish(
                        Event.MODULE_ERROR,
                        {
                            "module": self.name,
                            "scenario": "max_restarts_exhausted",
                            "error": self._error or "unknown",
                            "restart_count": self._restart_count,
                        },
                    )
                    break

    def _sleep(self, seconds: float) -> bool:
        """Sleep that respects stop signals.  Returns True if stop
        was requested (caller should break its loop)."""
        return self._stop_event.wait(timeout=seconds)

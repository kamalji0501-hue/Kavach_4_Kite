#!/usr/bin/env python3
"""Run only the JAGRAN Telegram bot (standalone Phase 1)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from telegram.error import NetworkError, RetryAfter, TimedOut

from bat_telegram.bots.jagran.bot import build_application
from bat_telegram.incident_publisher import active_incident_count
from core.bot_health import start_health_heartbeat
from core.bot_instance_guard import bootstrap_exclusive_bot
from core.bot_launcher import warn_if_not_launched_via_bat
from core.bot_logging import configure_bot_logging
from core.telegram_runtime import PollingRestartPolicy

from core.batman_mode import bot_lock_path, ensure_runtime_layout

ROOT = Path(__file__).parent
LOCK_PATH = bot_lock_path("jagran", ROOT)


def _configure_logging() -> None:
    configure_bot_logging(workspace_root=ROOT, bot_name="jagran")


def main() -> None:
    _configure_logging()
    logger = logging.getLogger("run_jagran")
    ensure_runtime_layout(ROOT)
    warn_if_not_launched_via_bat("jagran")
    bootstrap_exclusive_bot("jagran", LOCK_PATH, logger, root=ROOT)

    start_health_heartbeat(
        ROOT,
        "jagran",
        extra_provider=lambda: {"open_incidents": active_incident_count()},
    )

    restart_policy = PollingRestartPolicy()
    session = 0
    failure_streak = 0
    while True:
        session += 1
        try:
            logger.info("Starting JAGRAN (session %s)...", session)
            app = build_application()
            app.run_polling(drop_pending_updates=True)
            failure_streak += 1
            restart_delay = restart_policy.delay_for_exception(None, failure_streak=failure_streak)
            logger.warning("JAGRAN polling exited — restarting in %.1fs", restart_delay)
        except KeyboardInterrupt:
            logger.info("JAGRAN stopped by operator")
            return
        except (RetryAfter, TimedOut, NetworkError) as exc:
            failure_streak += 1
            restart_delay = restart_policy.delay_for_exception(exc, failure_streak=failure_streak)
            logger.warning(
                "Telegram network error: %s — restarting in %.1fs",
                exc,
                restart_delay,
            )
        except SystemExit:
            raise
        except Exception as exc:
            failure_streak += 1
            restart_delay = restart_policy.delay_for_exception(exc, failure_streak=failure_streak)
            logger.error(
                "JAGRAN crashed: %s — restarting in %.1fs",
                exc,
                restart_delay,
                exc_info=True,
            )
        time.sleep(restart_delay)


if __name__ == "__main__":
    main()

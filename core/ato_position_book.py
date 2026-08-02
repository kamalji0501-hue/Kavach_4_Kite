"""Position book read with retries (Q62)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from core.ato_manual_leg_sync import symbol_qty_map

logger = logging.getLogger(__name__)


def read_positions_with_retry(
    broker: Any,
    *,
    max_retries: int = 3,
    retry_delay_seconds: float = 0.05,
    position_reader: Callable[[], Any] | None = None,
) -> tuple[dict[str, int] | None, bool]:
    """Read broker positions up to *max_retries* times.

    Returns ``(symbol_qty_map, had_transient_failure)``.
    ``symbol_qty_map`` is None only when all attempts failed.
    """
    had_failure = False
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            if position_reader is not None:
                raw = position_reader()
            else:
                raw = broker.get_positions()
            sym_qty = symbol_qty_map(raw)
            if sym_qty is None:
                had_failure = True
                logger.warning(
                    "Position book unreadable (attempt %d/%d)",
                    attempt,
                    max_retries,
                )
            else:
                if had_failure:
                    logger.info(
                        "Position book recovered on attempt %d/%d",
                        attempt,
                        max_retries,
                    )
                return sym_qty, had_failure
        except Exception as exc:
            had_failure = True
            last_exc = exc
            logger.warning(
                "Position book read failed (attempt %d/%d): %s",
                attempt,
                max_retries,
                exc,
            )

        if attempt < max_retries and retry_delay_seconds > 0:
            time.sleep(retry_delay_seconds)

    if last_exc is not None:
        logger.error("Position book unreadable after %d attempts: %s", max_retries, last_exc)
    return None, had_failure

"""Validate ATO protect strikes against Dhan instrument master (UAT + prod)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger("batman.strike_validation")


def _expiry_from_sell_leg(sell_leg: dict[str, Any]) -> date | None:
    raw = sell_leg.get("drvExpiryDate") or sell_leg.get("expiry_iso")
    if raw:
        text = str(raw)[:10]
        try:
            return date.fromisoformat(text)
        except ValueError:
            pass
    expiry_label = sell_leg.get("expiry")
    if expiry_label:
        from backtest_engine.resolver.instrument_master import _parse_expiry_date

        try:
            return _parse_expiry_date(str(expiry_label))
        except ValueError:
            logger.debug("Could not parse expiry label %r", expiry_label)
    return None


def validate_protect_strike_exists(
    *,
    side: str,
    protect_strike: int,
    sell_leg: dict[str, Any],
) -> tuple[bool, str | None]:
    """Return (ok, error_message). Uses same instrument master as prod."""
    opt = side.upper()
    if opt not in ("CE", "PE"):
        return False, f"Invalid side {side!r}"

    exp = _expiry_from_sell_leg(sell_leg)
    if exp is None:
        return False, (
            f"Cannot validate {opt} strike {protect_strike:,} — sell leg expiry unknown. "
            "Re-fetch positions and try again."
        )

    try:
        from backtest_engine.resolver.instrument_master import resolve_nifty_option

        resolve_nifty_option(strike=int(protect_strike), option_type=opt, expiry_date=exp)
        return True, None
    except LookupError:
        return False, (
            f"The strike you chose ({protect_strike:,} {opt}) is not available "
            f"for expiry {exp.isoformat()}."
        )
    except Exception as exc:
        logger.warning("Strike validation failed: %s", exc)
        return False, f"Strike validation failed: {exc}"

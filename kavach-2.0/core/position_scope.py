"""Position scope: partial lots, 1:2 ratio validation, managed qty scaling (KAVACH register)."""

from __future__ import annotations

import copy
from typing import Any

DEFAULT_LOT_SIZE = 65
SELL_TO_BUY_RATIO = 2
MIN_NIFTY_LOT_SIZE = 25  # sanity floor — reject broker lookups returning 0/1

LEG_ROLES = ("pe_buy", "pe_sell", "ce_buy", "ce_sell")


def resolve_nifty_lot_size(
    *,
    config_lot_size: int | None = None,
    broker_lot_size: int | None = None,
    default: int = DEFAULT_LOT_SIZE,
) -> int:
    """Return NIFTY F&O lot size for qty→lots conversion (broker positions are in qty)."""
    for candidate in (config_lot_size, broker_lot_size):
        if candidate is None:
            continue
        n = int(candidate)
        if n >= MIN_NIFTY_LOT_SIZE:
            return n
    return default


def qty_to_lots(qty: int, lot_size: int = DEFAULT_LOT_SIZE) -> int:
    """Whole lots implied by absolute share qty."""
    if lot_size <= 0:
        return 0
    return abs(int(qty)) // lot_size


def validate_side_ratio(
    buy_qty: int,
    sell_qty: int,
    *,
    lot_size: int = DEFAULT_LOT_SIZE,
    ratio: int = SELL_TO_BUY_RATIO,
) -> tuple[bool, str]:
    """Require exact buy:sell lot ratio (default 1:2 iron condor per side)."""
    buy_lots = qty_to_lots(buy_qty, lot_size)
    if buy_lots <= 0:
        return False, f"BUY leg must be at least {lot_size} qty (1 lot)."
    expected_sell_qty = buy_lots * ratio * lot_size
    if abs(int(sell_qty)) != expected_sell_qty:
        return (
            False,
            f"Ratio must be 1:{ratio} — SELL expected {expected_sell_qty} qty, "
            f"got {abs(int(sell_qty))}.",
        )
    return True, ""


def max_managed_lots(
    buy_qty: int,
    sell_qty: int,
    *,
    lot_size: int = DEFAULT_LOT_SIZE,
    ratio: int = SELL_TO_BUY_RATIO,
) -> int:
    """Maximum whole buy-lots the algo may manage on this side (strict 1:2)."""
    ok, _ = validate_side_ratio(buy_qty, sell_qty, lot_size=lot_size, ratio=ratio)
    if not ok:
        return 0
    buy_lots = qty_to_lots(buy_qty, lot_size)
    sell_lots = qty_to_lots(sell_qty, lot_size)
    return min(buy_lots, sell_lots // ratio)


def max_managed_lots_flexible(
    buy_qty: int,
    sell_qty: int,
    *,
    lot_size: int = DEFAULT_LOT_SIZE,
) -> int:
    """Max buy-lots to offer in wizard — no iron-condor ratio requirement."""
    buy_lots = qty_to_lots(buy_qty, lot_size)
    sell_lots = qty_to_lots(sell_qty, lot_size)
    if buy_lots <= 0 and sell_lots <= 0:
        return 0
    if buy_lots <= 0:
        return sell_lots
    if sell_lots <= 0:
        return buy_lots
    return min(buy_lots, sell_lots)


def side_lots_selection(
    buy_qty: int,
    sell_qty: int,
    *,
    lot_size: int = DEFAULT_LOT_SIZE,
) -> tuple[int, int, int, int]:
    """Return (max_lots, buy_lots, sell_lots, lot_size) for wizard lot picker."""
    lot_size = resolve_nifty_lot_size(config_lot_size=lot_size)
    buy_lots = qty_to_lots(buy_qty, lot_size)
    sell_lots = qty_to_lots(sell_qty, lot_size)
    max_l = max_managed_lots_flexible(buy_qty, sell_qty, lot_size=lot_size)
    if max_l <= 0:
        max_l = 1
    return max_l, buy_lots, sell_lots, lot_size


def managed_qty_for_side(
    managed_lots: int,
    *,
    lot_size: int = DEFAULT_LOT_SIZE,
    ratio: int = SELL_TO_BUY_RATIO,
) -> tuple[int, int]:
    """Return (buy_qty, sell_qty) for managed_lots on one side."""
    lots = max(0, int(managed_lots))
    buy_qty = lots * lot_size
    sell_qty = lots * ratio * lot_size
    return buy_qty, sell_qty


def apply_managed_lots_to_leg(
    leg: dict[str, Any],
    managed_qty: int,
) -> dict[str, Any]:
    """Copy leg dict; set broker_qty snapshot and managed qty."""
    out = copy.deepcopy(leg)
    out["broker_qty"] = int(out.get("broker_qty", out.get("qty", 0)))
    direction = str(out.get("direction", "LONG")).upper()
    qty = abs(int(managed_qty))
    out["qty"] = qty
    if direction == "SHORT":
        out["direction"] = "SHORT"
    else:
        out["direction"] = "LONG"
    return out


def scale_side(
    buy_leg: dict[str, Any],
    sell_leg: dict[str, Any],
    managed_lots: int,
    *,
    lot_size: int = DEFAULT_LOT_SIZE,
    ratio: int = SELL_TO_BUY_RATIO,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply managed lot count to BUY+SELL pair; preserve broker_qty (strict 1:2)."""
    buy_qty, sell_qty = managed_qty_for_side(managed_lots, lot_size=lot_size, ratio=ratio)
    buy_out = apply_managed_lots_to_leg(buy_leg, buy_qty)
    sell_out = apply_managed_lots_to_leg(sell_leg, sell_qty)
    sell_out["direction"] = "SHORT"
    return buy_out, sell_out


def scale_side_flexible(
    buy_leg: dict[str, Any],
    sell_leg: dict[str, Any],
    managed_lots: int,
    *,
    lot_size: int = DEFAULT_LOT_SIZE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scale by buy-lots; SELL qty follows the broker leg ratio (any structure)."""
    buy_broker = abs(int(buy_leg.get("qty", 0) or 0))
    sell_broker = abs(int(sell_leg.get("qty", 0) or 0))
    lots = max(0, int(managed_lots))

    if buy_broker > 0:
        managed_buy = min(lots * lot_size, buy_broker) if lots else buy_broker
        if sell_broker > 0:
            managed_sell = min(
                int(round(managed_buy * (sell_broker / buy_broker))),
                sell_broker,
            )
        else:
            managed_sell = 0
    elif sell_broker > 0:
        managed_sell = min(lots * lot_size, sell_broker) if lots else sell_broker
        managed_buy = 0
    else:
        managed_buy = 0
        managed_sell = 0

    buy_out = apply_managed_lots_to_leg(buy_leg, managed_buy)
    sell_out = apply_managed_lots_to_leg(sell_leg, managed_sell)
    sell_out["direction"] = "SHORT"
    return buy_out, sell_out


NIFTY_STRIKE_MIN = 10_000
NIFTY_STRIKE_MAX = 100_000
DEFAULT_ATO_STEP = 50


def auto_protect_strike(sell_strike: int, side: str, *, ato_step: int = DEFAULT_ATO_STEP) -> int:
    """Default ATO protect strike: CE sell + step, PE sell − step."""
    strike = int(sell_strike)
    if str(side).upper() == "CE":
        return strike + int(ato_step)
    return strike - int(ato_step)


def parse_and_validate_protect_strike(text: str) -> tuple[int | None, str | None]:
    """Parse custom ATO protect strike (whole number, multiple of 50)."""
    raw = (text or "").strip()
    if not raw:
        return None, (
            "Invalid input. Enter a strike on the NIFTY grid "
            "(multiple of 50, e.g. 24000, 24050, 24100)."
        )
    if "." in raw or "," in raw:
        return None, (
            "Invalid input. Decimal strikes are not allowed. "
            "Enter a whole number (multiple of 50)."
        )
    try:
        value = int(raw)
    except ValueError:
        return None, (
            "Invalid input. Enter a whole number strike "
            "(multiple of 50, e.g. 24000, 24050)."
        )
    if value <= 0:
        return None, "Invalid input. Strike must be a positive whole number."
    if value < NIFTY_STRIKE_MIN or value > NIFTY_STRIKE_MAX:
        return None, (
            f"Invalid input. Strike must be between {NIFTY_STRIKE_MIN:,} and "
            f"{NIFTY_STRIKE_MAX:,}."
        )
    if value % 50 != 0:
        return None, (
            "Invalid input. Strike must be a multiple of 50 "
            "(e.g. 24000, 24050, 24100)."
        )
    return value, None


def protect_strike_direction_warnings(
    side: str,
    sell_strike: int,
    protect_strike: int,
) -> list[str]:
    """Non-blocking warnings when protect strike is on the non-standard side of sell."""
    warnings: list[str] = []
    side_u = str(side).upper()
    sell = int(sell_strike)
    protect = int(protect_strike)
    if side_u == "CE" and protect <= sell:
        warnings.append(
            f"CE ATO strike ({protect:,}) is not above CE sell ({sell:,}) — non-standard"
        )
    if side_u == "PE" and protect >= sell:
        warnings.append(
            f"PE ATO strike ({protect:,}) is not below PE sell ({sell:,}) — non-standard"
        )
    return warnings


def parse_and_validate_ato_lots(text: str) -> tuple[int | None, str | None]:
    """Parse operator text for ATO lots (non-negative integers only)."""
    raw = (text or "").strip()
    if not raw:
        return None, (
            "Invalid input. Enter a whole number starting from 0 (e.g. 0, 6, 12)."
        )
    if "." in raw or "," in raw:
        return None, (
            "Invalid input. Decimal numbers are not allowed. "
            "Enter a whole number from 0."
        )
    try:
        value = int(raw)
    except ValueError:
        return None, (
            "Invalid input. Enter a whole number starting from 0 (e.g. 0, 6, 12)."
        )
    if value < 0:
        return None, (
            "Invalid input. Negative numbers are not allowed. "
            "Enter 0 or a positive whole number."
        )
    return value, None


def suggested_ato_lots(
    managed_lots: int | None,
    buy_qty: int,
    *,
    lot_size: int = DEFAULT_LOT_SIZE,
) -> int:
    """Default ATO lots shown in register wizard (legacy: managed BUY lots)."""
    if managed_lots is not None:
        return max(0, int(managed_lots))
    return qty_to_lots(buy_qty, lot_size)


def broker_buy_lots(buy_leg: dict[str, Any], *, lot_size: int = DEFAULT_LOT_SIZE) -> int:
    """Whole lots on broker BUY leg (broker_qty snapshot preferred)."""
    bq = abs(int(buy_leg.get("broker_qty", buy_leg.get("qty", 0)) or 0))
    return qty_to_lots(bq, lot_size)


def build_registration_scope(
    *,
    pe_enabled: bool,
    ce_enabled: bool,
    pe_managed_lots: int | None,
    ce_managed_lots: int | None,
    pe_ato_lots: int | None = None,
    ce_ato_lots: int | None = None,
    lot_size: int = DEFAULT_LOT_SIZE,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "pe_enabled": pe_enabled,
        "ce_enabled": ce_enabled,
        "pe_managed_lots": pe_managed_lots,
        "ce_managed_lots": ce_managed_lots,
        "pe_ato_lots": pe_ato_lots,
        "ce_ato_lots": ce_ato_lots,
        "lot_size": lot_size,
    }


def legacy_registration_scope_from_deployment(dep: dict[str, Any]) -> dict[str, Any]:
    """Infer scope for pre-v1.1 deployments (full qty, both sides if legs present)."""
    positions = dep.get("positions") or {}
    pe_enabled = positions.get("pe_buy") is not None and positions.get("pe_sell") is not None
    ce_enabled = positions.get("ce_buy") is not None and positions.get("ce_sell") is not None
    lot_size = int((dep.get("registration_scope") or {}).get("lot_size", DEFAULT_LOT_SIZE))
    scope = dep.get("registration_scope") or {}
    if scope:
        out = dict(scope)
        if pe_enabled and out.get("pe_ato_lots") is None:
            pe_buy = positions.get("pe_buy") or {}
            out["pe_ato_lots"] = qty_to_lots(
                int(pe_buy.get("qty", pe_buy.get("broker_qty", 0))), lot_size
            )
        if ce_enabled and out.get("ce_ato_lots") is None:
            ce_buy = positions.get("ce_buy") or {}
            out["ce_ato_lots"] = qty_to_lots(
                int(ce_buy.get("qty", ce_buy.get("broker_qty", 0))), lot_size
            )
        return out
    pe_lots = None
    ce_lots = None
    pe_ato_lots = None
    ce_ato_lots = None
    if pe_enabled:
        pe_buy = positions["pe_buy"]
        pe_lots = qty_to_lots(int(pe_buy.get("broker_qty", pe_buy.get("qty", 0))), lot_size)
        pe_ato_lots = qty_to_lots(int(pe_buy.get("qty", pe_buy.get("broker_qty", 0))), lot_size)
    if ce_enabled:
        ce_buy = positions["ce_buy"]
        ce_lots = qty_to_lots(int(ce_buy.get("broker_qty", ce_buy.get("qty", 0))), lot_size)
        ce_ato_lots = qty_to_lots(int(ce_buy.get("qty", ce_buy.get("broker_qty", 0))), lot_size)
    return build_registration_scope(
        pe_enabled=pe_enabled,
        ce_enabled=ce_enabled,
        pe_managed_lots=pe_lots,
        ce_managed_lots=ce_lots,
        pe_ato_lots=pe_ato_lots,
        ce_ato_lots=ce_ato_lots,
        lot_size=lot_size,
    )


def filter_positions_by_side(positions: list[dict[str, Any]], side: str) -> list[dict[str, Any]]:
    """Filter NIFTY legs to PE or CE."""
    side = side.upper()
    opt = "PE" if side == "PE" else "CE"

    def _is_side(pos: dict[str, Any]) -> bool:
        typed = str(pos.get("opt_type", "")).upper()
        if typed in ("PE", "CE"):
            return typed == opt
        sym = str(pos.get("symbol", "")).upper()
        return sym.endswith(opt)

    return [p for p in positions if _is_side(p)]


def filter_positions_by_direction(
    positions: list[dict[str, Any]], direction: str
) -> list[dict[str, Any]]:
    return [p for p in positions if str(p.get("direction", "")).upper() == direction.upper()]


def ensure_broker_qty_on_legs(selected: dict[str, dict | None]) -> dict[str, dict | None]:
    """Ensure each leg has broker_qty before scaling."""
    out: dict[str, dict | None] = {}
    for role, leg in selected.items():
        if leg is None:
            out[role] = None
            continue
        leg_copy = copy.deepcopy(leg)
        if "broker_qty" not in leg_copy:
            leg_copy["broker_qty"] = int(leg_copy.get("qty", 0))
        out[role] = leg_copy
    return out

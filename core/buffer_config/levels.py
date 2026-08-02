"""Convert between ATO buffer points and absolute NIFTY spot levels."""

from __future__ import annotations

from decimal import Decimal

from core.buffer_config.validator import DEFAULT_BUFFER_MAX, DEFAULT_BUFFER_MIN, validate_buffer

# Spot inputs at/above this are treated as absolute NIFTY levels (not buffer pts).
NIFTY_LEVEL_DETECT_MIN = Decimal("1000")
NIFTY_LEVEL_MIN = Decimal("10000")
NIFTY_LEVEL_MAX = Decimal("50000")


def nifty_level_from_buffer(
    buffer: Decimal,
    *,
    side: str,
    kind: str,
    sell_strike: int | Decimal,
) -> Decimal:
    """Map buffer → absolute NIFTY trigger/exit level (engine formulas)."""
    strike = Decimal(sell_strike)
    side_u = (side or "").upper()
    kind_l = (kind or "").lower()
    if side_u == "CE":
        # CE: trigger = strike + entry, exit = strike − exit_buf
        return strike + buffer if kind_l == "entry" else strike - buffer
    # PE: trigger = strike − entry, exit = strike + exit_buf
    return strike - buffer if kind_l == "entry" else strike + buffer


def buffer_from_nifty_level(
    level: Decimal,
    *,
    side: str,
    kind: str,
    sell_strike: int | Decimal,
) -> Decimal:
    """Map absolute NIFTY level → buffer points for storage/engine."""
    strike = Decimal(sell_strike)
    side_u = (side or "").upper()
    kind_l = (kind or "").lower()
    if side_u == "CE":
        return level - strike if kind_l == "entry" else strike - level
    return strike - level if kind_l == "entry" else level - strike


def looks_like_nifty_level(value: Decimal) -> bool:
    """True when operator typed an absolute spot (e.g. 24160), not buffer pts."""
    return value >= NIFTY_LEVEL_DETECT_MIN


def parse_and_validate_user_buffer_or_level(
    text: str,
    *,
    side: str,
    kind: str,
    sell_strike: int | None,
    min_value: Decimal = DEFAULT_BUFFER_MIN,
    max_value: Decimal = DEFAULT_BUFFER_MAX,
) -> tuple[Decimal | None, str | None, str]:
    """Parse custom input as buffer points or absolute NIFTY level.

    Returns ``(buffer, error, mode)`` where mode is ``\"buffer\"`` or ``\"level\"``.
    """
    from core.buffer_config.parser import parse_buffer_text
    from core.buffer_config.schema import _quantize

    try:
        value = parse_buffer_text(text)
    except ValueError:
        return (
            None,
            "Invalid input. Enter buffer points (e.g. 5, 0, -10) or a NIFTY level (e.g. 24160).",
            "buffer",
        )

    if looks_like_nifty_level(value):
        if sell_strike is None:
            return (
                None,
                "NIFTY level needs the sell strike from an armed deployment / register leg.",
                "level",
            )
        if value < NIFTY_LEVEL_MIN or value > NIFTY_LEVEL_MAX:
            return (
                None,
                f"NIFTY level must be between {NIFTY_LEVEL_MIN} and {NIFTY_LEVEL_MAX}.",
                "level",
            )
        buf = buffer_from_nifty_level(
            value, side=side, kind=kind, sell_strike=sell_strike
        )
        ok, msg = validate_buffer(buf, min_value=min_value, max_value=max_value)
        if not ok:
            return (
                None,
                f"NIFTY {format(value, 'f').rstrip('0').rstrip('.')} → "
                f"{format(buf, 'f').rstrip('0').rstrip('.')} pts from sell {int(sell_strike)}. {msg}",
                "level",
            )
        return _quantize(buf), None, "level"

    ok, msg = validate_buffer(value, min_value=min_value, max_value=max_value)
    if not ok:
        return None, f"Invalid buffer points. {msg}", "buffer"
    return _quantize(value), None, "buffer"


def format_buffer_with_level(
    buffer: Decimal,
    *,
    side: str,
    kind: str,
    sell_strike: int | None,
) -> str:
    """Human label: ``-10 pts → NIFTY 24,160`` when sell strike known."""
    pts = format(buffer, "f").rstrip("0").rstrip(".") or "0"
    if sell_strike is None:
        return f"{pts} pts"
    level = nifty_level_from_buffer(
        buffer, side=side, kind=kind, sell_strike=sell_strike
    )
    level_i = int(level) if level == level.to_integral_value() else level
    if isinstance(level_i, int):
        return f"{pts} pts → NIFTY {level_i:,}"
    return f"{pts} pts → NIFTY {level}"

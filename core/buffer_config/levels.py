"""Convert between internal ATO buffer offsets and absolute NIFTY spot levels."""

from __future__ import annotations

from decimal import Decimal

# Absolute NIFTY spot range accepted from operators (Buffer Manager / Register).
NIFTY_LEVEL_DETECT_MIN = Decimal("1000")
NIFTY_LEVEL_MIN = Decimal("10000")
NIFTY_LEVEL_MAX = Decimal("50000")


def format_nifty_level_number(value: Decimal | int | float) -> str:
    """Format a NIFTY level for UI — keeps trailing zeros (23800 → 23,800)."""
    dec = Decimal(str(value))
    if dec == dec.to_integral_value():
        return f"{int(dec):,}"
    # Fractional only: trim fractional trailing zeros, never the integer part.
    text = format(dec, "f")
    if "." in text:
        whole, frac = text.split(".", 1)
        frac = frac.rstrip("0")
        return f"{int(whole):,}.{frac}" if frac else f"{int(whole):,}"
    return f"{int(dec):,}"


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
    """Map absolute NIFTY level → internal buffer offset for storage/engine."""
    strike = Decimal(sell_strike)
    side_u = (side or "").upper()
    kind_l = (kind or "").lower()
    if side_u == "CE":
        return level - strike if kind_l == "entry" else strike - level
    return strike - level if kind_l == "entry" else level - strike


def looks_like_nifty_level(value: Decimal) -> bool:
    """True when operator typed an absolute spot (e.g. 24160)."""
    return value >= NIFTY_LEVEL_DETECT_MIN


def parse_and_validate_user_buffer_or_level(
    text: str,
    *,
    side: str,
    kind: str,
    sell_strike: int | None,
    min_value: Decimal | None = None,
    max_value: Decimal | None = None,
) -> tuple[Decimal | None, str | None, str]:
    """Parse operator input as an absolute NIFTY level only.

    No strike-relative buffer range limit — any NIFTY level in
    ``[NIFTY_LEVEL_MIN, NIFTY_LEVEL_MAX]`` is accepted. ``min_value`` /
    ``max_value`` are ignored (kept for call-site compatibility).

    Returns ``(buffer_offset, error, mode)`` where mode is always ``\"level\"``
    on success (internal storage remains strike-relative offsets).
    """
    del min_value, max_value
    from core.buffer_config.parser import parse_buffer_text
    from core.buffer_config.schema import _quantize

    try:
        value = parse_buffer_text(text)
    except ValueError:
        return (
            None,
            "Invalid input. Enter a NIFTY level (e.g. 24160).",
            "level",
        )

    if not looks_like_nifty_level(value):
        return (
            None,
            "Enter a NIFTY level (e.g. 24160).",
            "level",
        )

    if sell_strike is None:
        return (
            None,
            "NIFTY level needs the sell strike from an armed deployment / register leg.",
            "level",
        )
    if value < NIFTY_LEVEL_MIN or value > NIFTY_LEVEL_MAX:
        return (
            None,
            f"NIFTY level must be between {format_nifty_level_number(NIFTY_LEVEL_MIN)} "
            f"and {format_nifty_level_number(NIFTY_LEVEL_MAX)}.",
            "level",
        )
    buf = buffer_from_nifty_level(value, side=side, kind=kind, sell_strike=sell_strike)
    return _quantize(buf), None, "level"


def format_buffer_with_level(
    buffer: Decimal,
    *,
    side: str,
    kind: str,
    sell_strike: int | None,
) -> str:
    """Human label: ``NIFTY 24,160`` when sell strike known."""
    if sell_strike is None:
        return "NIFTY level unavailable"
    level = nifty_level_from_buffer(
        buffer, side=side, kind=kind, sell_strike=sell_strike
    )
    return f"NIFTY {format_nifty_level_number(level)}"


def ato_absolute_levels(
    *,
    pe_sell_strike: int | None,
    ce_sell_strike: int | None,
    pe_entry_buffer: Decimal | int | float,
    ce_entry_buffer: Decimal | int | float,
    pe_exit_buffer: Decimal | int | float,
    ce_exit_buffer: Decimal | int | float,
) -> dict[str, int | None]:
    """Absolute ATO levels shared by Buffer Manager, ATO Status, and the engine.

    Same-side hysteresis only (exit must sit strictly beyond entry). Never clamp
    PE entry against CE exit — that silent rewrite made Buffer Manager show one
    PE fire level while ATO Status showed another.
    """
    pe_entry = Decimal(str(pe_entry_buffer))
    ce_entry = Decimal(str(ce_entry_buffer))
    pe_exit = Decimal(str(pe_exit_buffer))
    ce_exit = Decimal(str(ce_exit_buffer))
    min_hyst = Decimal("1")

    pe_trigger = (
        int(nifty_level_from_buffer(pe_entry, side="PE", kind="entry", sell_strike=pe_sell_strike))
        if pe_sell_strike is not None
        else None
    )
    ce_trigger = (
        int(nifty_level_from_buffer(ce_entry, side="CE", kind="entry", sell_strike=ce_sell_strike))
        if ce_sell_strike is not None
        else None
    )
    pe_exit_level = (
        int(nifty_level_from_buffer(pe_exit, side="PE", kind="exit", sell_strike=pe_sell_strike))
        if pe_sell_strike is not None
        else None
    )
    ce_exit_level = (
        int(nifty_level_from_buffer(ce_exit, side="CE", kind="exit", sell_strike=ce_sell_strike))
        if ce_sell_strike is not None
        else None
    )

    if ce_trigger is not None and ce_exit_level is not None and ce_exit_level >= ce_trigger:
        ce_exit_level = int(Decimal(ce_trigger) - min_hyst)
    if pe_trigger is not None and pe_exit_level is not None and pe_exit_level <= pe_trigger:
        pe_exit_level = int(Decimal(pe_trigger) + min_hyst)

    return {
        "pe_trigger": pe_trigger,
        "ce_trigger": ce_trigger,
        "pe_exit": pe_exit_level,
        "ce_exit": ce_exit_level,
    }
"""Buffer field serialization for deployment + state (backward compatible)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any

from core.buffer_config.validator import DEFAULT_BUFFER_MAX, DEFAULT_BUFFER_MIN, validate_buffer

QUANTIZE = Decimal("0.01")


class BufferKind(str, Enum):
    PREDEFINED = "PREDEFINED"
    CUSTOM = "CUSTOM"


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(QUANTIZE, rounding=ROUND_HALF_UP)


def serialize_buffer_field(
    value: Decimal, kind: BufferKind = BufferKind.PREDEFINED
) -> dict[str, str]:
    q = _quantize(value)
    return {"type": kind.value, "value": format(q, "f").rstrip("0").rstrip(".") or "0"}


def normalize_buffer_field(raw: Any, *, default: Decimal = Decimal("0")) -> Decimal:
    """Load buffer from deployment field (legacy int, Decimal, or typed dict).

    Must accept ``Decimal`` — ATO restore / Quick Tune store normalized Decimals
    in live state; dropping them silently zeros buffers and fires at sell strike.
    """
    if raw is None:
        return default
    if isinstance(raw, Decimal):
        return _quantize(raw)
    if isinstance(raw, (int, float)):
        return _quantize(Decimal(str(raw)))
    if isinstance(raw, str):
        return _quantize(Decimal(raw))
    if isinstance(raw, dict):
        val = raw.get("value", default)
        return _quantize(Decimal(str(val)))
    return default


def legacy_int_from_buffer(raw: Any, *, default: int = 0) -> int:
    """Best-effort int for legacy consumers (truncates toward zero)."""
    return int(normalize_buffer_field(raw, default=Decimal(default)))


def buffer_display(raw: Any) -> str:
    """Compact label for logs — no buffer-points / predefined wording."""
    val = normalize_buffer_field(raw)
    return format(val, "f").rstrip("0").rstrip(".") or "0"


def parse_and_validate_user_buffer(
    text: str,
    *,
    min_value: Decimal = DEFAULT_BUFFER_MIN,
    max_value: Decimal = DEFAULT_BUFFER_MAX,
) -> tuple[Decimal | None, str | None]:
    """Parse raw offset for internal/tests only — not used by Buffer Manager UI."""
    from core.buffer_config.parser import parse_buffer_text

    try:
        value = parse_buffer_text(text)
    except ValueError:
        return (
            None,
            "Invalid number. Enter a numeric value.",
        )
    ok, msg = validate_buffer(value, min_value=min_value, max_value=max_value)
    if not ok:
        return None, msg
    return _quantize(value), None

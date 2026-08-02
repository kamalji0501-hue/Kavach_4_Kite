"""Buffer value validation rules."""

from __future__ import annotations

from decimal import Decimal

# Signed buffers allowed for ATO testing (negative = fire early / closer to spot).
DEFAULT_BUFFER_MIN = Decimal("-500")
DEFAULT_BUFFER_MAX = Decimal("100")


def validate_buffer(
    value: Decimal,
    *,
    min_value: Decimal = DEFAULT_BUFFER_MIN,
    max_value: Decimal = DEFAULT_BUFFER_MAX,
) -> tuple[bool, str]:
    """Accept positive, zero, and negative buffers within [min_value, max_value]."""
    if value < min_value:
        return False, f"Buffer must be at least {min_value}."
    if value > max_value:
        return False, f"Buffer must not exceed {max_value}."
    return True, ""

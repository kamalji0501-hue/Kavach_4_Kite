"""Parse user buffer input text to Decimal."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_buffer_text(text: str) -> Decimal:
    """Parse numeric buffer string; raises ValueError on invalid input."""
    raw = (text or "").strip().replace(",", "")
    if not raw:
        raise ValueError("empty")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("not numeric") from exc
    return value

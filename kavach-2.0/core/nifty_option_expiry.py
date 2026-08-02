"""NIFTY option expiry parsing — fixture, Sensibull OCR, and Dhan trading symbols."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

_MONTH_MAP = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# 09 Jun 2026, 9 Jun, optional year (rolls forward if already past)
_EXPIRY_LABEL_RE = re.compile(
    r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?:\s+(\d{4}))?\b",
    re.I,
)
# NIFTY-Jun2026-23400-CE or compact NIFTY25JUN23400CE tail
_DHAN_SYMBOL_RE = re.compile(
    r"^NIFTY-([A-Za-z]{3})(\d{4})-(\d{4,5})-(CE|PE)$",
    re.I,
)
_DHAN_EXPIRY_TOKEN_RE = re.compile(r"^([A-Za-z]{3})(\d{4}|\d{2})$", re.I)


def _month_num(abbr: str) -> int:
    key = abbr.lower()[:3]
    if key not in _MONTH_MAP:
        raise ValueError(f"Unknown month: {abbr!r}")
    return _MONTH_MAP[key]


def _normalize_year(year: int, month: int, day: int, *, today: date | None = None) -> int:
    """If label omits year, pick current or next calendar year when date already passed."""
    today = today or date.today()
    if year > 99:
        return year
    year = 2000 + year if year < 100 else year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return year
    if candidate < today and year == today.year:
        return today.year + 1
    return year


def parse_expiry_label(text: str, *, today: date | None = None) -> date:
    """Parse '09 Jun 2026', '16 Jun', or ISO '2026-06-16'."""
    text = str(text).strip()
    if len(text) == 10 and text[4] == "-":
        return date.fromisoformat(text)

    m = _EXPIRY_LABEL_RE.search(text)
    if not m:
        token = parse_dhan_expiry_token(text)
        if token:
            return token
        raise ValueError(f"Cannot parse expiry label: {text!r}")

    day = int(m.group(1))
    month = _month_num(m.group(2))
    year = int(m.group(3)) if m.group(3) else _normalize_year(date.today().year, month, day, today=today)
    return date(year, month, day)


def parse_dhan_expiry_token(token: str) -> date | None:
    """Parse middle segment of Dhan symbol: ``Jun2026``, ``Jun26``."""
    m = _DHAN_EXPIRY_TOKEN_RE.match(str(token).strip())
    if not m:
        return None
    month = _month_num(m.group(1))
    raw_year = m.group(2)
    year = int(raw_year) if len(raw_year) == 4 else 2000 + int(raw_year)
    # Day unknown from token alone — callers match weekly by full symbol or fixture
    return date(year, month, 1)


def parse_dhan_trading_symbol(symbol: str) -> tuple[date | None, int | None, str | None]:
    """Return (expiry_month_anchor, strike, CE|PE) from ``NIFTY-Jun2026-23400-CE``."""
    sym = str(symbol).strip()
    m = _DHAN_SYMBOL_RE.match(sym)
    if not m:
        tail = re.search(r"(\d{4,5})(CE|PE)$", sym.replace("-", ""))
        if tail:
            return None, int(tail.group(1)), tail.group(2).upper()
        return None, None, None
    month = _month_num(m.group(1))
    year = int(m.group(2))
    strike = int(m.group(3))
    opt = m.group(4).upper()
    return date(year, month, 1), strike, opt


def trading_symbol_matches_expiry(symbol: str, target: date) -> bool:
    """True when Dhan hyphenated symbol month/year matches target expiry."""
    exp_anchor, _, _ = parse_dhan_trading_symbol(symbol)
    if exp_anchor is None:
        return False
    return exp_anchor.year == target.year and exp_anchor.month == target.month


def expiry_label_from_date(value: date) -> str:
    return value.strftime("%d %b %Y")


def expiry_date_from_positions(positions: list[dict[str, Any]]) -> date | None:
    """Resolve expiry for live option quotes when no UAT fixture (prod/dev)."""
    for pos in positions:
        raw = str(pos.get("expiry") or "").strip()
        if raw:
            try:
                return parse_expiry_label(raw)
            except ValueError:
                pass
        sym = str(pos.get("symbol") or "").strip()
        anchor, _, _ = parse_dhan_trading_symbol(sym)
        if anchor is not None:
            return anchor
    return None


def fixture_expiry_date(fixture: dict[str, Any]) -> date:
    """Resolve weekly expiry from fixture ``expiry_date`` or ``expiry_label``."""
    raw = str(fixture.get("expiry_date") or "").strip()
    if raw:
        return parse_expiry_label(raw[:10] if len(raw) >= 10 and raw[4] == "-" else raw)
    label = str(fixture.get("expiry_label") or "").strip()
    if label:
        return parse_expiry_label(label)
    raise ValueError("Fixture missing expiry_date / expiry_label")


def legs_from_fixture(fixture: dict[str, Any]) -> list[tuple[int, str]]:
    """(strike, CE|PE) pairs from fixture legs — drives securityId resolution."""
    out: list[tuple[int, str]] = []
    for leg in fixture.get("legs") or []:
        if not isinstance(leg, dict):
            continue
        try:
            out.append((int(leg["strike"]), str(leg.get("type", "")).upper()))
        except (TypeError, ValueError, KeyError):
            continue
    return out


def legs_missing_prices(
    positions: list[dict[str, Any]],
) -> list[tuple[int, str]]:
    """Positions that still need a live or fixture premium."""
    import math

    missing: list[tuple[int, str]] = []
    for pos in positions:
        try:
            strike = int(pos.get("strike", 0))
            opt = str(pos.get("opt_type", "")).upper()
        except (TypeError, ValueError):
            continue
        if opt not in ("CE", "PE"):
            continue
        raw = pos.get("avg_price")
        try:
            px = float(raw)
            if px > 0 and not math.isnan(px) and not math.isinf(px):
                continue
        except (TypeError, ValueError):
            pass
        missing.append((strike, opt))
    return missing


def infer_spot_from_fixture(fixture: dict[str, Any]) -> float:
    """Best spot for fixture metadata: explicit field, cache, or leg strikes."""
    spot = fixture.get("spot_at_capture")
    try:
        if spot and float(spot) > 0:
            return round(float(spot), 2)
    except (TypeError, ValueError):
        pass
    try:
        from core.nifty_ltp_feed import get_cached_nifty_ltp

        ltp = get_cached_nifty_ltp()
        if ltp and float(ltp) > 0:
            return round(float(ltp), 2)
    except Exception:
        pass
    strikes = [int(leg["strike"]) for leg in fixture.get("legs") or [] if "strike" in leg]
    if strikes:
        return float(sum(strikes) / len(strikes))
    return 0.0

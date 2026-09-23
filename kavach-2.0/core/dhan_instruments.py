"""Map Kavach / Kite NIFTY option names to Dhan Tradehull symbols.

Tradehull looks up SEM_CUSTOM_SYMBOL or SEM_TRADING_SYMBOL. Dhan's daytime
custom name is ``NIFTY 08 SEP 24000 CALL`` (zero-padded day, 3-letter month,
CALL/PUT). Kavach ATO still sends Kite compact ``NIFTY2690824000CE``.
ZerodhaBroker already rewrites compact names; BatmanBroker must do this
before Tradehull.order_placement.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from core.zerodha_instruments import compact_nifty_symbol, parse_kite_weekly_expiry

logger = logging.getLogger("batman.dhan.instruments")

_MONTH_NUM = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
_MONTH_NAME = {v: k for k, v in _MONTH_NUM.items()}

# Already-Dhan custom (daytime book): NIFTY 08 SEP 24000 CALL
_DHAN_CUSTOM = re.compile(
    r"^NIFTY\s+(\d{1,2})\s+([A-Z]{3})\s+(\d{4,5})\s+(CALL|PUT|CE|PE)$",
    re.I,
)
# Dhan SEM_TRADING_SYMBOL: NIFTY-Sep2026-24000-CE (month-level, not unique)
_DHAN_TRADING = re.compile(
    r"^NIFTY-([A-Za-z]{3})(\d{4})-(\d{4,5})-(CE|PE)$",
    re.I,
)
# Kite monthly: NIFTY26SEP24000CE (no calendar day — use last Tuesday)
_KITE_MONTHLY = re.compile(
    r"^NIFTY(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{4,5})(CE|PE)$",
    re.I,
)
_KITE_RIGHT = re.compile(r"(\d{4,5})(CE|PE)$", re.I)

_INDEX_PASS = {
    "NIFTY",
    "NIFTY50",
    "NIFTY 50",
    "NSE:NIFTY 50",
    "INDIA VIX",
    "SENSEX",
}


def last_tuesday(year: int, month: int) -> date:
    """NSE Nifty monthly expiry is the last Tuesday of the month (holiday shifts aside)."""
    if month == 12:
        day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        day = date(year, month + 1, 1) - timedelta(days=1)
    while day.weekday() != 1:
        day -= timedelta(days=1)
    return day


def _right_word(raw: str) -> str:
    tok = str(raw or "").strip().upper()
    if tok in {"PE", "PUT", "P"}:
        return "PUT"
    return "CALL"


def format_dhan_custom(expiry: date, strike: int, option_type: str) -> str:
    mon = _MONTH_NAME[expiry.month]
    return f"NIFTY {expiry.day:02d} {mon} {int(strike)} {_right_word(option_type)}"


def _parse_strike_right(compact: str) -> tuple[int, str] | None:
    m = _KITE_RIGHT.search(compact)
    if not m:
        return None
    return int(m.group(1)), m.group(2).upper()


def dhan_custom_symbol_from_any(symbol: str) -> str:
    """Return Tradehull-friendly Dhan custom symbol, or the original if not NIFTY F&O.

    Complete Dhan custom names are normalised (zero-pad day, CALL/PUT).
    Kite weekly compact uses the day in the symbol. Kite monthly uses last Tuesday.
    """
    raw = (symbol or "").strip()
    if not raw:
        return raw
    if raw.upper() in _INDEX_PASS:
        return raw.upper() if raw.upper() == "NIFTY" else raw

    custom = _DHAN_CUSTOM.fullmatch(" ".join(raw.upper().split()))
    if custom:
        day = int(custom.group(1))
        mon = custom.group(2).upper()
        strike = int(custom.group(3))
        right = _right_word(custom.group(4))
        return f"NIFTY {day:02d} {mon} {strike} {right}"

    compact = compact_nifty_symbol(raw)
    weekly_exp = parse_kite_weekly_expiry(compact)
    if weekly_exp is not None:
        parsed = _parse_strike_right(compact)
        if parsed:
            strike, right = parsed
            return format_dhan_custom(weekly_exp, strike, right)

    monthly = _KITE_MONTHLY.fullmatch(compact)
    if monthly:
        year = 2000 + int(monthly.group(1))
        month = _MONTH_NUM[monthly.group(2).upper()]
        strike = int(monthly.group(3))
        right = monthly.group(4).upper()
        return format_dhan_custom(last_tuesday(year, month), strike, right)

    trading = _DHAN_TRADING.fullmatch(raw.replace(" ", ""))
    if trading:
        # Ambiguous across weeklies in the same month — still send what Dhan stored.
        return raw.strip()

    return raw


def map_dhan_order_symbol(symbol: str) -> str:
    """Map for orders/LTP. Logs compact → custom rewrites."""
    mapped = dhan_custom_symbol_from_any(symbol)
    if mapped != (symbol or "").strip():
        logger.info("Dhan symbol map %s → %s", symbol, mapped)
    return mapped

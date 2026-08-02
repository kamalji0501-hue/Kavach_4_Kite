"""
Batman v3 — Utility helpers.

Expiry calendar, trading-hours checks, strike calculations, and
common date/time functions used across modules.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")


# ── NSE 2026 holidays (update yearly) ──────────────────────

NSE_HOLIDAYS_2026: list[date] = [
    date(2026, 1, 26),  # Republic Day
    date(2026, 2, 17),  # Mahashivratri (tentative)
    date(2026, 3, 10),  # Holi
    date(2026, 3, 30),  # Id-Ul-Fitr (Ram Navami)
    date(2026, 3, 31),  # Id-Ul-Fitr
    date(2026, 4, 2),  # Mahavir Jayanti
    date(2026, 4, 3),  # Good Friday
    date(2026, 4, 14),  # Dr. Ambedkar Jayanti
    date(2026, 5, 1),  # Maharashtra Day
    date(2026, 5, 25),  # Buddha Purnima (tentative)
    date(2026, 6, 7),  # Bakrid (tentative)
    date(2026, 7, 6),  # Muharram (tentative)
    date(2026, 8, 15),  # Independence Day
    date(2026, 8, 16),  # Parsi New Year (tentative)
    date(2026, 9, 4),  # Milad un-Nabi (tentative)
    date(2026, 10, 2),  # Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 10, 21),  # Dussehra Holiday
    date(2026, 11, 9),  # Diwali (Laxmi Puja)
    date(2026, 11, 10),  # Diwali (Balipratipada)
    date(2026, 11, 30),  # Guru Nanak Jayanti
    date(2026, 12, 25),  # Christmas
]


# ── Market / trading day helpers ───────────────────────────


def now_ist() -> datetime:
    """Current timestamp in IST."""
    return datetime.now(IST)


def today_ist() -> date:
    """Today's date in IST."""
    return now_ist().date()


def is_trading_day(d: date | None = None, extra_holidays: list[date] | None = None) -> bool:
    """True if *d* is a weekday and NOT an NSE holiday."""
    d = d or today_ist()
    if d.weekday() >= 5:
        return False
    all_holidays = NSE_HOLIDAYS_2026 + (extra_holidays or [])
    return d not in all_holidays


def is_market_hours(open_time: str = "09:15", close_time: str = "15:30") -> bool:
    """True if current IST time is between open and close."""
    now = now_ist().time()
    return time.fromisoformat(open_time) <= now <= time.fromisoformat(close_time)


def next_trading_day(from_date: date | None = None) -> date:
    """Return the next date that is a valid trading day."""
    d = (from_date or today_ist()) + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


# ── Expiry calendar helpers ────────────────────────────────


def current_week_expiry(expiry_weekday: int = 1, ref: date | None = None) -> date:
    """Return the weekly expiry date for the current (or given) week.

    ``expiry_weekday`` — 0=Mon … 6=Sun.  Default 1 = Tuesday.
    If the computed date is a holiday, the expiry shifts to the
    preceding trading day.
    """
    ref = ref or today_ist()
    days_ahead = (expiry_weekday - ref.weekday()) % 7
    exp = ref + timedelta(days=days_ahead)
    if exp < ref:
        exp += timedelta(weeks=1)
    # If expiry is a holiday, shift left
    while not is_trading_day(exp):
        exp -= timedelta(days=1)
    return exp


def is_expiry_day(expiry_weekday: int = 1, ref: date | None = None) -> bool:
    """True if *ref* (or today) is the weekly expiry day."""
    ref = ref or today_ist()
    return ref == current_week_expiry(expiry_weekday, ref)


def is_entry_day(entry_weekday: int = 2, ref: date | None = None) -> bool:
    """True if *ref* (or today) is the scheduled entry day.
    Default 2 = Wednesday."""
    ref = ref or today_ist()
    return ref.weekday() == entry_weekday and is_trading_day(ref)


def next_entry_date(from_date: date | None = None, entry_weekday: int = 2) -> date:
    """Return the next valid entry day at or after *from_date* + 1 day.

    Skips NSE holidays and weekends.  Default entry day is Wednesday (2).
    """
    d = (from_date or today_ist()) + timedelta(days=1)
    while True:
        if d.weekday() == entry_weekday and is_trading_day(d):
            return d
        d += timedelta(days=1)


def day_name_to_weekday(name: str) -> int:
    """Convert a day name string to a weekday integer (0=Mon … 6=Sun)."""
    days = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    return days.get(name.strip().lower(), 2)


def entry_date_this_week(
    entry_weekday: int = 2,
    ref: date | None = None,
    extra_holidays: list[date] | None = None,
) -> date:
    """Return the actual entry date for the week containing *ref*.

    Finds the scheduled entry weekday in the same Mon–Sun week as *ref*.
    If that date is an NSE holiday, shifts FORWARD to the next trading day
    (e.g. Wednesday holiday → Thursday = 3 DTE, still the same week).
    """
    ref = ref or today_ist()
    monday = ref - timedelta(days=ref.weekday())
    scheduled = monday + timedelta(days=entry_weekday)
    while not is_trading_day(scheduled, extra_holidays):
        scheduled += timedelta(days=1)
    return scheduled


def is_entry_window(
    entry_weekday: int = 2,
    ref: date | None = None,
    extra_holidays: list[date] | None = None,
) -> bool:
    """True if *ref* (or today) is the holiday-adjusted entry date for this week.

    Unlike ``is_entry_day()``, returns True on Thursday when the configured
    Wednesday entry day is an NSE holiday (holiday shifts entry forward).
    """
    ref = ref or today_ist()
    return ref == entry_date_this_week(entry_weekday, ref, extra_holidays)


# ── Strike math ────────────────────────────────────────────

NIFTY_STRIKE_STEP = 50


def round_to_strike(value: float, step: int = NIFTY_STRIKE_STEP) -> int:
    """Round *value* to the nearest option strike increment."""
    return int(round(value / step) * step)


def center_line(spot: float, step: int = NIFTY_STRIKE_STEP) -> int:
    """ATM strike from spot.  Alias of ``round_to_strike``."""
    return round_to_strike(spot, step)


def otm_count_from_distance(distance: int, step: int = NIFTY_STRIKE_STEP) -> int:
    """Convert a point-based distance to an OTM step count.

    Example: distance=300, step=50 → 6.
    """
    return max(1, distance // step)


def calculate_strikes(
    spot: float, sell_distance: int = 300, hedge_gap: int = 250, step: int = NIFTY_STRIKE_STEP
):
    """Return a dict with the four Batman iron-condor strikes.

    Batman structure: BUY leg is CLOSER to ATM than SELL leg.
    ``hedge_gap`` is the distance from ATM to the BUY strikes.
    ``sell_distance`` is the distance from ATM to the (outer) SELL strikes.

    Example (spot=25200, sell_distance=300, hedge_gap=250)::

        {
            "center": 25200,
            "ce_sell": 25500, "ce_buy": 25450,   # sell is outer, buy is inner
            "pe_sell": 24900, "pe_buy": 24950,   # sell is outer, buy is inner
            "sell_otm": 6,    "buy_otm": 5,
        }
    """
    c = center_line(spot, step)
    return {
        "center": c,
        "ce_sell": c + sell_distance,
        "ce_buy": c + hedge_gap,
        "pe_sell": c - sell_distance,
        "pe_buy": c - hedge_gap,
        "sell_otm": otm_count_from_distance(sell_distance, step),
        "buy_otm": otm_count_from_distance(hedge_gap, step),
    }


# ── Option symbol helpers ─────────────────────────────────

_OPTION_SYM_RE = re.compile(r"^([A-Z]+\d{2}[A-Z]{3})(\d+)(CE|PE)$")


def parse_option_symbol(sym: str):
    """Parse a Dhan/NSE option symbol into its three components.

    Symbol format examples::

        "NIFTY25APR23000CE"   →  ("NIFTY25APR", 23000, "CE")
        "NIFTY25APR22000PE"   →  ("NIFTY25APR", 22000, "PE")
        "NIFTY26JAN24500CE"   →  ("NIFTY26JAN", 24500, "CE")

    The prefix encodes BOTH the underlying AND the expiry month, e.g.
    ``"NIFTY25APR"`` means NIFTY, April 2025 expiry.  Two symbols sharing
    the same prefix are always on the same expiry.

    Returns:
        ``(prefix, strike, opt_type)``  — e.g. ``("NIFTY25APR", 23000, "CE")``
        ``(None, None, None)``          — if the symbol cannot be parsed
    """
    m = _OPTION_SYM_RE.match(sym.strip())
    if not m:
        return None, None, None
    return m.group(1), int(m.group(2)), m.group(3)


def build_ato_symbols(
    ce_sell_symbol: str,
    pe_sell_symbol: str,
    strike_step: int = 50,
) -> dict:
    """Derive the ATO protect symbols from the two sell-leg symbols.

    The ATO protect strike is exactly one strike step further OTM than
    the sell strike — on the **same expiry** as the deployed legs.
    The expiry is extracted directly from the sell symbol prefix so no
    external date lookup is needed.

    Rules::

        ce_ato_strike = ce_sell_strike + strike_step   (higher CE strike = more OTM)
        pe_ato_strike = pe_sell_strike - strike_step   (lower  PE strike = more OTM)

    Examples (all 13 Apr expiry)::

        CE sell "NIFTY25APR23000CE" → ATO "NIFTY25APR23050CE"  (strike 23050)
        PE sell "NIFTY25APR22000PE" → ATO "NIFTY25APR21950PE"  (strike 21950)

    Args:
        ce_sell_symbol: Trading symbol of the CE sell leg,  e.g. ``"NIFTY25APR23000CE"``
        pe_sell_symbol: Trading symbol of the PE sell leg,  e.g. ``"NIFTY25APR22000PE"``
        strike_step:    NIFTY option strike interval (default 50).

    Returns:
        dict with keys::

            {
                "ce_protect_symbol": "NIFTY25APR23050CE",
                "ce_protect_strike": 23050,
                "pe_protect_symbol": "NIFTY25APR21950PE",
                "pe_protect_strike": 21950,
            }

        All four values are ``None`` / ``0`` if either symbol cannot be parsed.
    """
    ce_prefix, ce_sell_strike, _ = parse_option_symbol(ce_sell_symbol)
    pe_prefix, pe_sell_strike, _ = parse_option_symbol(pe_sell_symbol)

    if not ce_prefix or not pe_prefix:
        return {
            "ce_protect_symbol": None,
            "ce_protect_strike": 0,
            "pe_protect_symbol": None,
            "pe_protect_strike": 0,
        }

    ce_ato_strike = ce_sell_strike + strike_step
    pe_ato_strike = pe_sell_strike - strike_step

    return {
        "ce_protect_symbol": f"{ce_prefix}{ce_ato_strike}CE",
        "ce_protect_strike": ce_ato_strike,
        "pe_protect_symbol": f"{pe_prefix}{pe_ato_strike}PE",
        "pe_protect_strike": pe_ato_strike,
    }


# ── Formatting helpers ─────────────────────────────────────


def fmt_rupees(amount: float) -> str:
    """Format ₹ value with Indian comma style for display."""
    sign = "-" if amount < 0 else ""
    val = abs(amount)
    if val >= 1_00_000:
        return f"{sign}₹{val:,.0f}"
    return f"{sign}₹{val:,.2f}"


def pnl_emoji(amount: float) -> str:
    """Return green/red emoji based on P&L sign."""
    if amount > 0:
        return "🟢"
    elif amount < 0:
        return "🔴"
    return "⚪"


def seconds_until(target_time: str) -> float:
    """Seconds from now-IST until *target_time* (HH:MM today)."""
    now = now_ist()
    t = time.fromisoformat(target_time)
    target_dt = datetime.combine(now.date(), t, tzinfo=IST)
    diff = (target_dt - now).total_seconds()
    return diff if diff > 0 else 0.0


def get_venv_python(root: str | Path) -> Path:
    """Return the venv interpreter path (Windows Scripts/ or Linux bin/)."""
    import shutil
    import sys
    from pathlib import Path as _Path

    root_path = _Path(root)
    win = root_path / ".venv" / "Scripts" / "python.exe"
    nix = root_path / ".venv" / "bin" / "python"
    if sys.platform == "win32":
        if win.is_file():
            return win
        if nix.is_file():
            return nix
        return win
    if nix.is_file():
        return nix
    if win.is_file():
        return win
    sys_py = shutil.which("python3") or shutil.which("python")
    if sys_py:
        return _Path(sys_py)
    return nix

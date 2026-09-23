"""Kite NFO instrument dump — resolve NIFTY option tradingsymbol + lot size.

GET /instruments/NFO once per day. Used for order tradingsymbols.
Docs: https://kite.trade/docs/connect/v3/market-quotes/#retrieving-the-full-instrument-list
"""

from __future__ import annotations

import csv
import re
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("batman.zerodha.instruments")

_CACHE_NAME = "kite_nfo_instruments.csv"
_TTL = timedelta(hours=12)


@dataclass(frozen=True)
class KiteNiftyOption:
    tradingsymbol: str
    instrument_token: int
    expiry: date
    strike: int
    option_type: str
    lot_size: int
    tick_size: float = 0.05


def _cache_path(root: Path | None = None) -> Path:
    from core.batman_mode import data_reports_base, workspace_root

    base = data_reports_base(root or workspace_root())
    path = base / "MarketData" / _CACHE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def refresh_nfo_instruments(client, *, root: Path | None = None, force: bool = False) -> Path:
    path = _cache_path(root)
    if path.is_file() and not force:
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        if age < _TTL and path.stat().st_size > 1000:
            return path
    raw = client.request("GET", "/instruments/NFO", raw=True, quote=True, timeout=30.0)
    if isinstance(raw, bytes) and raw.strip():
        path.write_bytes(raw)
        logger.info("Kite NFO instruments cached (%s bytes)", path.stat().st_size)
    return path


def _parse_expiry(raw: str) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def load_nifty_options(client=None, *, root: Path | None = None) -> list[KiteNiftyOption]:
    path = _cache_path(root)
    if client is not None:
        try:
            path = refresh_nfo_instruments(client, root=root)
        except Exception as exc:
            logger.warning("Kite instruments refresh failed: %s", exc)
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    out: list[KiteNiftyOption] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        name = str(row.get("name") or "").upper()
        if name != "NIFTY":
            continue
        opt = str(row.get("instrument_type") or "").upper()
        if opt not in {"CE", "PE"}:
            continue
        exp = _parse_expiry(str(row.get("expiry") or ""))
        if exp is None:
            continue
        try:
            strike = int(float(row.get("strike") or 0))
            token = int(row.get("instrument_token") or 0)
            lot = int(float(row.get("lot_size") or 65))
        except (TypeError, ValueError):
            continue
        try:
            tick = float(row.get("tick_size") or 0.05)
        except (TypeError, ValueError):
            tick = 0.05
        out.append(
            KiteNiftyOption(
                tradingsymbol=str(row.get("tradingsymbol") or ""),
                instrument_token=token,
                expiry=exp,
                strike=strike,
                option_type=opt,
                lot_size=lot or 65,
                tick_size=tick,
            )
        )
    return out


def nearest_nifty_expiry(options: list[KiteNiftyOption], *, on_or_after: date | None = None) -> date | None:
    day = on_or_after or date.today()
    future = sorted({row.expiry for row in options if row.expiry >= day})
    return future[0] if future else None


def resolve_nifty_option_kite(
    strike: int,
    option_type: str,
    expiry: date,
    *,
    client=None,
    root: Path | None = None,
) -> KiteNiftyOption | None:
    opt = str(option_type).upper()
    rows = [
        row
        for row in load_nifty_options(client, root=root)
        if row.strike == int(strike) and row.option_type == opt and row.expiry == expiry
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: r.tradingsymbol)
    return rows[0]


def compact_nifty_symbol(symbol: str) -> str:
    return (symbol or "").replace(" ", "").replace("-", "").upper()


# Weekly Kite: NIFTY2690823950PE (YY + month digit 1-9 + DD + strike).
# Oct/Nov/Dec weeklies use O/N/D: NIFTY26O0824000PE.
# Monthly Kite: NIFTY26SEP24200CE.
_KITE_WEEKLY_NIFTY = re.compile(r"^(NIFTY\d{2}[1-9OND]\d{2})(\d{4,5})(CE|PE)$")
_KITE_MONTHLY_NIFTY = re.compile(r"^(NIFTY\d{2}[A-Z]{3})(\d+)(CE|PE)$")
_KITE_WEEKLY_DATE = re.compile(r"^NIFTY(\d{2})([1-9OND])(\d{2})(\d{4,5})(CE|PE)$")
_KITE_MONTH_LETTER = {"O": 10, "N": 11, "D": 12}
_KITE_MONTH_TO_LETTER = {10: "O", 11: "N", 12: "D"}


def is_complete_kite_nifty_option(symbol: str) -> bool:
    compact = compact_nifty_symbol(symbol)
    return bool(_KITE_WEEKLY_NIFTY.fullmatch(compact) or _KITE_MONTHLY_NIFTY.fullmatch(compact))


def nifty_expiry_key(symbol: str) -> str | None:
    """Expiry token shared by all legs of one Batman book, e.g. NIFTY26908."""
    compact = compact_nifty_symbol(symbol)
    m = _KITE_WEEKLY_NIFTY.fullmatch(compact)
    if m:
        return m.group(1)
    m = _KITE_MONTHLY_NIFTY.fullmatch(compact)
    if m:
        return m.group(1)
    return None




def parse_kite_weekly_expiry(symbol: str) -> date | None:
    """NIFTY2690824000PE -> date(2026, 9, 8)."""
    compact = compact_nifty_symbol(symbol)
    m = _KITE_WEEKLY_DATE.fullmatch(compact)
    if not m:
        return None
    year = 2000 + int(m.group(1))
    mon_tok = m.group(2)
    day = int(m.group(3))
    if mon_tok.isdigit():
        month = int(mon_tok)
        if month < 1 or month > 9:
            return None
    else:
        month = _KITE_MONTH_LETTER.get(mon_tok)
        if month is None:
            return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def kite_weekly_prefix(expiry: date) -> str:
    """date(2026, 9, 8) -> NIFTY26908."""
    yy = expiry.year % 100
    if 1 <= expiry.month <= 9:
        mon = str(expiry.month)
    else:
        mon = _KITE_MONTH_TO_LETTER[expiry.month]
    return f"NIFTY{yy:02d}{mon}{expiry.day:02d}"


_KITE_MONTH_ABBR = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}
_KITE_ABBR_TO_MONTH = {v: k for k, v in _KITE_MONTH_ABBR.items()}


def kite_monthly_prefix(expiry: date) -> str:
    """date(2026, 9, 29) -> NIFTY26SEP (monthly series key)."""
    return f"NIFTY{expiry.year % 100:02d}{_KITE_MONTH_ABBR[expiry.month]}"


def _last_tuesday(year: int, month: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    while cursor.weekday() != 1:  # Tuesday
        cursor -= timedelta(days=1)
    return cursor


def parse_kite_monthly_expiry(
    symbol: str,
    *,
    client=None,
    root: Path | None = None,
) -> date | None:
    """NIFTY26SEP23300CE -> date(2026, 9, 29) via NFO instrument dump.

    Monthly Kite symbols encode YY+MMM only (no day). Resolve the real expiry
    from the cached instruments list; fall back to last-Tuesday convention.
    """
    compact = compact_nifty_symbol(symbol)
    m = _KITE_MONTHLY_NIFTY.fullmatch(compact)
    if not m:
        # Also accept bare prefix NIFTY26SEP
        if re.fullmatch(r"NIFTY\d{2}[A-Z]{3}", compact):
            prefix = compact
        else:
            return None
    else:
        prefix = m.group(1)
    rows = load_nifty_options(client, root=root)
    for row in rows:
        if nifty_expiry_key(row.tradingsymbol) == prefix:
            return row.expiry
    ym = re.fullmatch(r"NIFTY(\d{2})([A-Z]{3})", prefix)
    if not ym:
        return None
    month = _KITE_ABBR_TO_MONTH.get(ym.group(2))
    if month is None:
        return None
    return _last_tuesday(2000 + int(ym.group(1)), month)


def parse_kite_option_expiry(
    symbol: str,
    *,
    client=None,
    root: Path | None = None,
) -> date | None:
    """Weekly or monthly Kite NIFTY option -> expiry date."""
    weekly = parse_kite_weekly_expiry(symbol)
    if weekly is not None:
        return weekly
    return parse_kite_monthly_expiry(symbol, client=client, root=root)


def register_expiry_keys(expiry: date, *, root: Path | None = None) -> set[str]:
    """Symbol prefixes that belong to one Register expiry date.

    On monthly expiry Tuesday, both weekly (NIFTY26929) and monthly (NIFTY26SEP)
    series share the same calendar date — Register must accept both.
    """
    keys = {kite_weekly_prefix(expiry)}
    mprefix = kite_monthly_prefix(expiry)
    monthly_day = parse_kite_monthly_expiry(mprefix, root=root)
    if monthly_day == expiry:
        keys.add(mprefix)
    return keys


def kite_tradingsymbol_from_any(
    symbol: str,
    *,
    client=None,
    root: Path | None = None,
) -> str:
    """Accept Kavach/Dhan-ish labels and return a Kite NFO tradingsymbol.

    Complete weekly/monthly symbols are returned unchanged. Never remap a
    next-week contract (NIFTY26908...) onto nearest expiry.
    """
    raw = (symbol or "").strip()
    if not raw:
        return raw
    compact = compact_nifty_symbol(raw)
    if is_complete_kite_nifty_option(compact):
        return compact
    m = re.search(r"(\d{4,5})(CE|PE)$", compact, re.I)
    strike = int(m.group(1)) if m else 0
    opt = (m.group(2).upper() if m else "")
    exp: date | None = None
    dm = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", raw)
    if dm:
        exp = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
    if exp is None:
        rows = load_nifty_options(client, root=root)
        exp = nearest_nifty_expiry(rows)
    if strike and opt and exp:
        hit = resolve_nifty_option_kite(strike, opt, exp, client=client, root=root)
        if hit:
            return hit.tradingsymbol
    return compact or raw

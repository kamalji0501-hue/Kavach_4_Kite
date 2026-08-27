"""Kite NFO instrument dump — resolve NIFTY option tradingsymbol + lot size.

GET /instruments/NFO once per day. Used for order tradingsymbols.
Docs: https://kite.trade/docs/connect/v3/market-quotes/#retrieving-the-full-instrument-list
"""

from __future__ import annotations

import csv
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


def kite_tradingsymbol_from_any(
    symbol: str,
    *,
    client=None,
    root: Path | None = None,
) -> str:
    """Accept Kavach/Dhan-ish labels and return a Kite NFO tradingsymbol."""
    raw = (symbol or "").strip()
    if not raw:
        return raw
    compact = raw.replace(" ", "").replace("-", "").upper()
    if compact.startswith("NIFTY") and compact.endswith(("CE", "PE")) and compact[:5] == "NIFTY":
        # Already looks like NIFTY25SEP24200CE
        if compact[5:7].isdigit() and compact[7:10].isalpha():
            return compact
    import re

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

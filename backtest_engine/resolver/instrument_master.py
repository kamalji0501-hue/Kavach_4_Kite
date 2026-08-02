"""Resolve NIFTY option strikes via Dhan instrument master (production securityId + symbol)."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

logger = logging.getLogger("backtest_engine.instrument_master")

_DHAN_DETAILED_CSV = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
_NIFTY_LOT_SIZE = 65
_CACHE_DIR = Path(__file__).resolve().parents[1] / "cache"
_MASTER_USECOLS = (
    "UNDERLYING_SYMBOL",
    "INSTRUMENT",
    "SM_EXPIRY_DATE",
    "STRIKE_PRICE",
    "OPTION_TYPE",
    "SYMBOL_NAME",
    "DISPLAY_NAME",
    "SECURITY_ID",
    "LOT_SIZE",
)
# Process-local cache — full CSV is ~37MB and slow on Chromebook/Windows laptops.
_MASTER_MEM_CACHE: dict[str, pd.DataFrame] = {}


@dataclass(frozen=True)
class ResolvedInstrument:
    """One NIFTY option leg as Dhan / KAVACH would see it."""

    strike: int
    option_type: str
    expiry_date: str
    trading_symbol: str
    security_id: str
    lot_size: int
    source: str

    def to_broker_row(
        self,
        *,
        net_qty: int,
        avg_price: float,
    ) -> dict[str, Any]:
        """Build a positions-API-shaped row for ``filter_nifty_positions``."""
        return {
            "tradingSymbol": self.trading_symbol,
            "netQty": net_qty,
            "avgPrice": avg_price,
            "costPrice": avg_price,
            "drvStrikePrice": float(self.strike),
            "drvExpiryDate": self.expiry_date,
            "drvOptionType": self.option_type,
            "securityId": self.security_id,
            "exchangeSegment": "NSE_FNO",
            "productType": "MARGIN",
        }


def _parse_expiry_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse expiry date: {value!r}")


def _nifty_subset_path(day: date) -> Path:
    return _CACHE_DIR / f"nifty_optidx_{day.isoformat()}.csv"


def _read_master_csv(path: Path | StringIO) -> pd.DataFrame:
    """Read instrument CSV with only columns needed for NIFTY option resolve."""
    try:
        return pd.read_csv(path, usecols=list(_MASTER_USECOLS), low_memory=False)
    except ValueError:
        # Older/partial caches may lack some columns — fall back to full read.
        return pd.read_csv(path, low_memory=False)


def _to_nifty_optidx(master: pd.DataFrame) -> pd.DataFrame:
    required = {"UNDERLYING_SYMBOL", "INSTRUMENT"}
    if not required.issubset(master.columns):
        return master
    return master[
        (master["UNDERLYING_SYMBOL"] == "NIFTY") & (master["INSTRUMENT"] == "OPTIDX")
    ].copy()


def load_instrument_master(*, use_cache: bool = True) -> pd.DataFrame:
    """Load Dhan detailed scrip master filtered to NFO NIFTY options.

    Prefers a small daily NIFTY-OPTIDX subset CSV (~0.4MB) over the full
    ~37MB master so Chromebook/Windows UAT tests stay responsive.
    """
    day = date.today()
    mem_key = day.isoformat()
    if use_cache and mem_key in _MASTER_MEM_CACHE:
        return _MASTER_MEM_CACHE[mem_key]

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    subset_path = _nifty_subset_path(day)
    full_cache_path = _CACHE_DIR / f"api-scrip-master-detailed_{day.isoformat()}.csv"

    if use_cache and subset_path.is_file():
        logger.info("Loading NIFTY OPTIDX instrument subset: %s", subset_path)
        df = pd.read_csv(subset_path, low_memory=False)
        _MASTER_MEM_CACHE[mem_key] = df
        return df

    if use_cache and full_cache_path.is_file():
        logger.info("Building NIFTY OPTIDX subset from cached master: %s", full_cache_path)
        master = _read_master_csv(full_cache_path)
    else:
        logger.info("Downloading Dhan instrument master …")
        response = httpx.get(_DHAN_DETAILED_CSV, timeout=120.0)
        response.raise_for_status()
        if use_cache:
            full_cache_path.write_text(response.text, encoding="utf-8")
        master = _read_master_csv(StringIO(response.text))

    df = _to_nifty_optidx(master)
    if use_cache and not df.empty:
        df.to_csv(subset_path, index=False)
        logger.info("Wrote NIFTY OPTIDX subset (%s rows): %s", len(df), subset_path)

    _MASTER_MEM_CACHE[mem_key] = df
    return df


def _nifty_options_df(master: pd.DataFrame) -> pd.DataFrame:
    df = master[
        (master["UNDERLYING_SYMBOL"] == "NIFTY") & (master["INSTRUMENT"] == "OPTIDX")
    ].copy()
    df["_expiry"] = pd.to_datetime(df["SM_EXPIRY_DATE"], errors="coerce").dt.date
    return df


def resolve_nifty_option(
    *,
    strike: int,
    option_type: str,
    expiry_date: str | date,
    master: pd.DataFrame | None = None,
) -> ResolvedInstrument:
    """Find ``tradingSymbol`` and ``securityId`` for one strike (same IDs as live orders)."""
    opt = option_type.upper().strip()
    if opt not in ("CE", "PE"):
        raise ValueError(f"option_type must be CE or PE, got {option_type!r}")

    exp = expiry_date if isinstance(expiry_date, date) else _parse_expiry_date(str(expiry_date))
    if master is None:
        master = load_instrument_master()

    opts = _nifty_options_df(master)
    rows = opts[
        (opts["_expiry"] == exp)
        & (opts["STRIKE_PRICE"].astype(float) == float(strike))
        & (opts["OPTION_TYPE"].astype(str).str.upper() == opt)
    ]
    if rows.empty:
        raise LookupError(
            f"No NIFTY {opt} strike {strike} for expiry {exp.isoformat()} in instrument master"
        )

    row = rows.iloc[0]
    symbol = str(row.get("SYMBOL_NAME") or row.get("DISPLAY_NAME") or "").strip()
    if not symbol:
        raise LookupError(f"Instrument row missing SYMBOL_NAME for {strike}{opt} {exp}")

    lot = int(float(row.get("LOT_SIZE") or _NIFTY_LOT_SIZE))
    if lot != _NIFTY_LOT_SIZE:
        logger.warning(
            "Instrument master lot_size=%s for %s (expected %s)",
            lot,
            symbol,
            _NIFTY_LOT_SIZE,
        )

    return ResolvedInstrument(
        strike=int(strike),
        option_type=opt,
        expiry_date=exp.isoformat(),
        trading_symbol=symbol,
        security_id=str(int(row["SECURITY_ID"])),
        lot_size=_NIFTY_LOT_SIZE,
        source="instrument_master",
    )


def list_nifty_option_expiries(
    *,
    master: pd.DataFrame | None = None,
    on_or_after: date | None = None,
) -> list[date]:
    """Sorted unique NIFTY weekly expiries from the instrument master."""
    if master is None:
        master = load_instrument_master()
    cutoff = on_or_after or date.today()
    opts = _nifty_options_df(master)
    expiries = sorted({d for d in opts["_expiry"].dropna().unique() if d >= cutoff})
    return expiries


def _legs_resolve_for_expiry(
    legs: list[dict[str, Any]],
    expiry_date: date,
    *,
    master: pd.DataFrame,
) -> bool:
    for leg in legs:
        try:
            resolve_nifty_option(
                strike=int(leg["strike"]),
                option_type=str(leg["type"]),
                expiry_date=expiry_date,
                master=master,
            )
        except LookupError:
            return False
    return True


def resolve_fixture_trading_expiry(
    fixture_expiry: date,
    legs: list[dict[str, Any]],
    *,
    master: pd.DataFrame | None = None,
    today: date | None = None,
) -> tuple[date, bool]:
    """Resolve UAT fixture expiry; roll forward when past or strikes missing.

    Returns ``(expiry_date, rolled_forward)``.
    """
    if master is None:
        master = load_instrument_master()
    today = today or date.today()

    if fixture_expiry >= today and _legs_resolve_for_expiry(legs, fixture_expiry, master=master):
        return fixture_expiry, False

    for candidate in list_nifty_option_expiries(master=master, on_or_after=today):
        if _legs_resolve_for_expiry(legs, candidate, master=master):
            if candidate != fixture_expiry:
                logger.warning(
                    "UAT fixture expiry %s rolled to %s (strikes remapped in instrument master)",
                    fixture_expiry.isoformat(),
                    candidate.isoformat(),
                )
            return candidate, candidate != fixture_expiry

    missing = []
    for leg in legs:
        try:
            resolve_nifty_option(
                strike=int(leg["strike"]),
                option_type=str(leg["type"]),
                expiry_date=fixture_expiry,
                master=master,
            )
        except LookupError:
            missing.append(f"{leg.get('strike')}{leg.get('type')}")
    raise LookupError(
        f"No instrument master expiry on/after {today.isoformat()} covers fixture legs "
        f"(fixture expiry {fixture_expiry.isoformat()}, missing {', '.join(missing)})"
    )


def resolved_to_dict(inst: ResolvedInstrument) -> dict[str, Any]:
    return asdict(inst)

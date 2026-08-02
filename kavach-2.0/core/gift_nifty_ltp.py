"""GIFT NIFTY LTP — off-hours validation feed (DRISHTI only, not for ATO/KAVACH)."""

from __future__ import annotations

import json
import logging
import time
import zoneinfo
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from core.exceptions import BrokerConnectionError
from core.nifty_ltp import _extract_dhan_error, is_rate_limit_error

logger = logging.getLogger("batman.gift_nifty_ltp")

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CACHE_PATH = _ROOT / "data" / "gift_nifty_ltp_cache.json"
_DHAN_LTP_URL = "https://api.dhan.co/v2/marketfeed/ltp"

# NSE index segment — from ``Dependencies/all_instrument *.csv`` (SEM_SMST_SECURITY_ID).
GIFT_NIFTY_SECURITY_ID = 5024
GIFT_NIFTY_SYMBOL = "GIFTNIFTY"
GIFT_NIFTY_DISPLAY_NAME = "Gift Nifty"


def _parse_gift_nifty_ltp_from_marketfeed_payload(payload: dict[str, Any]) -> float:
    outer = payload.get("data")
    if not isinstance(outer, dict):
        raise BrokerConnectionError(f"GIFT NIFTY LTP missing from REST response: {payload}")

    candidates: list[dict[str, Any]] = [outer]
    nested = outer.get("data")
    if isinstance(nested, dict):
        candidates.append(nested)

    sid = str(GIFT_NIFTY_SECURITY_ID)
    quote: dict[str, Any] | None = None
    for block in candidates:
        idx_data = block.get("IDX_I")
        if not isinstance(idx_data, dict):
            continue
        raw = idx_data.get(sid) or idx_data.get(GIFT_NIFTY_SECURITY_ID)
        if isinstance(raw, dict):
            quote = raw
            break

    if not quote:
        raise BrokerConnectionError(f"GIFT NIFTY LTP missing from REST response: {payload}")

    last_price = quote.get("last_price")
    if last_price is None:
        raise BrokerConnectionError(f"GIFT NIFTY last_price missing: {quote}")
    ltp = float(last_price)
    if ltp <= 0:
        raise BrokerConnectionError(f"Non-positive GIFT NIFTY LTP: {ltp}")
    return ltp


@dataclass
class GiftNiftyCacheSnapshot:
    ltp: float
    updated_at: str
    source: str = "dhan_rest"
    symbol: str = GIFT_NIFTY_SYMBOL
    security_id: int = GIFT_NIFTY_SECURITY_ID
    probe_healthy: bool = True
    poll_interval_seconds: int = 2
    consecutive_failures: int = 0

    def age_seconds(self, now: datetime | None = None) -> float:
        now = now or datetime.now(_IST)
        try:
            updated = datetime.fromisoformat(self.updated_at)
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=_IST)
            return max(0.0, (now - updated.astimezone(_IST)).total_seconds())
        except (TypeError, ValueError):
            return float("inf")

    def is_fresh(self, max_age_seconds: float, now: datetime | None = None) -> bool:
        return self.probe_healthy and self.ltp > 0 and self.age_seconds(now) <= max_age_seconds


def default_cache_path() -> Path:
    return _DEFAULT_CACHE_PATH


def read_gift_nifty_cache(path: Path | None = None) -> GiftNiftyCacheSnapshot | None:
    cache_path = path or _DEFAULT_CACHE_PATH
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            return None
        return GiftNiftyCacheSnapshot(
            ltp=float(raw.get("ltp", 0.0)),
            updated_at=str(raw.get("updated_at", "")),
            source=str(raw.get("source", "dhan_rest")),
            symbol=str(raw.get("symbol", GIFT_NIFTY_SYMBOL)),
            security_id=int(raw.get("security_id", GIFT_NIFTY_SECURITY_ID)),
            probe_healthy=bool(raw.get("probe_healthy", True)),
            poll_interval_seconds=int(raw.get("poll_interval_seconds", 2)),
            consecutive_failures=int(raw.get("consecutive_failures", 0)),
        )
    except Exception as exc:
        logger.warning("Could not read GIFT NIFTY cache from %s: %s", cache_path, exc)
        return None


def write_gift_nifty_cache(snapshot: GiftNiftyCacheSnapshot, path: Path | None = None) -> None:
    cache_path = path or _DEFAULT_CACHE_PATH
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(asdict(snapshot), fh, indent=2)
    tmp.replace(cache_path)


def seed_gift_nifty_cache(
    ltp: float,
    *,
    poll_interval_seconds: int = 2,
    path: Path | None = None,
) -> GiftNiftyCacheSnapshot:
    now = datetime.now(_IST)
    snap = GiftNiftyCacheSnapshot(
        ltp=float(ltp),
        updated_at=now.isoformat(),
        probe_healthy=True,
        poll_interval_seconds=poll_interval_seconds,
        consecutive_failures=0,
    )
    write_gift_nifty_cache(snap, path)
    return snap


def append_gift_nifty_audit_log(
    log_dir: Path,
    now: datetime,
    ltp: float,
    source: str,
    *,
    event: str = "probe",
) -> Path:
    """Daily audit under DRISHTI ``logs/nifty_ltp/gift_nifty_ltp_YYYYMMDD.log``."""
    log_dir.mkdir(parents=True, exist_ok=True)
    day = now.strftime("%Y%m%d")
    log_path = log_dir / f"gift_nifty_ltp_{day}.log"
    line = (
        f"{now.strftime('%Y-%m-%d %H:%M:%S')} IST,"
        f"{ltp:.2f},"
        f"{source},"
        f"{event}\n"
    )
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(line)
    return log_path


def fetch_gift_nifty_ltp_rest(client_code: str, access_token: str) -> float:
    response = httpx.post(
        _DHAN_LTP_URL,
        headers={
            "access-token": access_token,
            "client-id": client_code,
            "Content-Type": "application/json",
        },
        json={"IDX_I": [GIFT_NIFTY_SECURITY_ID]},
        timeout=15.0,
    )
    if response.status_code == 429:
        raise BrokerConnectionError(
            f"Too many requests (HTTP 429). {_extract_dhan_error(response)}"
        )
    if response.status_code != 200:
        raise BrokerConnectionError(_extract_dhan_error(response))
    return _parse_gift_nifty_ltp_from_marketfeed_payload(response.json())


def fetch_gift_nifty_ltp_rest_with_retry(
    client_code: str,
    access_token: str,
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
    backoff_multiplier: float = 2.0,
    rate_limit_extra_seconds: float = 10.0,
) -> float:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return fetch_gift_nifty_ltp_rest(client_code, access_token)
        except BrokerConnectionError as exc:
            last_exc = exc
            if attempt >= max_attempts - 1:
                break
            msg = str(exc)
            delay = (
                rate_limit_extra_seconds * (backoff_multiplier**attempt)
                if is_rate_limit_error(msg)
                else base_delay_seconds * (backoff_multiplier**attempt)
            )
            logger.warning(
                "GIFT NIFTY REST retry %s/%s in %.1fs: %s",
                attempt + 1,
                max_attempts,
                delay,
                msg[:120],
            )
            time.sleep(delay)

    assert last_exc is not None
    raise last_exc

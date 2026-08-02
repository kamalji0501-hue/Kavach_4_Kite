"""NIFTY position display enrich — shared prod + UAT.

Broker avg/fill price is always preferred. UAT fixture prices and live marketfeed
are fallbacks only when avg_price is missing (ATO protect legs, stale rows).
"""

from __future__ import annotations

import logging
import math
import re
from datetime import date
from typing import Any

import pandas as pd

logger = logging.getLogger("batman.uat_position_enrich")


def format_expiry_display(value: str | date | None) -> str:
    """ISO, Sensibull label, or Dhan token → human expiry for Telegram/UI."""
    if value is None:
        return ""
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    text = str(value).strip()
    if not text:
        return ""
    try:
        from core.nifty_option_expiry import parse_expiry_label

        return parse_expiry_label(text).strftime("%d %b %Y")
    except ValueError:
        pass
    if re.search(r"\d{1,2}\s+[A-Za-z]{3}", text):
        return text
    return text


def fixture_price_map(fixture: dict[str, Any]) -> dict[tuple[int, str], float]:
    out: dict[tuple[int, str], float] = {}
    for leg in fixture.get("legs") or []:
        if not isinstance(leg, dict):
            continue
        try:
            st = int(leg["strike"])
            opt = str(leg.get("type", "")).upper()
            price = float(leg.get("avg_price", 0))
        except (TypeError, ValueError, KeyError):
            continue
        if opt in ("CE", "PE") and price > 0:
            out[(st, opt)] = round(price, 2)
    return out


def format_position_symbol_display(symbol: str, expiry_display: str) -> str:
    """NIFTY-Jun2026-23400-CE → NIFTY {expiry from fixture} 23400 CE."""
    if symbol.startswith("NIFTY-") and symbol.count("-") >= 3:
        parts = symbol.split("-")
        strike = parts[-2]
        opt = parts[-1]
        exp = expiry_display or parts[1]
        return f"NIFTY {exp} {strike} {opt}"
    m = re.match(r"^([A-Z]+\d{2}[A-Z]{3})(\d+)(CE|PE)$", symbol)
    if m:
        return f"NIFTY {expiry_display} {m.group(2)} {m.group(3)}".strip()
    return symbol


def _safe_avg_price(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, 2) if v > 0 else None


def try_marketfeed_option_premiums(
    broker: Any,
    *,
    target_expiry: date,
    legs: list[tuple[int, str]],
) -> dict[tuple[int, str], float]:
    """Dhan marketfeed/ltp (NSE_FNO securityId) — preferred over Tradehull symbol LTP."""
    if not hasattr(broker, "get_nifty_option_ltps") or not legs:
        return {}
    try:
        return broker.get_nifty_option_ltps(legs, expiry_date=target_expiry)
    except Exception as exc:
        logger.debug("marketfeed option LTP: %s", exc)
        return {}


def try_option_chain_premiums(
    broker: Any,
    *,
    target_expiry: date,
    strikes: list[int],
    max_expiry_index: int = 8,
) -> dict[tuple[int, str], float]:
    """Tradehull option chain → {(strike, CE|PE): LTP} for missing execution prices."""
    if not hasattr(broker, "get_option_chain"):
        return {}
    found: dict[tuple[int, str], float] = {}
    want = set(strikes)
    for idx in range(max_expiry_index):
        try:
            df = broker.get_option_chain(underlying="NIFTY", expiry=idx, num_strikes=50)
        except Exception as exc:
            logger.debug("option chain idx=%s: %s", idx, exc)
            continue
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            continue
        sym_col = next(
            (c for c in ("Symbol", "symbol", "TradingSymbol", "tradingSymbol") if c in df.columns),
            None,
        )
        ltp_col = next(
            (c for c in ("LTP", "ltp", "LastPrice", "last_price", "Close", "close") if c in df.columns),
            None,
        )
        if sym_col is None or ltp_col is None:
            continue
        from core.nifty_option_expiry import trading_symbol_matches_expiry

        sample = df[sym_col].astype(str).head(8)
        if not any(trading_symbol_matches_expiry(s, target_expiry) for s in sample):
            continue
        for _, row in df.iterrows():
            sym = str(row[sym_col])
            if not sym.startswith("NIFTY"):
                continue
            if not trading_symbol_matches_expiry(sym, target_expiry):
                continue
            m = re.search(r"(\d{4,5})(CE|PE)$", sym.replace("-", ""))
            if not m:
                m = re.search(r"-(\d{4,5})-(CE|PE)$", sym)
            if not m:
                continue
            st = int(m.group(1))
            opt = m.group(2)
            if st not in want:
                continue
            px = _safe_avg_price(row[ltp_col])
            if px:
                found[(st, opt)] = px
        if len(found) >= len(want) * 2:
            break
    return found


def resolve_market_quote_broker(broker: Any) -> Any | None:
    """Live Dhan quotes via REST marketfeed — cached, no Tradehull login storm."""
    if broker is None:
        return None
    if hasattr(broker, "get_nifty_option_ltps"):
        return broker
    from core.dhan_rest_quote import cached_rest_quote_client

    return cached_rest_quote_client(broker)


def enrich_nifty_positions(
    positions: list[dict[str, Any]],
    *,
    fixture: dict[str, Any] | None = None,
    chain_broker: Any | None = None,
) -> list[dict[str, Any]]:
    """Fill display fields; fill missing avg_price from fixture then live quotes."""
    if not positions:
        return positions

    from core.market_data_guard import (
        allow_live_option_quotes,
        get_cached_enrich,
        legs_still_missing_after_fixture,
        option_chain_fallback_enabled,
        positions_fingerprint,
        set_cached_enrich,
        should_skip_live_quotes,
    )

    fp = positions_fingerprint(positions)
    cached = get_cached_enrich(fp)
    if cached is not None:
        return cached

    skip_live, skip_reason = should_skip_live_quotes(positions, fixture=fixture)
    if skip_live:
        chain_broker = None
        logger.debug("enrich: skip live quotes — %s", skip_reason)

    expiry_iso = ""
    expiry_label = ""
    if fixture:
        expiry_iso = str(fixture.get("expiry_date") or "")
        expiry_label = str(fixture.get("expiry_label") or "")
    expiry_display = format_expiry_display(expiry_label or expiry_iso)
    if not expiry_display:
        from core.nifty_option_expiry import expiry_date_from_positions

        inferred = expiry_date_from_positions(positions)
        if inferred:
            expiry_display = format_expiry_display(inferred)

    fmap = fixture_price_map(fixture) if fixture else {}
    chain_map: dict[tuple[int, str], float] = {}
    if chain_broker:
        from core.nifty_option_expiry import (
            expiry_date_from_positions,
            fixture_expiry_date,
        )

        try:
            if fixture:
                exp = fixture_expiry_date(fixture)
            else:
                exp = expiry_date_from_positions(positions)
        except (ValueError, TypeError):
            exp = None
        if exp:
            need = legs_still_missing_after_fixture(positions, fixture)
            if need and allow_live_option_quotes(leg_count=len(need)):
                try:
                    chain_map = try_marketfeed_option_premiums(
                        chain_broker, target_expiry=exp, legs=need
                    )
                    if not chain_map and option_chain_fallback_enabled():
                        strikes = sorted({s for s, _ in need})
                        chain_map = try_option_chain_premiums(
                            chain_broker, target_expiry=exp, strikes=strikes
                        )
                except Exception as exc:
                    logger.warning("live option premium fetch failed: %s", exc)

    for pos in positions:
        if expiry_display:
            pos["expiry"] = expiry_display
        key = (int(pos.get("strike", 0)), str(pos.get("opt_type", "")).upper())
        px = _safe_avg_price(pos.get("avg_price"))
        if px is None:
            px = fmap.get(key) or chain_map.get(key)
        if px is not None:
            pos["avg_price"] = px
        pos["display_symbol"] = format_position_symbol_display(
            str(pos.get("symbol", "")),
            expiry_display,
        )
    set_cached_enrich(fp, positions)
    return positions


def enrich_positions_dataframe(
    df: pd.DataFrame,
    fixture: dict[str, Any],
) -> pd.DataFrame:
    """Ensure ShadowBroker rows carry valid avgPrice from Sensibull fixture."""
    if df is None or df.empty:
        return df
    fmap = fixture_price_map(fixture)
    out = df.copy()
    for i, row in out.iterrows():
        try:
            strike = int(float(row.get("drvStrikePrice", 0)))
            opt = str(row.get("drvOptionType", "")).upper()
        except (TypeError, ValueError):
            continue
        key = (strike, opt)
        cur = _safe_avg_price(row.get("avgPrice"))
        if cur is None and key in fmap:
            out.at[i, "avgPrice"] = fmap[key]
            out.at[i, "costPrice"] = fmap[key]
        exp = fixture.get("expiry_date")
        if exp:
            out.at[i, "drvExpiryDate"] = str(exp)[:10]
            out.at[i, "expiryLabel"] = format_expiry_display(str(exp)[:10])
    return out

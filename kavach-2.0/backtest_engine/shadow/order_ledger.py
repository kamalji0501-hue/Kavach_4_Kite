"""Simulated order fills for UAT ShadowBroker."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger("backtest_engine.order_ledger")

_PENDING_SEC = 0.35


def _next_order_id(broker: Any) -> str:
    import re

    nums = [0]
    for o in broker._orders:
        m = re.match(r"SHADOW-(\d+)", str(o.get("order_id", "")))
        if m:
            nums.append(int(m.group(1)))
    return f"SHADOW-{max(nums) + 1:05d}"


def place_virtual_order(broker: Any, symbol: str, **kw) -> str:
    oid = _next_order_id(broker)
    side = str(kw.get("transaction_type") or kw.get("side") or "BUY").upper()
    qty = int(kw.get("qty") or kw.get("quantity") or 0)
    from datetime import datetime
    from zoneinfo import ZoneInfo

    order_time = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")
    entry: dict[str, Any] = {
        "order_id": oid,
        "symbol": symbol,
        "qty": qty,
        "side": side,
        "status": "PENDING",
        "order_time": order_time,
        "timestamp": order_time,
    }
    entry.update(kw)
    # Keep IST clock fields even if caller passed conflicting kwargs.
    entry["order_time"] = order_time
    entry["timestamp"] = order_time
    broker._orders.append(entry)
    _persist(broker)

    order_type = str(kw.get("order_type") or "MARKET").upper()
    if order_type == "MARKET":
        entry["status"] = "TRADED"
        _apply_fill_to_book(broker, symbol, qty, side, order_entry=entry)
        _persist(broker)
        logger.info(
            "Shadow TRADED: %s %s %s qty=%s avg=%.2f",
            side,
            symbol,
            oid,
            qty,
            float(entry.get("avg_price") or 0.0),
        )
        return oid

    def _fill() -> None:
        time.sleep(_PENDING_SEC)
        entry["status"] = "TRADED"
        _apply_fill_to_book(broker, symbol, qty, side, order_entry=entry)
        _persist(broker)
        logger.info(
            "Shadow TRADED: %s %s %s qty=%s avg=%.2f",
            side,
            symbol,
            oid,
            qty,
            float(entry.get("avg_price") or 0.0),
        )

    threading.Thread(target=_fill, daemon=True, name=f"shadow-fill-{oid}").start()
    return oid


def get_virtual_order_status(broker: Any, order_id: str) -> str:
    for o in broker._orders:
        if o["order_id"] == order_id:
            return str(o.get("status", "PENDING"))
    return "REJECTED"


def _resolve_shadow_fill_price(broker: Any, symbol: str) -> float:
    """Option LTP for a shadow fill.

    UAT replay: prefer option_ltp_YYYYMMDD.log at replay market time (so Buy/Sell
    differ as spot moves). Otherwise live REST / broker quote. JWT may live under
    data_runtime — do not require repo-relative data/access_token.json.
    """
    strike, opt = _strike_opt(symbol)
    if not strike or not opt:
        return 0.0
    try:
        from core.batman_mode import access_token_path, workspace_root
        from core.dhan_rest_quote import cached_rest_quote_client
        from core.nifty_option_expiry import fixture_expiry_date
        from core.option_ltp_uat_lookup import (
            lookup_protect_premium,
            replay_market_time_from_cache,
        )
        from core.token_store import TokenStore
        from core.uat_positions import load_positions_fixture
        from dotenv import dotenv_values

        root = getattr(broker, "_root", None) or workspace_root()

        # UAT NIFTY replay → stamp fill from historical option LTP log.
        replay_t = replay_market_time_from_cache(root)
        if replay_t is not None:
            replay_px = lookup_protect_premium(
                symbol=symbol,
                root=root,
                replay_market_time=replay_t,
                day=replay_t,
            )
            if replay_px is not None and replay_px > 0:
                return float(replay_px)

        env = dotenv_values(workspace_root() / "config" / ".env")
        cc = (getattr(broker, "_client_code", None) or env.get("DHAN_CLIENT_CODE") or "").strip()
        token = getattr(broker, "_access_token", None)
        if not token:
            store = TokenStore(path=access_token_path(root))
            token, _ = store.load()
        if cc:
            broker._client_code = cc
        if token:
            broker._access_token = token

        fix = load_positions_fixture(root)
        exp = fixture_expiry_date(fix)
        getter = getattr(broker, "get_nifty_option_ltps", None)
        if callable(getter):
            prices = getter([(strike, opt)], expiry_date=exp)
            if isinstance(prices, dict):
                return float(prices.get((strike, opt), 0.0) or 0.0)

        if not token or not cc:
            return 0.0
        quote = cached_rest_quote_client(broker)
        if not quote:
            return 0.0
        prices = quote.get_nifty_option_ltps([(strike, opt)], expiry_date=exp)
        return float(prices.get((strike, opt), 0.0) or 0.0)
    except Exception as exc:
        logger.debug("ATO fill LTP lookup: %s", exc)
        return 0.0


def _uat_fallback_premium(symbol: str, *, spot: float | None = None) -> float:
    """Reporting-only estimate so UAT SARANSH never shows blank Buy/Sell premiums."""
    strike, opt = _strike_opt(symbol)
    if not strike or not opt:
        return 1.0
    px = float(spot) if spot and spot > 0 else float(strike)
    if str(opt).upper() == "CE":
        intrinsic = max(0.0, px - float(strike))
    else:
        intrinsic = max(0.0, float(strike) - px)
    # Small time-value floor — display only; does not affect order placement.
    return round(max(intrinsic + 5.0, 1.0), 2)


def _apply_fill_to_book(
    broker: Any,
    symbol: str,
    qty: int,
    side: str,
    *,
    order_entry: dict[str, Any] | None = None,
) -> None:
    from backtest_engine.shadow.position_book import apply_virtual_fill

    fill_price = _resolve_shadow_fill_price(broker, symbol)
    if fill_price <= 0:
        spot = None
        getter = getattr(broker, "get_nifty_ltp", None)
        if callable(getter):
            try:
                spot = float(getter())
            except Exception:
                spot = None
        fill_price = _uat_fallback_premium(symbol, spot=spot)
        logger.warning(
            "Shadow fill: no live option LTP for %s — using UAT fallback premium %.2f",
            symbol,
            fill_price,
        )

    exp_date = None
    try:
        from core.nifty_option_expiry import fixture_expiry_date
        from core.uat_positions import load_positions_fixture

        root = getattr(broker, "_root", None)
        exp_date = fixture_expiry_date(load_positions_fixture(root))
    except Exception:
        pass

    broker._positions_df = apply_virtual_fill(
        broker._positions_df,
        symbol=symbol,
        qty=qty,
        side=side,
        avg_price=fill_price,
        expiry_date=exp_date,
    )
    # Only stamp the order being filled — never overwrite prior entry fills.
    if order_entry is not None and fill_price > 0:
        order_entry["avg_price"] = fill_price


def _persist(broker: Any) -> None:
    if not hasattr(broker, "_persist_order_ledger"):
        return
    try:
        broker._persist_order_ledger()
    except Exception as exc:
        logger.warning("Shadow ledger persist failed: %s", exc)


def _strike_opt(symbol: str) -> tuple[int, str]:
    from backtest_engine.shadow.position_book import _parse_strike_from_symbol

    return _parse_strike_from_symbol(symbol)

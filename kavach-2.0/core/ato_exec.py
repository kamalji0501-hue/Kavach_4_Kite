"""ATO protect execution: resting BUY trigger+limit, fill-Rescue, SELL crash Rescue."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("batman.ato_exec")

TICK = 0.05
BUY_LIMIT_OFFSET = 0.10
BUY_RESCUE_RUPEES = 1.00
BUY_RESCUE_BUFFER_PCT = 10.0
SELL_RESCUE_PCT = 0.70
SELL_RESCUE_FLOOR = 0.05


def snap_tick(px: float, *, tick: float = TICK, side: str = "BUY") -> float:
    t = float(tick) if tick > 0 else TICK
    if px <= 0:
        return t
    units = float(px) / t
    if str(side).upper() == "SELL":
        snapped = int(units) * t
    else:
        import math

        snapped = math.ceil(units - 1e-12) * t
    return round(max(t, snapped), 2)


def buy_trigger_limit(ltp: float) -> tuple[float, float]:
    """Parked BUY: trigger = LTP, limit = LTP + 10 paise."""
    trigger = snap_tick(float(ltp), side="BUY")
    limit = snap_tick(trigger + BUY_LIMIT_OFFSET, side="BUY")
    return trigger, limit


def should_fill_rescue(*, trigger: float, ltp: float, remaining_qty: int) -> bool:
    """True when leftover BUY qty is still short and premium ran +1 rupee."""
    try:
        rem = int(remaining_qty)
    except (TypeError, ValueError):
        rem = 0
    if rem <= 0:
        return False
    try:
        return float(ltp) + 1e-9 >= float(trigger) + BUY_RESCUE_RUPEES
    except (TypeError, ValueError):
        return False


def aggressive_buy_limit(ltp: float, *, buffer_pct: float = BUY_RESCUE_BUFFER_PCT) -> float:
    try:
        from core.order_pricing import aggressive_limit_price

        return float(aggressive_limit_price(float(ltp), "BUY", buffer_pct=buffer_pct))
    except Exception:
        return snap_tick(float(ltp) * (1.0 + float(buffer_pct) / 100.0), side="BUY")


def crash_sell_limit(
    *,
    bid: float | None,
    ltp: float,
    pct: float = SELL_RESCUE_PCT,
    floor: float = SELL_RESCUE_FLOOR,
) -> float:
    ref = None
    try:
        if bid is not None and float(bid) > 0:
            ref = float(bid)
    except (TypeError, ValueError):
        ref = None
    if ref is None or ref <= 0:
        try:
            ref = float(ltp)
        except (TypeError, ValueError):
            ref = 0.0
    if ref <= 0:
        return float(floor)
    return snap_tick(max(float(floor), ref * float(pct)), side="SELL")


def remaining_qty(*, requested: int, filled: int) -> int:
    try:
        req = int(requested)
        got = int(filled)
    except (TypeError, ValueError):
        return 0
    return max(0, req - max(0, got))


def place_buy_resting(
    broker: Any,
    *,
    symbol: str,
    qty: int,
    ltp: float,
    product: str = "MARGIN",
) -> dict[str, Any]:
    trigger, limit = buy_trigger_limit(ltp)
    # Kite rejects SL-BUY unless trigger > LTP. ATO already in breach must
    # buy now — use a marketable LIMIT (10% above LTP), not a parked stop.
    px = aggressive_buy_limit(ltp)
    oid = broker.place_order(
        symbol=symbol,
        qty=int(qty),
        price=px,
        order_type="LIMIT",
        transaction_type="BUY",
        trade_type=product,
        confirm=False,
    )
    logger.info(
        "ATO BUY marketable LIMIT trigger=%.2f limit=%.2f aggressive=%.2f qty=%s symbol=%s id=%s",
        trigger,
        limit,
        px,
        qty,
        symbol,
        oid,
    )
    return {
        "order_id": str(oid),
        "trigger": trigger,
        "limit": limit,
        "qty": int(qty),
        "symbol": str(symbol),
        "side": "BUY",
    }


def rescue_complete_buy(
    broker: Any,
    *,
    symbol: str,
    remaining: int,
    ltp: float,
    existing_oid: str | None = None,
    product: str = "MARGIN",
) -> dict[str, Any]:
    """Complete leftover BUY qty. This is not an exit."""
    px = aggressive_buy_limit(ltp)
    oid = str(existing_oid or "").strip()
    if oid:
        modify = getattr(broker, "modify_order", None)
        if callable(modify):
            try:
                modify(oid, order_type="LIMIT", qty=int(remaining), price=px)
                logger.info("ATO BUY fill-Rescue modify id=%s limit=%.2f qty=%s", oid, px, remaining)
                return {"order_id": oid, "crash_limit": px, "via": "modify", "side": "BUY"}
            except Exception as exc:
                logger.warning("ATO BUY fill-Rescue modify failed: %s", exc)
                err = str(exc).lower()
                if "being processed" in err or "cannot be modified" in err:
                    return {"order_id": oid, "via": "modify_pending", "side": "BUY"}
        cancel = getattr(broker, "cancel_order", None)
        if callable(cancel):
            try:
                cancel(oid)
            except Exception:
                pass
    place = getattr(broker, "place_aggressive_limit", None)
    if callable(place):
        new_id = place(symbol, int(remaining), "BUY", trade_type=product)
    else:
        new_id = broker.place_order(
            symbol=symbol,
            qty=int(remaining),
            price=px,
            order_type="LIMIT",
            transaction_type="BUY",
            trade_type=product,
            confirm=False,
        )
    logger.info("ATO BUY fill-Rescue place id=%s limit=%.2f qty=%s", new_id, px, remaining)
    return {"order_id": str(new_id), "crash_limit": px, "via": "place", "side": "BUY"}


def place_sell_sl_limit(
    broker: Any,
    *,
    symbol: str,
    qty: int,
    ltp: float,
    product: str = "MARGIN",
    trigger_offset: float = 1.0,
) -> dict[str, Any]:
    """Exit SELL: marketable LIMIT (Kite SL-SELL waits under LTP and does not fill)."""
    trigger = snap_tick(max(TICK, float(ltp) - float(trigger_offset)), side="SELL")
    limit = snap_tick(max(TICK, trigger - BUY_LIMIT_OFFSET), side="SELL")
    try:
        from core.order_pricing import aggressive_limit_price

        px = float(aggressive_limit_price(float(ltp), "SELL"))
    except Exception:
        px = crash_sell_limit(bid=None, ltp=ltp)
    oid = broker.place_order(
        symbol=symbol,
        qty=int(qty),
        price=px,
        order_type="LIMIT",
        transaction_type="SELL",
        trade_type=product,
        confirm=False,
    )
    logger.info(
        "ATO SELL marketable LIMIT trigger=%.2f parked=%.2f aggressive=%.2f qty=%s symbol=%s id=%s",
        trigger,
        limit,
        px,
        qty,
        symbol,
        oid,
    )
    return {
        "order_id": str(oid),
        "trigger": trigger,
        "limit": limit,
        "qty": int(qty),
        "symbol": str(symbol),
        "side": "SELL",
    }


def rescue_flatten_sell(
    broker: Any,
    *,
    symbol: str,
    remaining: int,
    ltp: float,
    bid: float | None = None,
    existing_oid: str | None = None,
    product: str = "MARGIN",
) -> dict[str, Any]:
    px = crash_sell_limit(bid=bid, ltp=ltp)
    oid = str(existing_oid or "").strip()
    if oid:
        modify = getattr(broker, "modify_order", None)
        if callable(modify):
            try:
                modify(oid, order_type="LIMIT", qty=int(remaining), price=px)
                logger.info("ATO SELL exit-Rescue modify id=%s crash=%.2f qty=%s", oid, px, remaining)
                return {"order_id": oid, "crash_limit": px, "via": "modify", "side": "SELL"}
            except Exception as exc:
                logger.warning("ATO SELL exit-Rescue modify failed: %s", exc)
                err = str(exc).lower()
                try:
                    from core.desk_alerts import emit_desk_alert, option_side

                    side = option_side(symbol)
                    who = f"{side} " if side else ""
                    if "429" in err or "too many" in err:
                        line = f"{who}sell cannot be changed — Kite is blocking more updates (too many requests)."
                    else:
                        line = f"{who}sell cannot be changed — Kite is still working on that order."
                    emit_desk_alert(
                        severity="red",
                        category="ATO exit",
                        alert=line.strip(),
                        log=f"ATO SELL exit-Rescue modify failed: {exc}",
                        side=side,
                    )
                except Exception:
                    pass
                if "being processed" in err or "cannot be modified" in err:
                    return {"order_id": oid, "via": "modify_pending", "side": "SELL"}
        cancel = getattr(broker, "cancel_order", None)
        if callable(cancel):
            try:
                cancel(oid)
            except Exception as cancel_exc:
                try:
                    from core.desk_alerts import emit_desk_alert, option_side

                    side = option_side(symbol)
                    who = f"{side} " if side else ""
                    emit_desk_alert(
                        severity="red",
                        category="ATO exit",
                        alert=f"{who}sell cannot be cancelled either.".strip(),
                        log=f"ATO SELL exit-Rescue cancel failed: {cancel_exc}",
                        side=side,
                    )
                except Exception:
                    pass
    place = getattr(broker, "place_aggressive_limit", None)
    if callable(place):
        new_id = place(symbol, int(remaining), "SELL", trade_type=product)
    else:
        new_id = broker.place_order(
            symbol=symbol,
            qty=int(remaining),
            price=px,
            order_type="LIMIT",
            transaction_type="SELL",
            trade_type=product,
            confirm=False,
        )
    logger.info("ATO SELL exit-Rescue place id=%s crash=%.2f qty=%s", new_id, px, remaining)
    return {"order_id": str(new_id), "crash_limit": px, "via": "place", "side": "SELL"}

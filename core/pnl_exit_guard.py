"""Home Safe Exit (floor) + Take Profit (ceiling) vs day PnL cache.

Armed checks use cached day PnL (refreshed by ATO get_positions).
On fire: pause ATO, sequenced flatten (shorts then longs), both toggles OFF, clear levels.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger("batman.pnl_exit_guard")

_FIRE_LOCK = threading.Lock()

KEY_SAFE_ON = "pnl_exit.safe_on"
KEY_SAFE_LEVEL = "pnl_exit.safe_level_rs"
KEY_TP_ON = "pnl_exit.tp_on"
KEY_TP_LEVEL = "pnl_exit.tp_level_rs"
KEY_FIRING = "pnl_exit.firing"
KEY_LAST_REASON = "pnl_exit.last_reason"
KEY_LAST_PNL = "pnl_exit.last_pnl"
KEY_LAST_AT = "pnl_exit.last_at"


def snapshot_pnl_exit(state: Any) -> dict[str, Any]:
    if state is None:
        return {
            "safe_on": False,
            "safe_level_rs": None,
            "tp_on": False,
            "tp_level_rs": None,
            "firing": False,
            "last_reason": None,
            "last_pnl": None,
            "last_at": None,
        }
    return {
        "safe_on": bool(state.get(KEY_SAFE_ON, False)),
        "safe_level_rs": state.get(KEY_SAFE_LEVEL),
        "tp_on": bool(state.get(KEY_TP_ON, False)),
        "tp_level_rs": state.get(KEY_TP_LEVEL),
        "firing": bool(state.get(KEY_FIRING, False)),
        "last_reason": state.get(KEY_LAST_REASON),
        "last_pnl": state.get(KEY_LAST_PNL),
        "last_at": state.get(KEY_LAST_AT),
    }


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def current_day_pnl() -> float | None:
    try:
        from core.day_pnl_cache import cached_day_pnl

        return cached_day_pnl()
    except Exception:
        return None


def validate_safe_level(level: float, day_pnl: float | None) -> str | None:
    if day_pnl is None:
        return "Day PnL unknown — wait for a positions refresh, then retry."
    if not (level < float(day_pnl)):
        return f"Safe Exit level must be less than current day PnL ({day_pnl:.2f})."
    return None


def validate_tp_level(level: float, day_pnl: float | None) -> str | None:
    if day_pnl is None:
        return "Day PnL unknown — wait for a positions refresh, then retry."
    if not (level > float(day_pnl)):
        return f"Take Profit level must be greater than current day PnL ({day_pnl:.2f})."
    return None


def clear_both(state: Any, *, save: bool = True) -> None:
    if state is None:
        return
    state.set(KEY_SAFE_ON, False, save=False)
    state.set(KEY_TP_ON, False, save=False)
    state.set(KEY_SAFE_LEVEL, None, save=False)
    state.set(KEY_TP_LEVEL, None, save=False)
    state.set(KEY_FIRING, False, save=save)


def set_safe_exit(state: Any, *, on: bool, level: float | None) -> dict[str, Any]:
    day = current_day_pnl()
    if on:
        if level is None:
            return {"ok": False, "error": "Enter a Safe Exit ₹ level before turning ON."}
        err = validate_safe_level(float(level), day)
        if err:
            return {"ok": False, "error": err}
        state.set(KEY_SAFE_LEVEL, float(level), save=False)
        state.set(KEY_SAFE_ON, True, save=True)
    else:
        state.set(KEY_SAFE_ON, False, save=True)
    out = {"ok": True, "pnl_exit": snapshot_pnl_exit(state), "day_pnl": day}
    out["text"] = (
        f"Safe Exit ON @ ₹{float(level):.2f}" if on else "Safe Exit OFF"
    )
    return out


def set_take_profit(state: Any, *, on: bool, level: float | None) -> dict[str, Any]:
    day = current_day_pnl()
    if on:
        if level is None:
            return {"ok": False, "error": "Enter a Take Profit ₹ level before turning ON."}
        err = validate_tp_level(float(level), day)
        if err:
            return {"ok": False, "error": err}
        state.set(KEY_TP_LEVEL, float(level), save=False)
        state.set(KEY_TP_ON, True, save=True)
    else:
        state.set(KEY_TP_ON, False, save=True)
    out = {"ok": True, "pnl_exit": snapshot_pnl_exit(state), "day_pnl": day}
    out["text"] = (
        f"Take Profit ON @ ₹{float(level):.2f}" if on else "Take Profit OFF"
    )
    return out


def _leg_rows(broker: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        df = broker.get_positions()
    except Exception as exc:
        logger.error("pnl_exit get_positions failed: %s", exc)
        return rows
    if df is None or getattr(df, "empty", True):
        return rows
    for _, row in df.iterrows():
        symbol = str(row.get("tradingSymbol") or row.get("tradingsymbol") or "")
        try:
            net_qty = int(row.get("netQty", 0) or 0)
        except (TypeError, ValueError):
            net_qty = 0
        if not symbol or net_qty == 0:
            continue
        product = str(row.get("product") or "NRML")
        exchange = str(row.get("exchange") or "NFO")
        rows.append(
            {
                "symbol": symbol,
                "qty": abs(net_qty),
                "net_qty": net_qty,
                "product": product,
                "exchange": exchange,
            }
        )
    # Shorts (net < 0) first, then longs (net > 0)
    shorts = [r for r in rows if r["net_qty"] < 0]
    longs = [r for r in rows if r["net_qty"] > 0]
    return shorts + longs


def _trade_type_for_product(product: str) -> str:
    p = (product or "").upper()
    if p in {"MIS", "INTRADAY"}:
        return "INTRADAY"
    return "MARGIN"


def _cancel_open_orders(broker: Any, symbol: str) -> None:
    """Drop working orders for one symbol so a retry cannot double-sell."""
    try:
        df = broker.get_orderbook()
    except Exception as exc:
        logger.warning("pnl_exit orderbook for cancel: %s", exc)
        return
    if df is None or getattr(df, "empty", True):
        return
    want = str(symbol)
    for _, row in df.iterrows():
        sym = str(row.get("tradingsymbol") or row.get("tradingSymbol") or "")
        if sym != want:
            continue
        st = str(row.get("status") or "").upper()
        if st in {"COMPLETE", "REJECTED", "CANCELLED", "CANCELED"}:
            continue
        oid = str(row.get("order_id") or "")
        if not oid or not hasattr(broker, "cancel_order"):
            continue
        try:
            broker.cancel_order(oid)
            logger.info("pnl_exit cancelled leftover order %s for %s (%s)", oid, want, st)
        except Exception as exc:
            logger.warning("pnl_exit cancel %s: %s", oid, exc)


def _close_one(broker: Any, leg: dict[str, Any]) -> str | None:
    net = int(leg["net_qty"])
    side = "BUY" if net < 0 else "SELL"
    trade_type = _trade_type_for_product(str(leg.get("product") or ""))
    symbol = str(leg["symbol"])
    qty = int(leg["qty"])
    exchange = str(leg.get("exchange") or "NFO")
    try:
        # Options MARKET is converted by Kite to LIMIT-at-LTP and can sit unfilled
        # on cheap/expiry contracts (seen 1 Sep 2026 on NIFTY2690125050CE).
        if hasattr(broker, "place_aggressive_limit"):
            return str(
                broker.place_aggressive_limit(
                    symbol,
                    qty,
                    side,
                    buffer_pct=20.0,
                    tick_size=0.05,
                    chase_timeout_sec=25.0,
                    chase_interval_sec=3.0,
                    trade_type=trade_type,
                    exchange=exchange,
                )
            )
        return str(
            broker.close_position(
                symbol=symbol,
                qty=qty,
                side=side,
                trade_type=trade_type,
                exchange=exchange,
            )
        )
    except Exception as exc:
        logger.error("pnl_exit close failed %s: %s", symbol, exc)
        return None


def _clear_paper_book() -> None:
    try:
        from core.paper_position_book import open_legs, record_fill

        for leg in list(open_legs() or []):
            sym = str(leg.get("trading_symbol") or "")
            qty = int(leg.get("qty") or 0)
            if not sym or qty <= 0:
                continue
            # SELL reduces/closes paper longs
            try:
                record_fill(
                    symbol=sym,
                    qty=qty,
                    side="SELL",
                    avg_price=leg.get("avg_price"),
                    security_id=leg.get("security_id"),
                    source="pnl_exit_flatten",
                    order_id="pnl-exit",
                )
            except Exception as exc:
                logger.warning("paper book clear %s: %s", sym, exc)
    except Exception as exc:
        logger.debug("paper book clear skip: %s", exc)


def sequenced_flatten(broker: Any) -> dict[str, Any]:
    order_ids: list[str] = []
    try:
        if hasattr(broker, "cancel_all_intraday"):
            broker.cancel_all_intraday()
    except Exception as exc:
        logger.warning("pnl_exit cancel_all: %s", exc)

    legs = _leg_rows(broker)
    for leg in legs:
        oid = _close_one(broker, leg)
        if oid:
            order_ids.append(oid)
        time.sleep(0.35)

    # Retry only still-open qty; cancel working orders first so we never double-sell.
    time.sleep(1.0)
    left = _leg_rows(broker)
    for leg in left:
        _cancel_open_orders(broker, str(leg["symbol"]))
        time.sleep(0.25)
    left = _leg_rows(broker)
    for leg in left:
        oid = _close_one(broker, leg)
        if oid:
            order_ids.append(oid)
        time.sleep(0.35)

    _clear_paper_book()
    still = _leg_rows(broker)
    if still:
        logger.error(
            "pnl_exit leftover after flatten: %s",
            [(r.get("symbol"), r.get("net_qty")) for r in still],
        )
    return {
        "orders_placed": len(order_ids),
        "order_ids": order_ids,
        "legs_seen": len(legs),
        "legs_left": len(still),
        "left_symbols": [r.get("symbol") for r in still],
    }


def _pause_ato(state: Any) -> None:
    try:
        from core.ato_side_state import pause_all_ato

        pause_all_ato(state, reason="pnl_exit_fired", save=False)
    except Exception:
        try:
            state.set("algo.paused", True, save=False)
            state.set("algo.pause_reason", "pnl_exit_fired", save=False)
        except Exception:
            pass
    if state is None:
        return
    try:
        for prefix in ("ce", "pe"):
            state.set(f"ato.{prefix}_triggered", False, save=False)
            state.set(f"ato.{prefix}_ato_active", False, save=False)
        state.save()
    except Exception as exc:
        logger.warning("pnl_exit clear ato flags: %s", exc)


def _notify(events: Any, reason: str, pnl: float, level: float | None, result: dict[str, Any]) -> None:
    payload = {
        "reason": reason,
        "pnl": pnl,
        "level": level,
        "source": "pnl_exit_guard",
        **result,
    }
    try:
        from core.event_bus import Event

        if events is not None:
            events.publish(Event.ALL_POSITIONS_CLOSED, payload)
            events.publish(Event.EMERGENCY_EXIT, {"reason": reason, "source": "pnl_exit_guard"})
    except Exception as exc:
        logger.warning("pnl_exit event publish: %s", exc)
    try:
        from bat_telegram.incident_publisher import publish_incident

        if reason == "manual_exit":
            detail = (
                f"Manual flatten. Day PnL ₹{pnl:.2f}. "
                f"Flatten orders={result.get('orders_placed')}."
            )
        elif level is None:
            detail = f"Day PnL ₹{pnl:.2f}. Flatten orders={result.get('orders_placed')}."
        else:
            detail = (
                f"Day PnL ₹{pnl:.2f} hit level ₹{level:.2f}. "
                f"Flatten orders={result.get('orders_placed')}."
            )
        publish_incident(
            severity="critical",
            category="pnl_exit",
            title=reason.replace("_", " ").upper(),
            detail=detail,
            next_action="Both Safe Exit and Take Profit cleared. Re-arm manually if needed.",
        )
    except Exception as exc:
        logger.debug("pnl_exit incident: %s", exc)


def flatten_now(
    *,
    broker: Any,
    state: Any,
    events: Any = None,
    reason: str = "manual_exit",
    pnl: float | None = None,
    level: float | None = None,
) -> dict[str, Any]:
    """Pause ATO and sequenced-flatten now. No PnL level required."""
    if broker is None:
        return {"ok": False, "error": "Broker not available."}
    if not _FIRE_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "Exit already in progress."}
    try:
        if state is not None and bool(state.get(KEY_FIRING, False)):
            return {"ok": False, "error": "Exit already in progress."}

        day = current_day_pnl()
        if pnl is not None:
            pnl_v = float(pnl)
        elif day is not None:
            pnl_v = float(day)
        else:
            pnl_v = 0.0
        level_v = float(level) if level is not None else None

        if state is not None:
            state.set(KEY_FIRING, True, save=False)
            state.set(KEY_SAFE_ON, False, save=False)
            state.set(KEY_TP_ON, False, save=False)
            state.set(KEY_SAFE_LEVEL, None, save=False)
            state.set(KEY_TP_LEVEL, None, save=False)
            state.set(KEY_LAST_REASON, reason, save=False)
            state.set(KEY_LAST_PNL, pnl_v, save=False)
            from core import utils

            state.set(KEY_LAST_AT, utils.now_ist().isoformat(), save=True)

        if level_v is None:
            logger.critical("PNL EXIT FIRE reason=%s pnl=%.2f level=none", reason, pnl_v)
        else:
            logger.critical(
                "PNL EXIT FIRE reason=%s pnl=%.2f level=%.2f", reason, pnl_v, level_v
            )
        try:
            from core.desk_alerts import emit_desk_alert

            if reason == "take_profit":
                emit_desk_alert(
                    severity="green",
                    category="PnL exit",
                    alert="Target hit — book is flattening.",
                    log=f"PNL EXIT FIRE reason={reason} pnl={pnl_v:.2f} level={level_v}",
                )
            elif reason == "safe_exit":
                emit_desk_alert(
                    severity="red",
                    category="PnL exit",
                    alert="Stop-loss hit — book is flattening.",
                    log=f"PNL EXIT FIRE reason={reason} pnl={pnl_v:.2f} level={level_v}",
                )
            else:
                emit_desk_alert(
                    severity="red",
                    category="PnL exit",
                    alert="Manual exit — book is flattening.",
                    log=f"PNL EXIT FIRE reason={reason} pnl={pnl_v:.2f}",
                )
        except Exception:
            pass
        _pause_ato(state)
        result = sequenced_flatten(broker)
        if state is not None:
            state.set(KEY_FIRING, False, save=True)
        _notify(events, reason, pnl_v, level_v, result)
        left = int(result.get("legs_left") or 0)
        placed = int(result.get("orders_placed") or 0)
        if left:
            leftover = ", ".join(str(s) for s in (result.get("left_symbols") or []) if s)
            text = f"Exit finished with {left} leftover leg(s)"
            if leftover:
                text += f": {leftover}"
            text += "."
        else:
            text = f"Exit complete. Orders placed: {placed}."
        return {
            "ok": True,
            "reason": reason,
            "pnl": pnl_v,
            "level": level_v,
            "text": text,
            **result,
        }
    except Exception as exc:
        logger.exception("pnl_exit fire failed: %s", exc)
        try:
            if state is not None:
                state.set(KEY_FIRING, False, save=True)
        except Exception:
            pass
        return {"ok": False, "error": str(exc), "reason": reason}
    finally:
        _FIRE_LOCK.release()


def check_and_maybe_fire(*, broker: Any, state: Any, events: Any = None) -> dict[str, Any] | None:
    """Compare armed levels to day PnL; fire once if crossed."""
    if state is None or broker is None:
        return None
    if bool(state.get(KEY_FIRING, False)):
        return None

    safe_on = bool(state.get(KEY_SAFE_ON, False))
    tp_on = bool(state.get(KEY_TP_ON, False))
    if not safe_on and not tp_on:
        return None

    pnl = current_day_pnl()
    if pnl is None:
        return None

    reason = None
    level = None
    if safe_on:
        lvl = _f(state.get(KEY_SAFE_LEVEL))
        if lvl is not None and float(pnl) <= float(lvl):
            reason = "safe_exit"
            level = float(lvl)
    if reason is None and tp_on:
        lvl = _f(state.get(KEY_TP_LEVEL))
        if lvl is not None and float(pnl) >= float(lvl):
            reason = "take_profit"
            level = float(lvl)
    if reason is None or level is None:
        return None

    out = flatten_now(
        broker=broker,
        state=state,
        events=events,
        reason=reason,
        pnl=float(pnl),
        level=float(level),
    )
    if not out.get("ok") and "already in progress" in str(out.get("error") or "").lower():
        return None
    return out

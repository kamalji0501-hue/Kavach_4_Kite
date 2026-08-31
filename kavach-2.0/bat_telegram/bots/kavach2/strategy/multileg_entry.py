"""Sequential Dhan entry for Batman 2.0 eight-leg plan (KAVACH 2.0)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Callable

from bat_telegram.bots.kavach2.strategy.batman2_legs import (
    LegPlan,
    PLACE_SEQUENCE,
    build_batman2_plan,
    plan_to_preview_rows,
)

logger = logging.getLogger("batman.kavach2.multileg")

NotifyFn = Callable[[str], None]


# Sell legs must wait until that side's planned BUY legs (qty>0) are fully filled.
_SIDE_BUY_KEYS_BEFORE_SELL: dict[str, tuple[str, ...]] = {
    "ce_sell": ("ce_buy", "ce_margin_hedge", "ce_dyn_hedge"),
    "pe_sell": ("pe_buy", "pe_margin_hedge", "pe_dyn_hedge"),
}




def resolve_expiry(expiry: date | str | None = None) -> date:
    """Nearest weekly expiry from instrument master, or explicit override."""
    if expiry is not None:
        if isinstance(expiry, date):
            return expiry
        from core.nifty_option_expiry import parse_expiry_label

        return parse_expiry_label(str(expiry))

    try:
        from backtest_engine.resolver.instrument_master import list_nifty_option_expiries

        expiries = list_nifty_option_expiries(on_or_after=date.today())
        if expiries:
            return expiries[0]
    except Exception as exc:
        logger.warning("list_nifty_option_expiries failed: %s — falling back", exc)

    from core.utils import current_week_expiry

    return current_week_expiry()


def resolve_symbol(strike: int, option_type: str, expiry: date) -> tuple[str, int]:
    """Return (trading_symbol, lot_size) via Kite NFO dump, then Dhan master fallback."""
    try:
        from core.zerodha_instruments import resolve_nifty_option_kite

        kite = resolve_nifty_option_kite(int(strike), str(option_type).upper(), expiry)
        if kite is not None:
            return kite.tradingsymbol, int(kite.lot_size)
    except Exception as exc:
        logger.warning("Kite symbol resolve failed: %s", exc)
    from backtest_engine.resolver.instrument_master import resolve_nifty_option

    inst = resolve_nifty_option(
        strike=int(strike),
        option_type=str(option_type).upper(),
        expiry_date=expiry,
    )
    return inst.trading_symbol, int(inst.lot_size)


def build_preview(
    center_level: float,
    *,
    base_lots: int,
    lot_size: int,
    params: dict[str, Any] | None = None,
) -> tuple[list[LegPlan], list[dict[str, Any]]]:
    p = params or {}
    legs = build_batman2_plan(
        center_level,
        base_lots=base_lots,
        lot_size=lot_size,
        buy_offset=int(p.get("buy_offset", 250)),
        sell_offset=int(p.get("sell_offset", 300)),
        dyn_from_sell=int(p.get("dyn_from_sell", 200)),
        margin_offset=int(p.get("margin_offset", 1000)),
        dyn_hedge_pct=float(p.get("dyn_hedge_pct", 0.30)),
        strike_step=int(p.get("strike_step", 50)),
    )
    return legs, plan_to_preview_rows(legs)


def deploy_multileg(
    broker: Any,
    *,
    center_level: float,
    base_lots: int,
    lot_size: int,
    expiry: date | str | None = None,
    params: dict[str, Any] | None = None,
    notify: NotifyFn | None = None,
) -> dict[str, Any]:
    """Place all 8 legs sequentially (buys before sell per side). On failure: stop, status=partial.

    Returns a result dict for Telegram (does not write GO books or batman_*.json).
    Operator should Register Batman afterwards to arm Phase 1 / ATO.
    """
    p = params or {}
    exp = resolve_expiry(expiry)
    legs_plan, _ = build_preview(
        center_level, base_lots=base_lots, lot_size=lot_size, params=p
    )

    chase_timeout = float(p.get("chase_timeout_sec", 45.0))
    chase_interval = float(p.get("chase_interval_sec", 5.0))
    buffer_pct = float(p.get("aggressive_buffer_pct", 10.0))
    product = str(p.get("product_type", "MARGIN"))

    filled: list[dict[str, Any]] = []
    pending_keys = [leg.key for leg in legs_plan if leg.qty > 0]
    status = "entry_only_done"
    error: str | None = None

    def _notify(msg: str) -> None:
        if notify:
            try:
                notify(msg)
            except Exception:
                pass

    def _buys_filled_for_sell(sell_key: str) -> list[str]:
        """Return planned buy keys for this sell that are not yet fully filled."""
        required = _SIDE_BUY_KEYS_BEFORE_SELL.get(sell_key) or ()
        planned = {p.key: p for p in legs_plan}
        need = [k for k in required if k in planned and int(planned[k].qty) > 0]
        filled_ok = {r["key"] for r in filled if r.get("status") == "filled"}
        return [k for k in need if k not in filled_ok]

    for leg in legs_plan:
        if leg.qty <= 0:
            continue

        # Hard gate: never open a SELL until that side's BUY legs are fully filled.
        if leg.key in _SIDE_BUY_KEYS_BEFORE_SELL:
            missing = _buys_filled_for_sell(leg.key)
            if missing:
                error = (
                    f"Cannot place {leg.key}: buy legs not fully filled yet "
                    f"({', '.join(missing)})"
                )
                logger.error(error)
                filled.append(
                    {
                        "key": leg.key,
                        "side": leg.side,
                        "option_type": leg.option_type,
                        "strike": leg.strike,
                        "qty": leg.qty,
                        "role": leg.role,
                        "symbol": None,
                        "order_id": None,
                        "status": "skipped",
                        "error": error,
                    }
                )
                pending_keys = [k for k in pending_keys if k != leg.key]
                for rest in legs_plan:
                    if rest.key in pending_keys and rest.qty > 0:
                        filled.append(
                            {
                                "key": rest.key,
                                "side": rest.side,
                                "option_type": rest.option_type,
                                "strike": rest.strike,
                                "qty": rest.qty,
                                "role": rest.role,
                                "symbol": None,
                                "order_id": None,
                                "status": "skipped",
                            }
                        )
                status = "partial"
                break

        try:
            symbol, _ = resolve_symbol(leg.strike, leg.option_type, exp)
        except Exception as exc:
            error = f"Symbol resolve failed for {leg.key}: {exc}"
            logger.error(error)
            status = "partial"
            break

        try:
            _notify(f"Batman 2.0 placing {leg.side} {symbol} qty={leg.qty}…")
            if hasattr(broker, "place_aggressive_limit"):
                order_id = broker.place_aggressive_limit(
                    symbol=symbol,
                    qty=leg.qty,
                    side=leg.side,
                    buffer_pct=buffer_pct,
                    chase_timeout_sec=chase_timeout,
                    chase_interval_sec=chase_interval,
                    trade_type=product,
                )
            else:
                order_id = broker.place_market_order(
                    symbol=symbol,
                    qty=leg.qty,
                    side=leg.side,
                    trade_type=product,
                )
            row = {
                "key": leg.key,
                "side": leg.side,
                "option_type": leg.option_type,
                "strike": leg.strike,
                "qty": leg.qty,
                "role": leg.role,
                "symbol": symbol,
                "order_id": str(order_id),
                "status": "filled",
            }
            filled.append(row)
            pending_keys = [k for k in pending_keys if k != leg.key]
            logger.info("Batman 2.0 OK %s → %s", leg.key, order_id)
        except Exception as exc:
            error = f"{leg.key} failed: {exc}"
            logger.error("Batman 2.0 %s", error)
            filled.append(
                {
                    "key": leg.key,
                    "side": leg.side,
                    "option_type": leg.option_type,
                    "strike": leg.strike,
                    "qty": leg.qty,
                    "role": leg.role,
                    "symbol": symbol,
                    "order_id": None,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            pending_keys = [k for k in pending_keys if k != leg.key]
            for rest in legs_plan:
                if rest.key in pending_keys and rest.qty > 0:
                    filled.append(
                        {
                            "key": rest.key,
                            "side": rest.side,
                            "option_type": rest.option_type,
                            "strike": rest.strike,
                            "qty": rest.qty,
                            "role": rest.role,
                            "symbol": None,
                            "order_id": None,
                            "status": "skipped",
                        }
                    )
            status = "partial"
            break

    from core.nifty_option_expiry import expiry_label_from_date

    result: dict[str, Any] = {
        "status": status,
        "center_level": float(center_level),
        "expiry": expiry_label_from_date(exp),
        "base_lots": base_lots,
        "lot_size": lot_size,
        "legs": filled,
    }
    if error:
        result["error"] = error

    filled_n = sum(1 for x in filled if x.get("status") == "filled")
    planned_n = len([l for l in legs_plan if l.qty > 0])
    _notify(
        f"Batman 2.0 done: status={status} filled={filled_n}/{planned_n}"
        + (f" error={error}" if error else "")
        + " — tap Register Batman to arm Phase 1."
    )
    return result


def format_preview_text(
    center_level: float,
    legs_preview: list[dict[str, Any]],
    *,
    expiry_label: str,
    base_lots: int,
    all_legs: list[LegPlan] | None = None,
) -> str:
    shown = {row["key"] for row in legs_preview}
    skipped = [
        leg for leg in (all_legs or [])
        if leg.qty <= 0 and leg.key not in shown
    ]
    n_place = len(legs_preview)
    n_plan = len(all_legs) if all_legs else n_place
    lines = [
        f"Batman 2.0 preview — center {center_level:.0f}",
        f"Expiry: {expiry_label} | lots: {base_lots} | {n_place} legs to place"
        + (f" (of {n_plan} in plan)" if n_plan != n_place else ""),
        "─" * 36,
    ]
    for row in legs_preview:
        lines.append(
            f"{row['key']:<16} {row['side']:<4} {row['type']} {row['strike']} × {row['qty']}"
        )
    if skipped:
        lines.append("─" * 36)
        lines.append("Skipped (30% dyn hedge < 1 lot at this size):")
        for leg in skipped:
            lines.append(
                f"{leg.key:<16} {leg.side:<4} {leg.option_type} {leg.strike} × 0"
            )
    lines.append("─" * 36)
    lines.append("Confirm to place all legs above (entry only).")
    lines.append("Then Register Batman to arm Phase 1 / ATO.")
    return "\n".join(lines)


def format_result_text(result: dict[str, Any]) -> str:
    """Human-readable deploy result for Telegram."""
    lines = [
        f"Batman 2.0 deploy — {result.get('status')}",
        f"Center: {result.get('center_level')} | Expiry: {result.get('expiry')}",
        f"Lots: {result.get('base_lots')}",
        "─" * 36,
    ]
    for leg in result.get("legs") or []:
        lines.append(
            f"• {leg.get('key')} {leg.get('side')} "
            f"{leg.get('symbol') or leg.get('strike')} "
            f"×{leg.get('qty')} [{leg.get('status')}]"
        )
    if result.get("error"):
        lines.append(f"Error: {result['error']}")
    lines.append("─" * 36)
    lines.append("Tap Register Batman to arm Phase 1 / ATO.")
    return "\n".join(lines)


__all__ = [
    "PLACE_SEQUENCE",
    "build_preview",
    "deploy_multileg",
    "format_preview_text",
    "format_result_text",
    "resolve_expiry",
    "resolve_symbol",
]

"""Sequential Dhan entry for Batman 2.0 eight-leg plan."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Callable

from GO.book import make_multileg_book, save_book
from GO.strategy.batman2_legs import LegPlan, PLACE_SEQUENCE, build_batman2_plan, plan_to_preview_rows

logger = logging.getLogger("batman.go.multileg")

NotifyFn = Callable[[str], None]


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
    """Return (trading_symbol, lot_size) via instrument master."""
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
    root=None,
    notify: NotifyFn | None = None,
) -> dict[str, Any]:
    """Place all 8 legs sequentially. On failure: stop, book status=partial."""
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

    for leg in legs_plan:
        if leg.qty <= 0:
            continue
        try:
            symbol, _ = resolve_symbol(leg.strike, leg.option_type, exp)
        except Exception as exc:
            error = f"Symbol resolve failed for {leg.key}: {exc}"
            logger.error(error)
            status = "partial"
            break

        try:
            _notify(f"GO multi-leg placing {leg.side} {symbol} qty={leg.qty}…")
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
            logger.info("GO multi-leg OK %s → %s", leg.key, order_id)
        except Exception as exc:
            error = f"{leg.key} failed: {exc}"
            logger.error("GO multi-leg %s", error)
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
            # Remaining legs stay pending
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

    book = make_multileg_book(
        center_level=float(center_level),
        expiry=expiry_label_from_date(exp),
        base_lots=base_lots,
        lot_size=lot_size,
        legs=filled,
        status=status,
    )
    if error:
        book["error"] = error
    path = save_book(book, root=root)
    book["_path"] = str(path)

    filled_n = sum(1 for x in filled if x.get("status") == "filled")
    _notify(
        f"GO multi-leg done: status={status} filled={filled_n}/{len([l for l in legs_plan if l.qty > 0])}"
        + (f" error={error}" if error else "")
    )
    return book


def format_preview_text(
    center_level: float,
    legs_preview: list[dict[str, Any]],
    *,
    expiry_label: str,
    base_lots: int,
) -> str:
    lines = [
        f"Batman 2.0 preview — center {center_level:.0f}",
        f"Expiry: {expiry_label} | lots: {base_lots}",
        "─" * 36,
    ]
    for row in legs_preview:
        lines.append(
            f"{row['key']:<16} {row['side']:<4} {row['type']} {row['strike']} × {row['qty']}"
        )
    lines.append("─" * 36)
    lines.append("Confirm to place all legs (entry only — no GO exit).")
    return "\n".join(lines)


# Re-export for callers that want sequence constant
__all__ = [
    "PLACE_SEQUENCE",
    "build_preview",
    "deploy_multileg",
    "format_preview_text",
    "resolve_expiry",
    "resolve_symbol",
]

"""Single-leg Buy CE/PE with fixed SL/Target, trailing, and manual Exit."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from GO.book import load_active_book, make_single_book, save_book
from GO.strategy.batman2_legs import snap_strike
from GO.strategy.multileg_entry import resolve_expiry, resolve_symbol

logger = logging.getLogger("batman.go.single_leg")

NotifyFn = Callable[[str], None]


@dataclass
class RiskLevels:
    entry: float
    sl: float
    target: float
    trail_active: bool = False
    trail_sl: float = 0.0
    trail_target: float = 0.0
    peak: float = 0.0


def initial_risk(entry_premium: float, sl_rupees: float, target_rupees: float) -> RiskLevels:
    entry = float(entry_premium)
    sl = entry - abs(float(sl_rupees))
    target = entry + abs(float(target_rupees))
    if sl < 0:
        sl = 0.05
    return RiskLevels(
        entry=entry,
        sl=sl,
        target=target,
        trail_active=False,
        trail_sl=sl,
        trail_target=target,
        peak=entry,
    )


def update_trailing(
    risk: RiskLevels,
    ltp: float,
    *,
    activate_rupees: float,
    trail_sl_distance: float,
    trail_target_distance: float,
) -> RiskLevels:
    """Update trailing SL/Target for a long option premium."""
    px = float(ltp)
    risk.peak = max(risk.peak, px)

    if not risk.trail_active:
        if px >= risk.entry + abs(float(activate_rupees)):
            risk.trail_active = True
            logger.info("GO single-leg trailing activated at LTP=%.2f", px)
        else:
            return risk

    # Ratchet SL up; move target further as peak rises
    new_sl = risk.peak - abs(float(trail_sl_distance))
    risk.trail_sl = max(risk.trail_sl, new_sl, risk.sl)
    new_tgt = risk.peak + abs(float(trail_target_distance))
    risk.trail_target = max(risk.trail_target, new_tgt, risk.target)
    return risk


def check_exit(risk: RiskLevels, ltp: float) -> str | None:
    """Return exit reason or None."""
    px = float(ltp)
    sl = risk.trail_sl if risk.trail_active else risk.sl
    tgt = risk.trail_target if risk.trail_active else risk.target
    if px <= sl:
        return "trailing_sl" if risk.trail_active else "fixed_sl"
    if px >= tgt:
        return "trailing_target" if risk.trail_active else "fixed_target"
    return None


def _quote_premium(broker: Any, symbol: str) -> float:
    quotes = broker.get_ltp([symbol])
    raw = quotes.get(symbol)
    try:
        px = float(raw or 0)
    except (TypeError, ValueError):
        px = 0.0
    if px > 0:
        return px
    for val in quotes.values():
        try:
            candidate = float(val)
        except (TypeError, ValueError):
            continue
        if candidate > 0:
            return candidate
    raise RuntimeError(f"No positive LTP for {symbol}: {quotes}")


def enter_single_leg(
    broker: Any,
    *,
    option_type: str,
    strike: int | None,
    lots: int,
    lot_size: int,
    sl_rupees: float,
    target_rupees: float,
    expiry: date | str | None = None,
    params: dict[str, Any] | None = None,
    root=None,
    notify: NotifyFn | None = None,
) -> dict[str, Any]:
    """Buy one CE/PE, arm fixed SL/Target, save GO book."""
    p = params or {}
    opt = option_type.upper().strip()
    if opt not in {"CE", "PE"}:
        raise ValueError(f"option_type must be CE or PE, got {option_type!r}")

    exp = resolve_expiry(expiry)
    step = int(p.get("strike_step", 50))

    if strike is None:
        spot = float(broker.get_nifty_ltp())
        strike = snap_strike(spot, step)
    else:
        strike = snap_strike(float(strike), step)

    qty = int(lots) * int(lot_size)
    if qty <= 0:
        raise ValueError("qty must be positive")

    symbol, _ = resolve_symbol(strike, opt, exp)
    product = str(p.get("product_type", "MARGIN"))
    chase_timeout = float(p.get("chase_timeout_sec", 45.0))
    chase_interval = float(p.get("chase_interval_sec", 5.0))
    buffer_pct = float(p.get("aggressive_buffer_pct", 10.0))

    if notify:
        notify(f"GO single-leg BUY {symbol} qty={qty}…")

    if hasattr(broker, "place_aggressive_limit"):
        order_id = broker.place_aggressive_limit(
            symbol=symbol,
            qty=qty,
            side="BUY",
            buffer_pct=buffer_pct,
            chase_timeout_sec=chase_timeout,
            chase_interval_sec=chase_interval,
            trade_type=product,
        )
    else:
        order_id = broker.place_market_order(
            symbol=symbol, qty=qty, side="BUY", trade_type=product
        )

    try:
        entry_px = _quote_premium(broker, symbol)
    except Exception:
        entry_px = float(p.get("fallback_entry_premium", 0) or 0)

    risk = initial_risk(entry_px or 1.0, sl_rupees, target_rupees)

    from core.nifty_option_expiry import expiry_label_from_date

    book = make_single_book(
        option_type=opt,
        strike=strike,
        symbol=symbol,
        qty=qty,
        expiry=expiry_label_from_date(exp),
        entry_premium=risk.entry,
        sl_price=risk.sl,
        target_price=risk.target,
        order_id=str(order_id),
        status="open",
    )
    book["trail_sl"] = risk.trail_sl
    book["trail_target"] = risk.trail_target
    book["peak_premium"] = risk.peak
    path = save_book(book, root=root)
    book["_path"] = str(path)
    if notify:
        notify(
            f"GO single-leg opened {symbol}\n"
            f"entry≈{risk.entry:.2f} SL={risk.sl:.2f} TGT={risk.target:.2f}"
        )
    return book


def exit_single_leg(
    broker: Any,
    book: dict[str, Any],
    *,
    reason: str,
    params: dict[str, Any] | None = None,
    root=None,
    notify: NotifyFn | None = None,
) -> dict[str, Any]:
    """SELL flatten the open single-leg book."""
    if book.get("mode") != "single":
        raise ValueError("Not a single-leg book")
    if book.get("status") == "closed":
        return book

    p = params or {}
    symbol = str(book.get("symbol") or "")
    qty = int(book.get("qty") or 0)
    if not symbol or qty <= 0:
        raise ValueError("Book missing symbol/qty")

    product = str(p.get("product_type", "MARGIN"))
    chase_timeout = float(p.get("chase_timeout_sec", 45.0))
    chase_interval = float(p.get("chase_interval_sec", 5.0))
    buffer_pct = float(p.get("aggressive_buffer_pct", 10.0))

    if notify:
        notify(f"GO Exit ({reason}): SELL {symbol} qty={qty}…")

    if hasattr(broker, "place_aggressive_limit"):
        oid = broker.place_aggressive_limit(
            symbol=symbol,
            qty=qty,
            side="SELL",
            buffer_pct=buffer_pct,
            chase_timeout_sec=chase_timeout,
            chase_interval_sec=chase_interval,
            trade_type=product,
        )
    else:
        oid = broker.place_market_order(
            symbol=symbol, qty=qty, side="SELL", trade_type=product
        )

    book["status"] = "closed"
    book["exit_reason"] = reason
    book["exit_order_id"] = str(oid)
    save_book(book, root=root)
    if notify:
        notify(f"GO single-leg closed ({reason}) order={oid}")
    return book


class SingleLegMonitor:
    """Background poller for open single-leg SL / Target / trailing."""

    def __init__(
        self,
        broker: Any,
        *,
        params: dict[str, Any] | None = None,
        root=None,
        notify: NotifyFn | None = None,
        poll_seconds: float = 3.0,
    ) -> None:
        self.broker = broker
        self.params = params or {}
        self.root = root
        self.notify = notify
        self.poll_seconds = max(1.0, float(poll_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="go-single-leg-monitor", daemon=True
        )
        self._thread.start()
        logger.info("GO single-leg monitor started")

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:
                logger.error("GO single-leg monitor error: %s", exc, exc_info=True)
            self._stop.wait(self.poll_seconds)

    def poll_once(self) -> None:
        if self.broker is None:
            return
        book = load_active_book(self.root)
        if not book or book.get("mode") != "single" or book.get("status") != "open":
            return

        symbol = str(book.get("symbol") or "")
        if not symbol:
            return

        try:
            ltp = _quote_premium(self.broker, symbol)
        except Exception as exc:
            logger.warning("GO single-leg LTP failed: %s", exc)
            return

        risk = RiskLevels(
            entry=float(book.get("entry_premium") or 0),
            sl=float(book.get("sl_price") or 0),
            target=float(book.get("target_price") or 0),
            trail_active=bool(book.get("trail_active")),
            trail_sl=float(book.get("trail_sl") or book.get("sl_price") or 0),
            trail_target=float(book.get("trail_target") or book.get("target_price") or 0),
            peak=float(book.get("peak_premium") or book.get("entry_premium") or 0),
        )
        risk = update_trailing(
            risk,
            ltp,
            activate_rupees=float(self.params.get("trail_activate_rupees", 5.0)),
            trail_sl_distance=float(self.params.get("trail_sl_distance", 3.0)),
            trail_target_distance=float(self.params.get("trail_target_distance", 5.0)),
        )
        book["trail_active"] = risk.trail_active
        book["trail_sl"] = risk.trail_sl
        book["trail_target"] = risk.trail_target
        book["peak_premium"] = risk.peak
        book["last_ltp"] = ltp
        save_book(book, root=self.root)

        reason = check_exit(risk, ltp)
        if reason:
            exit_single_leg(
                self.broker,
                book,
                reason=reason,
                params=self.params,
                root=self.root,
                notify=self.notify,
            )

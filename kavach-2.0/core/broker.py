"""
Batman v3 — Dhan-Tradehull broker adapter.

Wraps the ``Dhan_Tradehull.Tradehull`` client with:
    • access_token auth (daily manual token via DRISHTI bot)
    • Hot-reload of token without process restart
    • Token age monitoring (24h TTL, warn after 20h)
    • Unified error handling → BatmanError types
    • Retry with exponential backoff on transient failures
    • Circuit breaker to prevent cascading failures
    • Order confirmation (poll TRADED status)
    • Convenience methods for the Batman strategy
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pandas as pd

from .exceptions import (
    BrokerAuthError,
    BrokerConnectionError,
    OrderCancelError,
    OrderPlacementError,
    PositionError,
)
from .positions import fetch_positions_rest
from .resilience import CircuitBreaker, confirm_order, retry

if TYPE_CHECKING:
    from .models import LTPQuote

logger = logging.getLogger("batman.broker")

# Token is valid for 24h; refresh after 20h for safety
_TOKEN_TTL_HOURS = 20
_TRADEHULL_TOKEN_DIR = Path("Dependencies")


def _sync_tradehull_token_cache(access_token: str) -> None:
    """Write today's JWT so Tradehull does not reuse a stale cached token."""
    today = date.today().strftime("%Y-%m-%d")
    token_file = _TRADEHULL_TOKEN_DIR / f"token_{today}.txt"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(f"{today}|{access_token}", encoding="utf-8")


class BatmanBroker:
    """High-level broker interface around Dhan-Tradehull.

    Usage::

        broker = BatmanBroker.connect_with_token(client_code, access_token)
        ltp = broker.get_nifty_ltp()
        broker.hot_reload_token(new_token)   # called by DRISHTI bot each morning
    """

    def __init__(
        self,
        tradehull_instance,
        auth_time: datetime | None = None,
        *,
        client_code: str = "",
        access_token: str = "",
    ):
        self._tsl = tradehull_instance
        self._auth_time = auth_time or datetime.now()
        self._client_code = client_code
        self._access_token = access_token
        self._lock = threading.Lock()
        self._runtime_mode_provider: Callable[[], str] | None = None
        self._circuit = CircuitBreaker(
            name="broker",
            failure_threshold=5,
            recovery_timeout=60.0,
        )

    # ── Factories ─────────────────────────────────────────────

    @classmethod
    def connect_with_token(cls, client_code: str, access_token: str) -> BatmanBroker:
        """Create a Tradehull session using an access_token (Dhan JWT).

        The access_token is obtained manually from the Dhan developer portal
        and is valid for 24 hours.  DRISHTI bot supplies a fresh token each
        morning via Telegram; ``hot_reload_token()`` updates the running instance.
        """
        try:
            from Dhan_Tradehull import Tradehull
        except ImportError as exc:
            raise BrokerAuthError(
                "Dhan-Tradehull not installed. " "Run: pip install Dhan-Tradehull"
            ) from exc

        if not access_token:
            raise BrokerAuthError(
                "access_token is empty. " "Send a fresh Dhan token to DRISHTI bot before starting."
            )

        try:
            logger.info("Connecting to Dhan (access_token mode) …")
            _sync_tradehull_token_cache(access_token)
            tsl = Tradehull(
                ClientCode=client_code,
                mode="access_token",
                token_id=access_token,
            )
            logger.info("Dhan broker connected ✓")
            return cls(
                tsl,
                datetime.now(),
                client_code=client_code,
                access_token=access_token,
            )
        except Exception as exc:
            raise BrokerAuthError(f"Dhan broker connection failed: {exc}") from exc

    # ── Token management ─────────────────────────────────────

    def hot_reload_token(self, client_code: str, access_token: str) -> None:
        """Replace the access_token without restarting the process.

        Called by DRISHTI bot whenever the user sends a fresh Dhan JWT.
        Thread-safe — the lock ensures no in-flight broker call reads a
        partially-swapped Tradehull instance.
        """
        new_instance = BatmanBroker.connect_with_token(client_code, access_token)
        with self._lock:
            self._tsl = new_instance._tsl
            self._auth_time = datetime.now()
            self._client_code = client_code
            self._access_token = access_token
        logger.info("Broker token hot-reloaded ✓  (new auth_time=%s)", self._auth_time)

    def needs_reauth(self) -> bool:
        """True when the current token has been held for ≥ 20h.

        Dhan tokens are valid for 24h; we warn at 20h to leave a 4h
        window for Rahul to send a fresh token via DRISHTI before expiry.
        """
        return datetime.now() - self._auth_time > timedelta(hours=_TOKEN_TTL_HOURS)

    @property
    def token_age_hours(self) -> float:
        """Hours since the current token was loaded."""
        return (datetime.now() - self._auth_time).total_seconds() / 3600

    def _snapshot_tsl(self):
        """Return Tradehull handle under lock (safe during hot-reload)."""
        with self._lock:
            return self._tsl, self._client_code, self._access_token

    def set_runtime_mode_provider(self, provider: Callable[[], str] | None) -> None:
        """Attach a runtime mode resolver used to block live orders in mock mode."""
        self._runtime_mode_provider = provider

    def _runtime_mode(self) -> str:
        if self._runtime_mode_provider is None:
            return "live"
        try:
            mode = str(self._runtime_mode_provider() or "live").strip().lower()
        except Exception:
            return "live"
        return mode if mode in {"mock", "live"} else "live"

    def _enforce_live_mode_for_orders(self) -> None:
        if self._runtime_mode() != "live":
            raise OrderPlacementError(
                "Order placement blocked because runtime mode is MOCK. Switch SANCHALAK to live mode before sending trading commands."
            )

    # ── Market Data ──────────────────────────────────────────

    def get_ltp(self, names: list[str]) -> dict[str, float]:
        """Get last traded price for one or more instruments.

        ``names`` can be index names (``['NIFTY']``) or trading symbols.
        Returns ``{'NIFTY': 25234.50, ...}``.
        """
        try:
            tsl, _, _ = self._snapshot_tsl()
            with self._circuit:
                data = cast(dict[str, float], tsl.get_ltp_data(names=names))
                if not data:
                    raise BrokerConnectionError(f"LTP fetch returned no data for: {names}")
                return data
        except BrokerConnectionError:
            raise
        except Exception as exc:
            raise BrokerConnectionError(f"LTP fetch failed: {exc}") from exc

    @retry(max_attempts=3, base_delay=0.5)
    def get_nifty_ltp(self) -> float:
        """Shortcut — return NIFTY index LTP as a float."""
        data = self.get_ltp(["NIFTY"])
        if "NIFTY" not in data:
            raise BrokerConnectionError("NIFTY LTP missing from broker response")
        return float(data["NIFTY"])

    def get_nifty_quote(self) -> LTPQuote:
        """Return NIFTY LTP as a typed LTPQuote.

        Structured counterpart to ``get_nifty_ltp()``.  Use this wherever
        the caller needs symbol + timestamp alongside the price (e.g. logging,
        output writing, cross-codebase hand-offs with the Sapient LTP fetcher).
        """
        from datetime import datetime as _dt

        from .models import LTPQuote

        ltp = self.get_nifty_ltp()
        return LTPQuote(symbol="NIFTY", ltp=ltp, timestamp=_dt.now())

    def get_option_chain(
        self,
        underlying: str = "NIFTY",
        exchange: str = "NFO",
        expiry: int = 0,
        num_strikes: int = 20,
    ) -> pd.DataFrame:
        """Retrieve option chain as a DataFrame."""
        try:
            tsl, _, _ = self._snapshot_tsl()
            df = tsl.get_option_chain(
                Underlying=underlying,
                exchange=exchange,
                expiry=expiry,
                num_strikes=num_strikes,
            )
            if df is None:
                return pd.DataFrame()
            return df
        except Exception as exc:
            raise BrokerConnectionError(f"Option chain failed: {exc}") from exc

    def get_fno_ltp_by_security_ids(self, security_ids: list[int]) -> dict[int, float]:
        """NSE F&O LTP via Dhan ``POST /marketfeed/ltp`` (Data API subscription)."""
        from .dhan_market_quote import fetch_fno_ltp_rest

        if not self._client_code or not self._access_token:
            raise BrokerConnectionError("Broker missing client_code or access_token")
        return fetch_fno_ltp_rest(self._client_code, self._access_token, security_ids)

    def get_nifty_option_ltps(
        self,
        legs: list[tuple[int, str]],
        *,
        expiry_date: date,
    ) -> dict[tuple[int, str], float]:
        """Resolve strikes to securityIds, then fetch live option LTPs."""
        from core.dhan_rest_quote import fetch_nifty_option_ltps_rest

        return fetch_nifty_option_ltps_rest(
            self._client_code,
            self._access_token,
            legs,
            expiry_date=expiry_date,
        )

    # ── Strike selection ─────────────────────────────────────

    @retry(max_attempts=3, base_delay=1.0)
    def atm_strike(self, underlying: str = "NIFTY", expiry: int = 0) -> tuple[str, str, int]:
        """Return (CE_symbol, PE_symbol, ATM_strike)."""
        try:
            tsl, _, _ = self._snapshot_tsl()
            ce, pe, strike = tsl.ATM_Strike_Selection(Underlying=underlying, Expiry=expiry)
            return ce, pe, int(strike)
        except Exception as exc:
            raise BrokerConnectionError(f"ATM strike selection failed: {exc}") from exc

    @retry(max_attempts=3, base_delay=1.0)
    def otm_strike(
        self,
        underlying: str = "NIFTY",
        expiry: int = 0,
        otm_count: int = 6,
    ) -> tuple[str, str, int, int]:
        """Return (CE_symbol, PE_symbol, CE_strike, PE_strike).

        ``otm_count`` is the number of strike steps away from ATM.
        """
        try:
            tsl, _, _ = self._snapshot_tsl()
            ce, pe, ce_strike, pe_strike = tsl.OTM_Strike_Selection(
                Underlying=underlying, Expiry=expiry, OTM_count=otm_count
            )
            return ce, pe, int(ce_strike), int(pe_strike)
        except Exception as exc:
            raise BrokerConnectionError(f"OTM strike selection failed: {exc}") from exc

    # ── Order management ─────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        exchange: str = "NFO",
        qty: int = 75,
        price: float = 0,
        trigger_price: float = 0,
        order_type: str = "MARKET",
        transaction_type: str = "BUY",
        trade_type: str = "MARGIN",
        *,
        confirm: bool | None = None,
    ) -> str:
        """Place an order and return the order ID.

        Args:
            symbol: e.g. ``'NIFTY 10 MAR 25500 CALL'``
            exchange: ``'NFO'``, ``'NSE'``, ``'INDEX'``, etc.
            qty: number of shares (must be multiples of lot size)
            price: limit price (0 for MARKET)
            trigger_price: trigger price for STOPLIMIT/STOPMARKET
            order_type: MARKET | LIMIT | STOPLIMIT | STOPMARKET
            transaction_type: BUY | SELL
            trade_type: MIS | MARGIN | CNC | CO | BO | MTF
            confirm: When None, MARKET confirms async and LIMIT sync.
                Pass False when the caller manages fill/chase itself.
        """
        self._enforce_live_mode_for_orders()
        try:
            tsl, _, _ = self._snapshot_tsl()
            order_id = tsl.order_placement(
                tradingsymbol=symbol,
                exchange=exchange,
                quantity=qty,
                price=price,
                trigger_price=trigger_price,
                order_type=order_type,
                transaction_type=transaction_type,
                trade_type=trade_type,
            )
            logger.info(
                "Order placed: %s %s %s qty=%d price=%s → order_id=%s",
                transaction_type,
                symbol,
                order_type,
                qty,
                price,
                order_id,
            )

            oid_str = str(order_id)

            # For MARKET orders confirmation is fire-and-forget — Dhan fills
            # them in <1s so we never block the calling thread (iron condor
            # entry would otherwise stall for up to 32s across 4 legs).
            # For LIMIT/STOPLIMIT orders we still confirm synchronously so the
            # caller knows immediately if the order was rejected — unless the
            # caller opted out (aggressive LIMIT chase).
            do_confirm = (order_type != "MARKET") if confirm is None else confirm
            if order_type == "MARKET" and confirm is None:
                import threading as _t

                _t.Thread(
                    target=self._confirm_async,
                    args=(oid_str,),
                    daemon=True,
                    name=f"confirm-{oid_str}",
                ).start()
            elif do_confirm:
                try:
                    status = confirm_order(self, oid_str, max_wait=10.0, poll_interval=1.0)
                    if status == "REJECTED":
                        raise OrderPlacementError(f"Order {oid_str} REJECTED after placement")
                except OrderPlacementError:
                    raise
                except Exception as conf_exc:
                    logger.warning("Order confirmation poll failed (non-fatal): %s", conf_exc)

            return oid_str
        except Exception as exc:
            raise OrderPlacementError(
                f"Order failed: {transaction_type} {qty}×{symbol} ({order_type}): {exc}"
            ) from exc

    def _confirm_async(self, order_id: str) -> None:
        """Background thread: poll order status and log the outcome."""
        try:
            status = confirm_order(self, order_id, max_wait=10.0, poll_interval=1.0)
            if status == "REJECTED":
                logger.error(
                    "MARKET order %s was REJECTED — manual intervention required", order_id
                )
            else:
                logger.debug("MARKET order %s confirmed → %s", order_id, status)
        except Exception as exc:
            logger.warning("Async confirmation failed for %s: %s", order_id, exc)

    def place_market_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        trade_type: str = "MARGIN",
        exchange: str = "NFO",
    ) -> str:
        """Convenience: place a MARKET order.  ``side`` = 'BUY' / 'SELL'."""
        return self.place_order(
            symbol=symbol,
            exchange=exchange,
            qty=qty,
            order_type="MARKET",
            transaction_type=side,
            trade_type=trade_type,
        )

    def modify_order(
        self,
        order_id: str,
        *,
        order_type: str = "LIMIT",
        qty: int,
        price: float,
        trigger_price: float = 0,
    ) -> str:
        """Modify a pending order (price/qty/type). Used for LIMIT chase."""
        self._enforce_live_mode_for_orders()
        try:
            tsl, _, _ = self._snapshot_tsl()
            # Tradehull uses OrderID + order_type + quantity + price.
            result = tsl.modify_order(
                OrderID=order_id,
                order_type=order_type,
                quantity=qty,
                price=price,
                trigger_price=trigger_price,
            )
            logger.info(
                "Order modified: %s → type=%s qty=%d price=%s (%s)",
                order_id,
                order_type,
                qty,
                price,
                result,
            )
            return str(order_id)
        except Exception as exc:
            raise OrderPlacementError(f"Modify failed for {order_id}: {exc}") from exc

    def place_aggressive_limit(
        self,
        symbol: str,
        qty: int,
        side: str,
        *,
        buffer_pct: float = 10.0,
        tick_size: float = 0.05,
        chase_timeout_sec: float = 45.0,
        chase_interval_sec: float = 5.0,
        trade_type: str = "MARGIN",
        exchange: str = "NFO",
    ) -> str:
        """Place a marketable LIMIT (LTP ± buffer) and chase until fill or timeout.

        SEBI/algo-safe replacement for MARKET on ATO protect entry/exit.
        """
        import time

        from core.order_pricing import aggressive_limit_price

        self._enforce_live_mode_for_orders()
        side_u = str(side).upper()
        if side_u not in {"BUY", "SELL"}:
            raise OrderPlacementError(f"Invalid side for aggressive LIMIT: {side}")

        def _quote_limit() -> float:
            quotes = self.get_ltp([symbol])
            ltp = float(quotes.get(symbol) or 0.0)
            if ltp <= 0:
                # Some Tradehull feeds key by alternate name — take first positive.
                for val in quotes.values():
                    try:
                        candidate = float(val)
                    except (TypeError, ValueError):
                        continue
                    if candidate > 0:
                        ltp = candidate
                        break
            if ltp <= 0:
                raise OrderPlacementError(f"No positive LTP for {symbol}: {quotes}")
            return aggressive_limit_price(
                ltp, side_u, buffer_pct=buffer_pct, tick=tick_size
            )

        limit_px = _quote_limit()
        order_id = self.place_order(
            symbol=symbol,
            exchange=exchange,
            qty=qty,
            price=limit_px,
            order_type="LIMIT",
            transaction_type=side_u,
            trade_type=trade_type,
            confirm=False,
        )
        logger.info(
            "Aggressive LIMIT placed: %s %s qty=%d limit=%.2f buffer=%.1f%% → %s",
            side_u,
            symbol,
            qty,
            limit_px,
            buffer_pct,
            order_id,
        )

        deadline = time.time() + max(0.0, float(chase_timeout_sec))
        next_chase = time.time() + max(0.5, float(chase_interval_sec))
        last_status = "UNKNOWN"

        while time.time() < deadline:
            try:
                last_status = self.get_order_status(order_id)
            except Exception as exc:
                logger.warning("Aggressive LIMIT status poll failed for %s: %s", order_id, exc)
                time.sleep(0.5)
                continue

            status_u = str(last_status).upper()
            if status_u == "TRADED":
                logger.info("Aggressive LIMIT %s TRADED", order_id)
                return order_id
            if status_u in {"REJECTED", "CANCELLED", "EXPIRED"}:
                raise OrderPlacementError(
                    f"Aggressive LIMIT {order_id} ended as {status_u}"
                )

            now = time.time()
            if now >= next_chase and status_u in {"PENDING", "TRANSIT", "PART_TRADED", "UNKNOWN"}:
                try:
                    new_px = _quote_limit()
                    if abs(new_px - limit_px) >= tick_size / 2:
                        self.modify_order(
                            order_id,
                            order_type="LIMIT",
                            qty=qty,
                            price=new_px,
                        )
                        limit_px = new_px
                        logger.info(
                            "Aggressive LIMIT chase: %s → new limit=%.2f", order_id, new_px
                        )
                except Exception as chase_exc:
                    logger.warning(
                        "Aggressive LIMIT chase modify failed for %s: %s",
                        order_id,
                        chase_exc,
                    )
                next_chase = now + max(0.5, float(chase_interval_sec))

            time.sleep(0.5)

        # Timeout — cancel residual and fail so ATO retry / halt can run.
        try:
            self.cancel_order(order_id)
        except Exception as cancel_exc:
            logger.warning(
                "Aggressive LIMIT cancel after timeout failed for %s: %s",
                order_id,
                cancel_exc,
            )
        raise OrderPlacementError(
            f"Aggressive LIMIT {order_id} timed out after {chase_timeout_sec}s "
            f"(last status={last_status})"
        )

    def get_order_status(self, order_id: str) -> str:
        """Return order status string (TRADED / PENDING / REJECTED …)."""
        try:
            tsl, _, _ = self._snapshot_tsl()
            return str(tsl.get_order_status(orderid=order_id))
        except Exception as exc:
            raise OrderPlacementError(f"Order status failed: {exc}") from exc

    def cancel_order(self, order_id: str) -> str:
        """Cancel a pending order."""
        try:
            tsl, _, _ = self._snapshot_tsl()
            return str(tsl.cancel_order(OrderID=order_id))
        except Exception as exc:
            raise OrderCancelError(f"Cancel failed: {exc}") from exc

    def cancel_all_intraday(self) -> None:
        """Cancel all open intraday (MIS) orders."""
        try:
            tsl, _, _ = self._snapshot_tsl()
            tsl.cancel_all_orders()
            logger.info("All intraday orders cancelled")
        except Exception as exc:
            raise OrderCancelError(f"Cancel-all failed: {exc}") from exc

    # ── Positions & P&L ──────────────────────────────────────

    @retry(max_attempts=2, base_delay=1.0)
    def get_positions(self) -> pd.DataFrame:
        """Return current positions as a DataFrame."""
        try:
            tsl, client_code, access_token = self._snapshot_tsl()
            result = tsl.get_positions()
            if isinstance(result, dict):
                raise PositionError(f"Tradehull positions failed: {result.get('remarks', result)}")
            return cast(pd.DataFrame, result)
        except PositionError:
            if client_code and access_token:
                logger.warning("Tradehull positions failed — falling back to Dhan REST")
                return fetch_positions_rest(client_code, access_token)
            raise
        except Exception as exc:
            if client_code and access_token:
                logger.warning("Tradehull positions error (%s) — falling back to Dhan REST", exc)
                try:
                    return fetch_positions_rest(client_code, access_token)
                except Exception as rest_exc:
                    raise PositionError(
                        f"Positions fetch failed (Tradehull + REST): {rest_exc}"
                    ) from rest_exc
            raise PositionError(f"Positions fetch failed: {exc}") from exc

    @retry(max_attempts=2, base_delay=1.0)
    def get_live_pnl(self) -> float:
        """Return total live (unrealized) P&L."""
        try:
            tsl, _, _ = self._snapshot_tsl()
            return float(tsl.get_live_pnl())
        except Exception as exc:
            raise PositionError(f"Live PnL failed: {exc}") from exc

    def get_balance(self) -> float:
        """Return available margin / balance."""
        try:
            tsl, _, _ = self._snapshot_tsl()
            return float(tsl.get_balance())
        except Exception as exc:
            raise BrokerConnectionError(f"Balance fetch failed: {exc}") from exc

    def get_orderbook(self) -> pd.DataFrame:
        """Return full order book for the day."""
        try:
            tsl, _, _ = self._snapshot_tsl()
            return tsl.get_orderbook()
        except Exception as exc:
            raise BrokerConnectionError(f"Orderbook failed: {exc}") from exc

    def get_holdings(self) -> pd.DataFrame:
        """Return holdings."""
        try:
            tsl, _, _ = self._snapshot_tsl()
            return tsl.get_holdings()
        except Exception as exc:
            raise BrokerConnectionError(f"Holdings failed: {exc}") from exc

    def get_lot_size(self, symbol: str) -> int:
        """Return lot size for a symbol (NIFTY index options default 65)."""
        from core.position_scope import resolve_nifty_lot_size

        broker_lot: int | None = None
        try:
            tsl, _, _ = self._snapshot_tsl()
            raw = int(tsl.get_lot_size(tradingsymbol=symbol))
            if raw > 0:
                broker_lot = raw
        except Exception:
            pass
        return resolve_nifty_lot_size(broker_lot_size=broker_lot)

    # ── Position close helpers ───────────────────────────────

    def close_position(
        self,
        symbol: str,
        qty: int,
        side: str,
        trade_type: str = "MARGIN",
        exchange: str = "NFO",
    ) -> str:
        """Close an open position by placing an opposite MARKET order.

        If you are short 130 qty, pass ``side='BUY', qty=130``.
        If you are long  65 qty,  pass ``side='SELL', qty=65``.
        """
        return self.place_market_order(
            symbol=symbol,
            qty=abs(qty),
            side=side,
            trade_type=trade_type,
            exchange=exchange,
        )

    def close_all_positions(self, trade_type: str = "MARGIN") -> list[str]:
        """Close every open position with an opposite market order.

        Returns list of order IDs placed.
        """
        positions = self.get_positions()
        if positions is None or positions.empty:
            logger.info("No positions to close")
            return []

        order_ids: list[str] = []
        for _, row in positions.iterrows():
            symbol = row.get("tradingSymbol") or row.get("tradingsymbol", "")
            net_qty = int(row.get("netQty", 0) or row.get("buyQty", 0) - row.get("sellQty", 0))
            if net_qty == 0 or not symbol:
                continue

            side = "SELL" if net_qty > 0 else "BUY"
            try:
                oid = self.close_position(
                    symbol=symbol,
                    qty=abs(net_qty),
                    side=side,
                    trade_type=trade_type,
                )
                order_ids.append(oid)
            except OrderPlacementError as exc:
                logger.error("Failed to close %s: %s", symbol, exc)

        logger.info("Closed %d positions", len(order_ids))
        return order_ids

    # ── Telegram via Tradehull ───────────────────────────────

    def send_alert(self, message: str, chat_id: str, bot_token: str) -> None:
        """Send a Telegram alert using Tradehull's built-in method."""
        try:
            self._tsl.send_telegram_alert(
                message=message,
                receiver_chat_id=chat_id,
                bot_token=bot_token,
            )
        except Exception:
            logger.warning("Tradehull send_telegram_alert failed (non-critical)")

    # ── Dunder ───────────────────────────────────────────────

    @property
    def circuit_status(self) -> dict:
        """Return circuit breaker status for health checks."""
        return self._circuit.status()

    def __repr__(self) -> str:
        age = datetime.now() - self._auth_time
        return f"<BatmanBroker auth_age={age}>"

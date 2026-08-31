"""Kavach 2.0 live broker — Kite Connect v3 REST (Zerodha).

Same method surface as BatmanBroker. Order mapping (Dhan → Kite):
  STOPLIMIT → SL (trigger + limit)
  STOPMARKET → SL-M
  LIMIT / MARKET unchanged
  trade_type MARGIN → product NRML (positional F&O)
  exchange NFO

ATO BUY park and ATO SELL cover stay resting trigger+limit, now Kite SL.
No KiteTicker. Quotes prefer Feeder cache/IPC.
Docs: https://kite.trade/docs/connect/v3/orders/
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import pandas as pd

from core.exceptions import (
    BrokerConnectionError,
    OrderCancelError,
    OrderPlacementError,
    PositionError,
)
from core.models import LTPQuote
from core.resilience import CircuitBreaker, confirm_order, retry
from core.zerodha_credentials import ZerodhaOrderCreds, load_zerodha_order_creds
from core.zerodha_http import KiteAPIError, ZerodhaRestClient
from core.zerodha_instruments import (
    kite_tradingsymbol_from_any,
    load_nifty_options,
    nearest_nifty_expiry,
    resolve_nifty_option_kite,
)

logger = logging.getLogger("batman.zerodha.broker")

_ORDER_TYPE = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "STOPLIMIT": "SL",
    "STOP_LOSS": "SL",
    "SL": "SL",
    "STOPMARKET": "SL-M",
    "STOP_LOSS_MARKET": "SL-M",
    "SL-M": "SL-M",
    "SLM": "SL-M",
}
_PRODUCT = {
    "MARGIN": "NRML",
    "NRML": "NRML",
    "MIS": "MIS",
    "CNC": "CNC",
    "MTF": "MTF",
}
_TERMINAL = {"TRADED", "COMPLETE", "REJECTED", "CANCELLED", "CANCELED", "EXPIRED"}


def _map_status(raw: str) -> str:
    status = str(raw or "").strip().upper()
    if status in {"COMPLETE", "TRADED"}:
        return "TRADED"
    if status in {"CANCELLED", "CANCELED"}:
        return "CANCELLED"
    if status == "REJECTED":
        return "REJECTED"
    if status == "EXPIRED":
        return "EXPIRED"
    return "PENDING"


def _positions_df(net_rows: list[dict[str, Any]]) -> pd.DataFrame:
    records = []
    for row in net_rows or []:
        qty = int(row.get("quantity") or 0)
        avg = float(row.get("average_price") or 0)
        token = row.get("instrument_token") or ""
        records.append(
            {
                "tradingsymbol": row.get("tradingsymbol") or "",
                "tradingSymbol": row.get("tradingsymbol") or "",
                "exchange": row.get("exchange") or "NFO",
                "quantity": qty,
                "netQty": qty,
                "average_price": avg,
                "avgPrice": avg,
                "instrument_token": token,
                "instrumentToken": token,
                "securityId": token,
                "product": row.get("product") or "",
                "pnl": row.get("pnl") or 0,
                "buyQty": int(row.get("buy_quantity") or 0),
                "sellQty": int(row.get("sell_quantity") or 0),
                "expiry": row.get("expiry") or "",
            }
        )
    return pd.DataFrame(records)



# Day P&L cache lives in core.day_pnl_cache (shared across duplicate core trees).
from core.day_pnl_cache import cached_day_pnl, update_day_pnl_from_positions


class ZerodhaBroker:
    """Kite REST broker used by Kavach 2.0 for live/paper-live punches."""

    def __init__(self, creds: ZerodhaOrderCreds, client: ZerodhaRestClient):
        self._creds = creds
        self._http = client
        self._auth_time = datetime.now()
        self._lock = threading.Lock()
        self._runtime_mode_provider: Callable[[], str] | None = None
        self._circuit = CircuitBreaker(name="zerodha", failure_threshold=5, recovery_timeout=60.0)
        self._client_code = creds.user_id or creds.api_key
        self._access_token = creds.access_token

    @classmethod
    def connect(cls, root=None, access_token: str | None = None) -> "ZerodhaBroker":
        creds = load_zerodha_order_creds(root)
        if access_token:
            creds.access_token = access_token.strip()
        if not creds.ok:
            raise BrokerConnectionError(
                "Zerodha api_key/access_token missing. Paste token on TOKEN or wait for feeder login."
            )
        client = ZerodhaRestClient(creds.api_key, creds.access_token)
        broker = cls(creds, client)
        try:
            profile = client.request("GET", "/user/profile", quote=True)
            user = str((profile or {}).get("user_id") or creds.user_id)
            logger.info("Zerodha REST connected user_id=%s", user)
        except KiteAPIError as exc:
            client.close()
            raise BrokerConnectionError(f"Zerodha profile failed: {exc}") from exc
        try:
            from core.zerodha_instruments import refresh_nfo_instruments

            refresh_nfo_instruments(client, root=root)
        except Exception as exc:
            logger.warning("NFO instrument cache warm failed: %s", exc)
        return broker

    def hot_reload_token(self, client_code: str, access_token: str) -> None:
        token = (access_token or "").strip()
        if not token:
            return
        with self._lock:
            self._access_token = token
            if client_code:
                self._client_code = client_code
            self._http.set_access_token(token)
            self._auth_time = datetime.now()
        logger.info("Zerodha access_token reloaded last4=%s", token[-4:])

    def needs_reauth(self) -> bool:
        try:
            self._http.request("GET", "/user/profile", quote=True)
            return False
        except Exception:
            return True

    def token_age_hours(self) -> float:
        return (datetime.now() - self._auth_time).total_seconds() / 3600.0

    def set_runtime_mode_provider(self, provider: Callable[[], str] | None) -> None:
        self._runtime_mode_provider = provider

    def _runtime_mode(self) -> str:
        if self._runtime_mode_provider:
            try:
                return str(self._runtime_mode_provider() or "live")
            except Exception:
                return "live"
        return "live"

    def _enforce_live_mode_for_orders(self) -> None:
        if self._runtime_mode() == "mock":
            raise OrderPlacementError("Live Zerodha orders are blocked (runtime mode=mock / not prod).")

    def _symbol(self, symbol: str) -> str:
        return kite_tradingsymbol_from_any(symbol, client=self._http)

    def _product(self, trade_type: str) -> str:
        return _PRODUCT.get(str(trade_type or "MARGIN").upper(), "NRML")

    def _order_type(self, order_type: str) -> str:
        return _ORDER_TYPE.get(str(order_type or "MARKET").upper(), "MARKET")

    # ── Quotes (Feeder first) ─────────────────────────────────

    def get_nifty_ltp(self) -> float:
        try:
            from core.nifty_ltp_feed import read_nifty_ltp_cache

            snap = read_nifty_ltp_cache()
            if snap is not None and float(snap.ltp) > 0:
                return float(snap.ltp)
        except Exception as exc:
            logger.debug("Feeder NIFTY cache miss: %s", exc)
        data = self._http.request(
            "GET", "/quote/ltp", params={"i": "NSE:NIFTY 50"}, quote=True
        )
        row = (data or {}).get("NSE:NIFTY 50") or {}
        return float(row.get("last_price") or 0)

    def get_nifty_quote(self) -> LTPQuote:
        return LTPQuote(symbol="NIFTY", ltp=self.get_nifty_ltp())

    def get_ltp(self, names: list[str], *, kite_only: bool = False) -> dict[str, float]:
        out: dict[str, float] = {}
        for name in names or []:
            if str(name).upper() in {"NIFTY", "NIFTY 50", "NSE:NIFTY 50"}:
                out[name] = self.get_nifty_ltp()
                continue
            if not kite_only:
                try:
                    from core.feeder_ipc import peek_option_quote

                    sym = self._symbol(str(name))
                    import re

                    m = re.search(r"(\d{4,5})(CE|PE)$", sym, re.I)
                    if m:
                        q = peek_option_quote(strike=int(m.group(1)), option_type=m.group(2).upper())
                        if q and float(q.get("ltp") or 0) > 0:
                            out[name] = float(q["ltp"])
                            continue
                except Exception:
                    pass
            try:
                key = f"NFO:{self._symbol(str(name))}"
                data = self._http.request("GET", "/quote/ltp", params={"i": key}, quote=True)
                row = (data or {}).get(key) or {}
                out[name] = float(row.get("last_price") or 0)
            except Exception as exc:
                logger.warning("Kite LTP failed for %s: %s", name, exc)
                out[name] = 0.0
        return out

    def get_fno_ltp_by_security_ids(self, security_ids: list[int]) -> dict[int, float]:
        out: dict[int, float] = {}
        for sid in security_ids or []:
            try:
                key = f"NFO:{int(sid)}"
                # Kite ltp wants exchange:tradingsymbol, not token. Skip unknown tokens.
                out[int(sid)] = 0.0
            except Exception:
                continue
        del key
        return out


    def get_ltps_kite_batch(self, names: list[str]) -> dict[str, float]:
        """One Kite /quote/ltp for many symbols (hybrid MTM, no Feeder)."""
        out: dict[str, float] = {}
        keys: list[str] = []
        key_to_name: dict[str, str] = {}
        for name in names or []:
            raw = str(name).strip()
            if not raw:
                continue
            sym = self._symbol(raw)
            key = f"NFO:{sym}"
            if key in key_to_name:
                continue
            keys.append(key)
            key_to_name[key] = raw
        if not keys:
            return out
        try:
            params: list[tuple[str, str]] = [("i", k) for k in keys]
            data = self._http.request("GET", "/quote/ltp", params=params, quote=True)
        except Exception as exc:
            logger.debug("Kite batch LTP failed: %s", exc)
            return out
        for key, raw_name in key_to_name.items():
            row = (data or {}).get(key) or {}
            try:
                px = float(row.get("last_price") or 0)
            except (TypeError, ValueError):
                px = 0.0
            if px > 0:
                out[raw_name] = px
                tail = raw_name.split(":")[-1]
                out[tail] = px
        return out

    def get_nifty_option_ltps(
        self,
        legs: list[tuple[int, str]],
        expiry_date: date | None = None,
        *,
        kite_only: bool = False,
    ) -> dict[tuple[int, str], float]:
        out: dict[tuple[int, str], float] = {}
        exp = expiry_date
        if exp is None:
            rows = load_nifty_options(self._http)
            exp = nearest_nifty_expiry(rows)
        for strike, opt in legs or []:
            key = (int(strike), str(opt).upper())
            if not kite_only:
                try:
                    from core.feeder_ipc import peek_option_quote

                    q = peek_option_quote(strike=key[0], option_type=key[1])
                    if q and float(q.get("ltp") or 0) > 0:
                        out[key] = float(q["ltp"])
                        continue
                except Exception:
                    pass
            inst = resolve_nifty_option_kite(key[0], key[1], exp, client=self._http) if exp else None
            if not inst:
                out[key] = 0.0
                continue
            try:
                qkey = f"NFO:{inst.tradingsymbol}"
                data = self._http.request("GET", "/quote/ltp", params={"i": qkey}, quote=True)
                row = (data or {}).get(qkey) or {}
                out[key] = float(row.get("last_price") or 0)
            except Exception as exc:
                logger.debug("option ltp REST failed %s: %s", key, exc)
                out[key] = 0.0
        return out

    def get_option_chain(self, *args: Any, **kwargs: Any) -> Any:
        raise BrokerConnectionError("Option chain via Kite REST is not used — Feeder supplies LTPs.")

    def atm_strike(self, underlying: str = "NIFTY", expiry: int = 0) -> tuple[str, str, int]:
        spot = self.get_nifty_ltp()
        strike = int(round(float(spot) / 50.0) * 50)
        return underlying, "CE", strike

    def otm_strike(
        self, underlying: str = "NIFTY", expiry: int = 0, offset: int = 50
    ) -> tuple[str, str, int]:
        _u, _s, atm = self.atm_strike(underlying, expiry)
        return underlying, "CE", atm + int(offset)

    # ── Orders ────────────────────────────────────────────────

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
        self._enforce_live_mode_for_orders()
        kite_type = self._order_type(order_type)
        payload: dict[str, Any] = {
            "tradingsymbol": self._symbol(symbol),
            "exchange": (exchange or "NFO").upper() if str(exchange).upper() != "INDEX" else "NFO",
            "transaction_type": str(transaction_type).upper(),
            "order_type": kite_type,
            "quantity": int(qty),
            "product": self._product(trade_type),
            "validity": "DAY",
            "tag": "KAVACH2",
        }
        # Autoslice is only for freeze-qty splits. NIFTY options freeze is 1755;
        # sending autoslice=true on 1-lot ATO (65) is rejected by Kite.
        if int(qty) >= 1755:
            payload["autoslice"] = "true"
        if kite_type in {"LIMIT", "SL"}:
            payload["price"] = float(price)
        if kite_type in {"SL", "SL-M"}:
            payload["trigger_price"] = float(trigger_price)
        if kite_type in {"MARKET", "SL-M"}:
            payload["market_protection"] = "-1"
        try:
            data = self._http.request("POST", "/orders/regular", data=payload)
            order_id = str((data or {}).get("order_id") or data)
        except KiteAPIError as exc:
            raise OrderPlacementError(
                f"Order failed: {transaction_type} {qty}×{symbol} ({kite_type}): {exc}"
            ) from exc
        logger.info(
            "Zerodha order placed: %s %s %s qty=%d price=%s trigger=%s → %s",
            transaction_type,
            payload["tradingsymbol"],
            kite_type,
            qty,
            price,
            trigger_price,
            order_id,
        )
        do_confirm = (kite_type != "MARKET") if confirm is None else confirm
        if kite_type == "MARKET" and confirm is None:
            threading.Thread(
                target=self._confirm_async, args=(order_id,), daemon=True, name=f"confirm-{order_id}"
            ).start()
        elif do_confirm:
            try:
                status = confirm_order(self, order_id, max_wait=10.0, poll_interval=1.0)
                if status == "REJECTED":
                    raise OrderPlacementError(f"Order {order_id} REJECTED after placement")
            except OrderPlacementError:
                raise
            except Exception as conf_exc:
                logger.warning("Order confirmation poll failed (non-fatal): %s", conf_exc)
        return order_id

    def _confirm_async(self, order_id: str) -> None:
        try:
            status = confirm_order(self, order_id, max_wait=10.0, poll_interval=1.0)
            if status == "REJECTED":
                logger.error("MARKET order %s was REJECTED", order_id)
            else:
                logger.debug("MARKET order %s confirmed → %s", order_id, status)
        except Exception as exc:
            logger.warning("Async confirmation failed for %s: %s", order_id, exc)

    def place_sl_limit(
        self,
        *,
        symbol: str,
        qty: int,
        side: str,
        trigger: float,
        limit: float,
        trade_type: str = "MARGIN",
        exchange: str = "NFO",
    ) -> str:
        """Resting Kite SL (trigger + limit). ATO BUY park and SELL cover."""
        return self.place_order(
            symbol=symbol,
            exchange=exchange,
            qty=int(qty),
            price=float(limit),
            trigger_price=float(trigger),
            order_type="STOPLIMIT",
            transaction_type=str(side).upper(),
            trade_type=trade_type,
            confirm=False,
        )

    def place_market_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        trade_type: str = "MARGIN",
        exchange: str = "NFO",
    ) -> str:
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
        self._enforce_live_mode_for_orders()
        kite_type = self._order_type(order_type)
        payload: dict[str, Any] = {
            "order_type": kite_type,
            "quantity": int(qty),
            "price": float(price),
        }
        if kite_type in {"SL", "SL-M"} and trigger_price:
            payload["trigger_price"] = float(trigger_price)
        try:
            self._http.request("PUT", f"/orders/regular/{order_id}", data=payload)
        except KiteAPIError as exc:
            raise OrderPlacementError(f"Modify failed for {order_id}: {exc}") from exc
        logger.info("Zerodha order modified: %s type=%s qty=%d price=%s", order_id, kite_type, qty, price)
        return str(order_id)

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
        import time

        from core.order_pricing import aggressive_limit_price

        self._enforce_live_mode_for_orders()
        side_u = str(side).upper()

        def _quote_limit() -> float:
            quotes = self.get_ltp([symbol])
            ltp = float(quotes.get(symbol) or 0.0)
            if ltp <= 0:
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
            return aggressive_limit_price(ltp, side_u, buffer_pct=buffer_pct, tick=tick_size)

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
                return order_id
            if status_u in {"REJECTED", "CANCELLED", "EXPIRED"}:
                raise OrderPlacementError(f"Aggressive LIMIT {order_id} ended as {status_u}")
            now = time.time()
            if now >= next_chase and status_u in {"PENDING", "TRANSIT", "PART_TRADED", "UNKNOWN"}:
                try:
                    new_px = _quote_limit()
                    if abs(new_px - limit_px) >= tick_size / 2:
                        self.modify_order(order_id, order_type="LIMIT", qty=qty, price=new_px)
                        limit_px = new_px
                except Exception as chase_exc:
                    logger.warning("Aggressive LIMIT chase modify failed for %s: %s", order_id, chase_exc)
                next_chase = now + max(0.5, float(chase_interval_sec))
            time.sleep(0.5)
        try:
            self.cancel_order(order_id)
        except Exception as cancel_exc:
            logger.warning("Aggressive LIMIT cancel after timeout failed for %s: %s", order_id, cancel_exc)
        raise OrderPlacementError(
            f"Aggressive LIMIT {order_id} timed out after {chase_timeout_sec}s (last status={last_status})"
        )

    def get_order_status(self, order_id: str) -> str:
        try:
            data = self._http.request("GET", f"/orders/{order_id}")
        except KiteAPIError as exc:
            raise OrderPlacementError(f"Order status failed: {exc}") from exc
        if isinstance(data, list) and data:
            raw = data[-1].get("status")
        elif isinstance(data, dict):
            raw = data.get("status")
        else:
            raw = str(data)
        return _map_status(str(raw))

    def cancel_order(self, order_id: str) -> str:
        try:
            self._http.request("DELETE", f"/orders/regular/{order_id}", data={})
        except KiteAPIError as exc:
            raise OrderCancelError(f"Cancel failed: {exc}") from exc
        return str(order_id)

    def cancel_all_intraday(self) -> None:
        try:
            book = self._http.request("GET", "/orders")
        except KiteAPIError as exc:
            raise OrderCancelError(f"Cancel-all failed: {exc}") from exc
        for row in book or []:
            status = _map_status(str(row.get("status") or ""))
            if status in _TERMINAL:
                continue
            oid = row.get("order_id")
            if oid:
                try:
                    self.cancel_order(str(oid))
                except Exception as exc:
                    logger.warning("cancel-all skip %s: %s", oid, exc)

    @retry(max_attempts=2, base_delay=1.0)
    def get_positions(self) -> pd.DataFrame:
        try:
            data = self._http.request("GET", "/portfolio/positions")
        except KiteAPIError as exc:
            raise PositionError(f"Positions fetch failed: {exc}") from exc
        update_day_pnl_from_positions(data)
        net = (data or {}).get("net") if isinstance(data, dict) else data
        return _positions_df(list(net or []))

    def get_live_pnl(self) -> float:
        # Prefer cache from last get_positions (no extra REST).
        cached = cached_day_pnl()
        if cached is not None:
            return float(cached)
        df = self.get_positions()
        if df is None or df.empty:
            return 0.0
        try:
            return float(df["pnl"].sum())
        except Exception:
            return 0.0

    def get_balance(self) -> float:
        try:
            data = self._http.request("GET", "/user/margins")
            equity = (data or {}).get("equity") or {}
            available = equity.get("available") or {}
            return float(available.get("live_balance") or available.get("cash") or 0)
        except KiteAPIError as exc:
            raise BrokerConnectionError(f"Balance fetch failed: {exc}") from exc

    def get_orderbook(self) -> pd.DataFrame:
        try:
            data = self._http.request("GET", "/orders")
            return pd.DataFrame(list(data or []))
        except KiteAPIError as exc:
            raise BrokerConnectionError(f"Orderbook failed: {exc}") from exc

    def get_holdings(self) -> pd.DataFrame:
        try:
            data = self._http.request("GET", "/portfolio/holdings")
            return pd.DataFrame(list(data or []))
        except KiteAPIError as exc:
            raise BrokerConnectionError(f"Holdings failed: {exc}") from exc

    def get_lot_size(self, symbol: str) -> int:
        from core.position_scope import resolve_nifty_lot_size

        broker_lot: int | None = None
        try:
            rows = load_nifty_options(self._http)
            want = self._symbol(symbol)
            for row in rows:
                if row.tradingsymbol == want and row.lot_size > 0:
                    broker_lot = row.lot_size
                    break
        except Exception:
            pass
        return resolve_nifty_lot_size(broker_lot_size=broker_lot)

    def close_position(
        self,
        symbol: str,
        qty: int,
        side: str,
        trade_type: str = "MARGIN",
        exchange: str = "NFO",
    ) -> str:
        return self.place_market_order(
            symbol=symbol, qty=abs(qty), side=side, trade_type=trade_type, exchange=exchange
        )

    def close_all_positions(self, trade_type: str = "MARGIN") -> list[str]:
        positions = self.get_positions()
        if positions is None or positions.empty:
            return []
        order_ids: list[str] = []
        for _, row in positions.iterrows():
            symbol = row.get("tradingSymbol") or row.get("tradingsymbol", "")
            net_qty = int(row.get("netQty", 0) or 0)
            if net_qty == 0 or not symbol:
                continue
            side = "SELL" if net_qty > 0 else "BUY"
            try:
                order_ids.append(
                    self.close_position(symbol=symbol, qty=abs(net_qty), side=side, trade_type=trade_type)
                )
            except OrderPlacementError as exc:
                logger.error("Failed to close %s: %s", symbol, exc)
        return order_ids

    def send_alert(self, message: str, chat_id: str, bot_token: str) -> None:
        del message, chat_id, bot_token

    def circuit_status(self) -> dict:
        return self._circuit.status()

    def __repr__(self) -> str:
        return f"ZerodhaBroker(user={self._client_code!r})"

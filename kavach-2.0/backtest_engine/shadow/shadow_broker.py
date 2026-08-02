"""Virtual broker for UAT — Sensibull book + simulated orders (P1)."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.batman_mode import get_mode
from core.batman_mode import workspace_root as _workspace_root
from core.uat_positions import load_positions_fixture

logger = logging.getLogger("backtest_engine.shadow_broker")

_NIFTY_LOT = 65


class ShadowBroker:
    """Drop-in for BatmanBroker during UAT mode."""

    def __init__(self, client_code: str, access_token: str, *, root: Path):
        self._client_code = client_code
        self._access_token = access_token
        self._root = root
        self._auth_time = datetime.now()
        self._core_positions_df = pd.DataFrame()
        self._positions_df = pd.DataFrame()
        self._orders: list[dict[str, Any]] = []
        self._load_order_ledger()
        self._reload_positions_from_fixture()

    @classmethod
    def connect_with_token(
        cls,
        client_code: str,
        access_token: str,
        *,
        workspace_root: Path | None = None,
    ) -> ShadowBroker:
        root = workspace_root or _workspace_root()
        mode = get_mode(root)
        if mode != "uat":
            raise RuntimeError(
                f"ShadowBroker is UAT-only (current mode={mode!r}). "
                "Use config/batman_mode.json prod + BatmanBroker for live trading."
            )
        return cls(client_code, access_token, root=root)

    @property
    def token_age_hours(self) -> float:
        return (datetime.now() - self._auth_time).total_seconds() / 3600

    def set_runtime_mode_provider(self, provider) -> None:
        del provider

    def _load_order_ledger(self) -> None:
        from backtest_engine.shadow.ledger_store import load_orders, seed_from_uat_state

        self._orders = load_orders(self._root)
        if not self._orders:
            self._orders = seed_from_uat_state(self._root)
        if self._orders:
            logger.info(
                "ShadowBroker restored %d virtual orders from ledger",
                len(self._orders),
            )

    def _persist_order_ledger(self) -> None:
        from backtest_engine.shadow.ledger_store import save_orders

        save_orders(self._root, self._orders)

    def clear_virtual_book(self) -> None:
        """Drop simulated ATO fills (Batman Complete / fresh register)."""
        from backtest_engine.shadow.ledger_store import clear_ledger

        self._orders = []
        clear_ledger(self._root)
        self._reload_positions_from_fixture()
        logger.info("ShadowBroker virtual book cleared")

    def _reload_positions_from_fixture(self) -> None:
        from backtest_engine.resolver.instrument_master import (
            load_instrument_master,
            resolve_fixture_trading_expiry,
            resolve_nifty_option,
        )
        from core.batman_mode import uat_screenshot_dir
        from core.nifty_option_expiry import fixture_expiry_date

        fixture = load_positions_fixture(self._root)
        fixture_exp = fixture_expiry_date(fixture)
        master = load_instrument_master()
        exp_date, rolled = resolve_fixture_trading_expiry(
            fixture_exp,
            fixture["legs"],
            master=master,
        )
        if rolled:
            from backtest_engine.shadow.ledger_store import clear_ledger

            self._orders = []
            clear_ledger(self._root)
            logger.info(
                "ShadowBroker rolled UAT fixture expiry %s → %s; cleared stale virtual ledger",
                fixture_exp.isoformat(),
                exp_date.isoformat(),
            )
        rows: list[dict[str, Any]] = []
        for leg in fixture["legs"]:
            inst = resolve_nifty_option(
                strike=int(leg["strike"]),
                option_type=str(leg["type"]),
                expiry_date=exp_date,
                master=master,
            )
            lots = int(leg["lots"])
            qty = lots * _NIFTY_LOT
            if str(leg.get("side", "BUY")).upper() != "BUY":
                qty = -qty
            rows.append(inst.to_broker_row(net_qty=qty, avg_price=float(leg.get("avg_price", 0))))

        from backtest_engine.shadow.position_book import rebuild_positions
        from core.uat_position_enrich import enrich_positions_dataframe, format_expiry_display

        core = enrich_positions_dataframe(pd.DataFrame(rows), fixture)
        exp_label = format_expiry_display(fixture.get("expiry_date") or fixture.get("expiry_label"))
        if exp_label and not core.empty:
            core["expiryLabel"] = exp_label
        self._core_positions_df = core
        self._positions_df = rebuild_positions(
            self._core_positions_df, self._orders, expiry_date=exp_date
        )
        logger.info(
            "ShadowBroker loaded %d core legs + %d virtual fills → %d rows from %s",
            len(rows),
            sum(1 for o in self._orders if o.get("status") == "TRADED"),
            len(self._positions_df),
            uat_screenshot_dir(self._root) / "positions.json",
        )

    def refresh_fixture_positions(self) -> None:
        """Reload Sensibull core book; keeps TRADED virtual orders (ATO legs)."""
        self._reload_positions_from_fixture()

    def get_positions(self) -> pd.DataFrame:
        """Fast book read — live enrich happens in KAVACH cmd_positions only."""
        from core.uat_position_enrich import enrich_positions_dataframe

        fixture = load_positions_fixture(self._root)
        return enrich_positions_dataframe(self._positions_df.copy(), fixture)

    def get_nifty_option_ltps(
        self,
        legs: list[tuple[int, str]],
        *,
        expiry_date,
    ) -> dict[tuple[int, str], float]:
        # UAT replay: serve protect premiums from option_ltp log at replay time.
        try:
            from core.option_ltp_uat_lookup import (
                lookup_protect_premium,
                replay_market_time_from_cache,
            )

            replay_t = replay_market_time_from_cache(self._root)
            if replay_t is not None:
                out: dict[tuple[int, str], float] = {}
                for strike, opt in legs:
                    sym = f"NIFTY-XXX-{int(strike)}-{str(opt).upper()}"
                    # role_for_protect_symbol only needs -CE/-PE suffix
                    px = lookup_protect_premium(
                        symbol=sym,
                        root=self._root,
                        replay_market_time=replay_t,
                        day=replay_t,
                    )
                    if px is not None and px > 0:
                        out[(int(strike), str(opt).upper())] = float(px)
                if out:
                    return out
        except Exception:
            pass

        from core.dhan_rest_quote import cached_rest_quote_client

        client = cached_rest_quote_client(self)
        if client is None:
            return {}
        return client.get_nifty_option_ltps(legs, expiry_date=expiry_date)

    def get_ltp(self, names: list[str]) -> dict[str, float]:
        from core.nifty_ltp_feed import resolve_nifty_ltp_from_cache

        spot = float(resolve_nifty_ltp_from_cache(max_age_seconds=30))
        return {n: spot for n in names}

    def get_nifty_ltp(self) -> float:
        return self.get_ltp(["NIFTY"])["NIFTY"]

    def get_lot_size(self, underlying: str = "NIFTY") -> int:
        return _NIFTY_LOT

    def place_order(self, symbol: str, **kw) -> str:
        from backtest_engine.shadow.order_ledger import place_virtual_order

        return place_virtual_order(self, symbol, **kw)

    def place_market_order(
        self, symbol: str, qty: int, side: str, trade_type: str = "MARGIN", exchange: str = "NFO"
    ):
        return self.place_order(
            symbol=symbol,
            qty=qty,
            transaction_type=side,
            order_type="MARKET",
            trade_type=trade_type,
            exchange=exchange,
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
        for o in self._orders:
            if str(o.get("order_id")) == str(order_id):
                o["order_type"] = order_type
                o["qty"] = qty
                o["price"] = price
                o["trigger_price"] = trigger_price
                break
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
        """UAT: fill immediately like MARKET; record LIMIT price for audit."""
        from core.order_pricing import aggressive_limit_price

        del chase_timeout_sec, chase_interval_sec  # unused — shadow fills instantly
        # Prefer live option premium when REST quotes are available; else synthetic.
        ltp = 0.0
        try:
            from backtest_engine.shadow.order_ledger import _resolve_shadow_fill_price

            ltp = float(_resolve_shadow_fill_price(self, symbol) or 0.0)
        except Exception:
            ltp = 0.0
        if ltp <= 0:
            quotes = self.get_ltp([symbol])
            raw = quotes.get(symbol)
            # Shadow get_ltp returns NIFTY spot for unknown names — ignore huge values.
            try:
                candidate = float(raw or 0.0)
            except (TypeError, ValueError):
                candidate = 0.0
            ltp = candidate if 0 < candidate < 5000 else 50.0
        limit_px = aggressive_limit_price(
            ltp, side, buffer_pct=buffer_pct, tick=tick_size
        )
        # Immediate fill (MARKET path) so ATO book checks do not race the
        # 0.35s LIMIT delay thread; price is kept for audit.
        return self.place_order(
            symbol=symbol,
            qty=qty,
            transaction_type=side,
            order_type="MARKET",
            price=limit_px,
            trade_type=trade_type,
            exchange=exchange,
            aggressive_limit=True,
            limit_buffer_pct=buffer_pct,
        )

    def get_order_status(self, order_id: str) -> str:
        from backtest_engine.shadow.order_ledger import get_virtual_order_status

        return get_virtual_order_status(self, order_id)

    def get_orderbook(self) -> pd.DataFrame:
        """Return virtual order book for SARANSH / UAT reporting."""
        rows: list[dict[str, Any]] = []
        for o in self._orders:
            rows.append(
                {
                    "order_id": o.get("order_id"),
                    "tradingSymbol": o.get("symbol"),
                    "symbol": o.get("symbol"),
                    "transactionType": o.get("side") or o.get("transaction_type"),
                    "quantity": o.get("qty"),
                    "orderStatus": o.get("status"),
                    "order_time": o.get("order_time") or o.get("timestamp") or "",
                    "timestamp": o.get("timestamp") or o.get("order_time") or "",
                    "avg_price": o.get("avg_price"),
                }
            )
        return pd.DataFrame(rows)

    def cancel_order(self, order_id: str) -> str:
        return "CANCELLED"

    def cancel_all_intraday(self) -> None:
        pass

    def get_live_pnl(self) -> float:
        return 0.0

    def get_balance(self) -> float:
        return 0.0

    def atm_strike(self, underlying: str = "NIFTY", expiry: int = 0):
        spot = int(round(self.get_nifty_ltp() / 50) * 50)
        return f"NIFTY {spot} CE", f"NIFTY {spot} PE", spot

    def otm_strike(self, underlying: str = "NIFTY", expiry: int = 0, otm_count: int = 6):
        spot = int(round(self.get_nifty_ltp() / 50) * 50)
        ce = spot + otm_count * 50
        pe = spot - otm_count * 50
        return f"NIFTY {ce} CE", f"NIFTY {pe} PE", ce, pe

from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path
from typing import Any, cast

from core import utils
from core.event_bus import Event
from core.module_base import ModuleBase

logger = logging.getLogger(__name__)

_HANDOFF_PATH = Path("data/analytics/hedge_box/prabhat_mukti_handoff.csv")
_REQUEST_TIMEOUT_SECONDS = 120
_BUY_ACTIONS = {
    "standard_break_even",
    "green_inside",
    "orange_inside",
    "blue_inside",
    "yellow_inside",
    "breach_protect",
}


@dataclass(frozen=True)
class SidePlan:
    side: str
    state: str
    action: str
    strike: int | None
    symbol: str | None
    quantity: int
    break_even: int | None
    option_ltp: float | None


class Ratripal(ModuleBase):
    name = "ratripal"

    def _run(self) -> None:
        cfg = self.config.section("hedge_box")
        if not cfg.get("enabled", False):
            if self._sleep(60):
                return
            return

        check_time = time.fromisoformat(str(cfg.get("check_time_ist", "15:15")))

        while not self._stop_event.is_set():
            try:
                self._tick(check_time)
            except Exception as exc:
                self.log.error("RATRIPAL tick failed: %s", exc)
            if self._sleep(15):
                return

    def _tick(self, check_time: time) -> None:
        if not self.state.get("deployment.confirmed", False):
            return
        if self.state.get("deployment.batman_complete", False):
            return
        if self.state.get("algo.paused", False):
            return
        if not self.state.get("modules.ratripal.enabled", False):
            return
        if not utils.is_trading_day():
            return

        now = utils.now_ist()
        today = now.date()
        if self.state.get("ratripal.last_run_date") == today.isoformat():
            return
        if now.time() < check_time:
            return

        deployment = self._load_deployment()
        if deployment is None:
            return

        dte = self._calculate_dte(deployment, today)
        if dte <= 0:
            self.state.set("ratripal.last_run_date", today.isoformat())
            return

        spot = float(self.broker.get_nifty_ltp())
        plans = self._build_plans(deployment, spot, dte)
        eligible = [plan for plan in plans if self._is_buy_candidate(plan)]
        if not eligible:
            self.state.set("ratripal.last_run_date", today.isoformat())
            return

        request_id = f"{today.isoformat()}::{int(now.timestamp())}"
        response = self._request_confirmation(request_id, eligible, dte, spot)
        if response == "deny":
            self.state.set("ratripal.last_run_date", today.isoformat())
            self.state.set("ratripal.last_decision", "denied")
            return

        for plan in eligible:
            if not self._execute_plan(plan, deployment, dte, spot, request_id):
                self.state.set("ratripal.last_run_date", today.isoformat())
                return

        self.state.set("ratripal.last_run_date", today.isoformat())
        self.state.set("ratripal.last_decision", response or "timeout")

    def _load_deployment(self) -> dict[str, Any] | None:
        deployment_path = self.state.get("deployment.file")
        if not deployment_path:
            return None
        path = Path(str(deployment_path))
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as fh:
            return cast(dict[str, Any], json.load(fh))

    def _calculate_dte(self, deployment: dict[str, Any], today: date) -> int:
        calendar = deployment.get("calendar", {})
        effective = calendar.get("effective_working_days") or []
        if effective:
            days = sorted(date.fromisoformat(d) for d in effective)
            future_days = [d for d in days if today < d]
            return len(future_days)

        expiry_raw = calendar.get("expiry_date")
        if expiry_raw:
            expiry = date.fromisoformat(expiry_raw)
            dte = 0
            cursor = today
            while cursor < expiry:
                cursor = utils.next_trading_day(cursor)
                dte += 1
            return dte

        expiry = utils.current_week_expiry(utils.day_name_to_weekday("Tuesday"), today)
        dte = 0
        cursor = today
        while cursor < expiry:
            cursor = utils.next_trading_day(cursor)
            dte += 1
        return dte

    def _build_plans(self, deployment: dict[str, Any], spot: float, dte: int) -> list[SidePlan]:
        positions = deployment.get("positions", {})
        break_even = deployment.get("risk", {}).get("break_even", {})
        ce_short = int(positions.get("ce_sell", {}).get("strike", 0) or 0)
        pe_short = int(positions.get("pe_sell", {}).get("strike", 0) or 0)
        box_width = int(self.config.get("hedge_box.box_width_points", 75))
        strike_step = int(self.config.get("hedge_box.strike_step_points", 50))

        ce_state = self._classify_side_state("CE", spot, ce_short, box_width, dte)
        pe_state = self._classify_side_state("PE", spot, pe_short, box_width, dte)

        return [
            self._plan_for_side(
                side="CE",
                side_state=ce_state,
                break_even=break_even.get("ce"),
                short_strike=ce_short,
                sell_symbol=str(positions.get("ce_sell", {}).get("symbol", "")),
                buy_qty=abs(int(positions.get("ce_buy", {}).get("qty", 0) or 0)),
                sell_qty=abs(int(positions.get("ce_sell", {}).get("qty", 0) or 0)),
                ato_active=bool(self.state.get("ato.ce_triggered", False)),
                strike_step=strike_step,
            ),
            self._plan_for_side(
                side="PE",
                side_state=pe_state,
                break_even=break_even.get("pe"),
                short_strike=pe_short,
                sell_symbol=str(positions.get("pe_sell", {}).get("symbol", "")),
                buy_qty=abs(int(positions.get("pe_buy", {}).get("qty", 0) or 0)),
                sell_qty=abs(int(positions.get("pe_sell", {}).get("qty", 0) or 0)),
                ato_active=bool(self.state.get("ato.pe_triggered", False)),
                strike_step=strike_step,
            ),
        ]

    def _classify_side_state(
        self,
        side: str,
        spot: float,
        short_strike: int,
        box_width: int,
        dte: int,
    ) -> str:
        active_colors = self._color_order_for_dte(dte)
        if side == "CE":
            if spot >= short_strike:
                return "Breach"
            for i, color in enumerate(active_colors):
                upper = short_strike - i * box_width
                lower = short_strike - (i + 1) * box_width
                if lower <= spot < upper:
                    return color
            return "White"

        if spot <= short_strike:
            return "Breach"
        for i, color in enumerate(active_colors):
            lower = short_strike + i * box_width
            upper = short_strike + (i + 1) * box_width
            if lower < spot <= upper:
                return color
        return "White"

    def _plan_for_side(
        self,
        *,
        side: str,
        side_state: str,
        break_even: int | None,
        short_strike: int,
        sell_symbol: str,
        buy_qty: int,
        sell_qty: int,
        ato_active: bool,
        strike_step: int,
    ) -> SidePlan:
        quantity = buy_qty or max(0, sell_qty // 2)
        if break_even is None:
            return SidePlan(
                side, side_state, "skip_missing_break_even", None, None, quantity, None, None
            )

        if side_state == "Breach" and ato_active:
            return SidePlan(
                side, side_state, "keep_engaged_ato", None, None, quantity, int(break_even), None
            )

        if side_state == "Breach":
            strike = short_strike + strike_step if side == "CE" else short_strike - strike_step
            symbol = self._build_option_symbol(sell_symbol, strike, side)
            return SidePlan(
                side,
                side_state,
                "breach_protect",
                strike,
                symbol,
                quantity,
                int(break_even),
                self._get_option_ltp(symbol),
            )

        steps = self._inside_steps(side_state)
        if steps is None:
            strike = self._round_to_strike(float(break_even), strike_step)
            symbol = self._build_option_symbol(sell_symbol, strike, side)
            return SidePlan(
                side,
                side_state,
                "standard_break_even",
                strike,
                symbol,
                quantity,
                int(break_even),
                self._get_option_ltp(symbol),
            )

        if side == "CE":
            raw = int(break_even) - steps * strike_step
            strike = max(self._round_to_strike(raw, strike_step), short_strike + strike_step)
        else:
            raw = int(break_even) + steps * strike_step
            strike = min(self._round_to_strike(raw, strike_step), short_strike - strike_step)

        symbol = self._build_option_symbol(sell_symbol, strike, side)
        return SidePlan(
            side,
            side_state,
            f"{side_state.lower()}_inside",
            strike,
            symbol,
            quantity,
            int(break_even),
            self._get_option_ltp(symbol),
        )

    def _request_confirmation(
        self,
        request_id: str,
        eligible: list[SidePlan],
        dte: int,
        spot: float,
    ) -> str | None:
        self.state.set("ratripal.pending.request_id", request_id, save=False)
        self.state.set("ratripal.pending.response", None, save=False)
        self.state.set("ratripal.pending.sent_at", utils.now_ist().isoformat(), save=False)
        self.events.publish(
            Event.HEDGE_BOX_CONFIRMATION_REQUEST,
            {
                "request_id": request_id,
                "spot": spot,
                "dte": dte,
                "timeout_seconds": _REQUEST_TIMEOUT_SECONDS,
                "sides": [
                    {
                        "side": plan.side,
                        "zone": plan.state,
                        "action": plan.action,
                        "strike": plan.strike,
                        "symbol": plan.symbol,
                        "qty": plan.quantity,
                        "break_even": plan.break_even,
                        "option_ltp": plan.option_ltp,
                    }
                    for plan in eligible
                ],
            },
        )

        waited = 0
        while waited < _REQUEST_TIMEOUT_SECONDS and not self._stop_event.is_set():
            if self.state.get("ratripal.pending.request_id") != request_id:
                break
            response = self.state.get("ratripal.pending.response")
            if response in {"confirm", "deny"}:
                self._clear_pending_request(request_id)
                return str(response)
            if self._sleep(2):
                break
            waited += 2

        self._clear_pending_request(request_id)
        return None

    def _execute_plan(
        self,
        plan: SidePlan,
        deployment: dict[str, Any],
        dte: int,
        spot: float,
        request_id: str,
    ) -> bool:
        if not plan.symbol or not plan.strike or plan.quantity <= 0:
            return True

        try:
            order_id = self.broker.place_market_order(
                symbol=plan.symbol,
                qty=plan.quantity,
                side="BUY",
                trade_type=self.config.get("strategy.product_type", "MARGIN"),
            )
        except Exception as exc:
            self._publish_execution_failure(
                scenario="hedge_box_execution_failure",
                title=f"RATRIPAL failed to place {plan.side} Hedge Box buy",
                error_message=str(exc),
                next_action="Check broker order book and place the hedge manually if required.",
            )
            return False

        if not self._verify_order(order_id):
            self._publish_execution_failure(
                scenario="hedge_box_verification_failure",
                title=f"RATRIPAL could not verify {plan.side} Hedge Box buy",
                error_message=f"Order {order_id} did not confirm as TRADED.",
                next_action="Check broker order book/positions immediately and confirm whether the hedge was filled.",
            )
            return False

        self._write_handoff_row(plan, deployment, dte, spot, order_id, request_id)
        self.events.publish(
            Event.HEDGE_BOX_EXECUTED,
            {
                "side": plan.side,
                "zone": plan.state,
                "action": plan.action,
                "strike": plan.strike,
                "symbol": plan.symbol,
                "qty": plan.quantity,
                "order_id": order_id,
                "dte": dte,
                "break_even": plan.break_even,
            },
        )
        return True

    def _verify_order(self, order_id: str) -> bool:
        try:
            status = str(self.broker.get_order_status(order_id)).upper()
            return status == "TRADED"
        except Exception:
            return False

    def _publish_execution_failure(
        self,
        *,
        scenario: str,
        title: str,
        error_message: str,
        next_action: str,
    ) -> None:
        self.events.publish(
            Event.MODULE_ERROR,
            {
                "module": self.name,
                "scenario": scenario,
                "severity": "critical",
                "category": "order",
                "title": title,
                "error_message": error_message,
                "next_action": next_action,
            },
        )

    def _write_handoff_row(
        self,
        plan: SidePlan,
        deployment: dict[str, Any],
        dte: int,
        spot: float,
        order_id: str,
        request_id: str,
    ) -> None:
        _HANDOFF_PATH.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "trade_date",
            "request_id",
            "deployment_file",
            "side",
            "zone",
            "action",
            "symbol",
            "strike",
            "qty",
            "order_id",
            "spot",
            "dte",
            "break_even",
            "status",
        ]
        rows: list[dict[str, Any]] = []
        if _HANDOFF_PATH.exists():
            with open(_HANDOFF_PATH, newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))

        key = (utils.today_ist().isoformat(), plan.side)
        new_row = {
            "trade_date": key[0],
            "request_id": request_id,
            "deployment_file": Path(str(self.state.get("deployment.file", ""))).name,
            "side": plan.side,
            "zone": plan.state,
            "action": plan.action,
            "symbol": plan.symbol,
            "strike": plan.strike,
            "qty": plan.quantity,
            "order_id": order_id,
            "spot": f"{spot:.2f}",
            "dte": dte,
            "break_even": plan.break_even,
            "status": "verified_buy",
        }

        replaced = False
        for index, row in enumerate(rows):
            if (row.get("trade_date"), row.get("side")) == key:
                rows[index] = new_row
                replaced = True
                break
        if not replaced:
            rows.append(new_row)

        with open(_HANDOFF_PATH, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        self.state.set("prabhat_mukti.handoff_file", str(_HANDOFF_PATH), save=False)

    def _is_buy_candidate(self, plan: SidePlan) -> bool:
        if plan.action not in _BUY_ACTIONS or not plan.symbol:
            return False
        return not self._has_existing_long_position(plan.symbol, plan.quantity)

    def _has_existing_long_position(self, symbol: str, qty: int) -> bool:
        try:
            positions = self.broker.get_positions()
        except Exception:
            return False
        if positions is None or positions.empty:
            return False
        for _, row in positions.iterrows():
            row_symbol = str(row.get("tradingSymbol") or row.get("tradingsymbol") or "")
            if row_symbol != symbol:
                continue
            net_qty = int(row.get("netQty", 0) or row.get("buyQty", 0) - row.get("sellQty", 0))
            if net_qty >= qty:
                return True
        return False

    def _clear_pending_request(self, request_id: str) -> None:
        if self.state.get("ratripal.pending.request_id") != request_id:
            return
        self.state.set("ratripal.pending.request_id", None, save=False)
        self.state.set("ratripal.pending.response", None, save=False)
        self.state.set("ratripal.pending.sent_at", None, save=False)

    def _get_option_ltp(self, symbol: str | None) -> float | None:
        if not symbol:
            return None
        try:
            prices = self.broker.get_ltp([symbol])
            value = prices.get(symbol)
            return None if value is None else float(value)
        except Exception:
            return None

    @staticmethod
    def _inside_steps(state: str) -> int | None:
        mapping = {
            "Green": 1,
            "Orange": 2,
            "Blue": 3,
            "Yellow": 4,
        }
        return mapping.get(state)

    @staticmethod
    def _color_order_for_dte(dte: int) -> list[str]:
        if dte >= 4:
            return ["Green"]
        if dte == 3:
            return ["Orange", "Green"]
        if dte == 2:
            return ["Blue", "Orange", "Green"]
        if dte == 1:
            return ["Yellow", "Blue", "Orange", "Green"]
        return []

    @staticmethod
    def _round_to_strike(value: float, step: int) -> int:
        if step != 50:
            lower = int(value // step) * step
            upper = lower + step
            return lower if value - lower < upper - value else upper
        base_100 = int(value // 100) * 100
        offset = value - base_100
        if offset < 25:
            return base_100
        if offset < 75:
            return base_100 + 50
        return base_100 + 100

    @staticmethod
    def _build_option_symbol(sell_symbol: str, strike: int, side: str) -> str | None:
        match = re.match(r"^([A-Z]+\d{2}[A-Z]{3})\d+(CE|PE)$", sell_symbol)
        if not match:
            return None
        return f"{match.group(1)}{strike}{side}"

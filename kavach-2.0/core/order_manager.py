"""Order Manager — backend punch for Kavach ATO (no Telegram Place Order bot).

When ATO engages/exits, call ``punch_ato`` (BUY protect / SELL exit).
The Place Order Telegram wizard is a *test harness only* and must NOT appear
in the master Kavach flow — no buttons, no slippage questions.

Modes:
  - ``paper``: Place Order ``BackendOrderWorkflow.for_paper`` (FakeBroker fills)
  - ``live``: reserved — uses Place Order ExecutionEngine with a real broker
    (not enabled until explicitly configured)
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("batman.order_manager")

try:
    from core.money_audit import audit, audit_span, new_correlation_id
except Exception:  # pragma: no cover
    def audit(*_a, **_k):  # type: ignore
        return None

    def new_correlation_id(prefix="c"):  # type: ignore
        return prefix

    from contextlib import contextmanager

    @contextmanager
    def audit_span(event, **fields):  # type: ignore
        yield dict(fields)

OrderMode = Literal["paper", "live"]

_PLACE_ORDER_ROOTS = (
    Path("/home/ubuntu/BlitzBot/GO"),
    Path("/home/ubuntu/GoBot/GO"),
    Path("/home/ubuntu/place-order-bot"),
    Path.home() / "place-order-bot",
)


def _ensure_place_order_on_path() -> Path | None:
    for root in _PLACE_ORDER_ROOTS:
        pkg = root / "place_order_bot"
        if pkg.is_dir():
            root_s = str(root)
            if root_s not in sys.path:
                sys.path.insert(0, root_s)
            return root
    return None


@dataclass
class OrderManager:
    """Thin facade: strategy intent → paper book / Place Order engine."""

    mode: OrderMode = "paper"
    ledger_dir: Path | None = None
    default_ltp: float = 100.0
    live_broker: Any = None

    def __post_init__(self) -> None:
        self.mode = "paper" if str(self.mode).lower() != "live" else "live"
        if self.ledger_dir is None:
            try:
                from core.batman_mode import data_root

                self.ledger_dir = data_root() / "order_manager"
            except Exception:
                self.ledger_dir = Path("data") / "order_manager"
        self.ledger_dir = Path(self.ledger_dir)
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self._paper_wf: Any = None
        self.last_result: Any = None
        self._live_wf: Any = None

    @property
    def is_paper(self) -> bool:
        return self.mode == "paper"

    def _paper_workflow(self) -> Any:
        if self._paper_wf is not None:
            return self._paper_wf
        root = _ensure_place_order_on_path()
        if root is None:
            raise RuntimeError(
                "place-order-bot not found — expected /home/ubuntu/place-order-bot "
                "for BackendOrderWorkflow"
            )
        from place_order_bot.backend_workflow import BackendOrderWorkflow

        self._paper_wf = BackendOrderWorkflow.for_paper(
            ledger_path=self.ledger_dir / "paper_chase.sqlite3",
            ltp=self.default_ltp,
            fill_mode="full",
        )
        return self._paper_wf

    def _punch_live(
        self,
        *,
        symbol: str,
        qty: int,
        side: str,
        product: str,
        reason: str,
        ltp: float | None,
        bid: float | None,
    ) -> str:
        broker = self.live_broker
        if broker is None:
            raise RuntimeError("OrderManager live mode has no broker")
        try:
            px = float(ltp or 0)
        except (TypeError, ValueError):
            px = 0.0
        if px <= 0:
            raise RuntimeError(f"ATO live punch needs option LTP for {symbol}")
        from core.ato_exec import place_buy_resting, place_sell_sl_limit

        if side == "BUY":
            out = place_buy_resting(
                broker, symbol=symbol, qty=qty, ltp=px, product=product
            )
        else:
            out = place_sell_sl_limit(
                broker, symbol=symbol, qty=qty, ltp=px, product=product
            )
        oid = str(out.get("order_id") or "")
        self.last_result = out
        logger.info(
            "OrderManager LIVE punch symbol=%s side=%s qty=%s ltp=%.2f id=%s reason=%s",
            symbol,
            side,
            qty,
            px,
            oid,
            reason,
        )
        return oid

    def punch_ato(
        self,
        *,
        symbol: str,
        qty: int,
        side: str,
        product: str = "MARGIN",
        security_id: str | None = None,
        reason: str = "ato_protect",
        ltp: float | None = None,
        bid: float | None = None,
    ) -> str:
        """Punch immediately when ATO engages. Returns broker/paper order id string."""
        side_u = str(side).strip().upper()
        if side_u in {"B", "BUY"}:
            side_u = "BUY"
        elif side_u in {"S", "SELL"}:
            side_u = "SELL"
        else:
            raise ValueError(f"unsupported side {side!r}")

        sec = str(security_id or symbol).strip()
        if self.mode == "live":
            return self._punch_live(
                symbol=symbol,
                qty=int(qty),
                side=side_u,
                product=str(product or "MARGIN"),
                reason=str(reason),
                ltp=ltp,
                bid=bid,
            )

        if _ensure_place_order_on_path() is None:
            raise RuntimeError(
                "place-order-bot not found — expected /home/ubuntu/place-order-bot"
            )
        from place_order_bot.backend_workflow import PunchRequest

        try:
            from core.paper_trade_logging import set_trade_lane

            set_trade_lane(self.mode)
        except Exception:
            pass
        corr = new_correlation_id("om")
        with audit_span(
            "order_manager.punch_ato",
            corr=corr,
            mode=self.mode,
            symbol=str(symbol),
            security_id=sec,
            side=side_u,
            qty=int(qty),
            product=str(product or "MARGIN"),
            reason=str(reason),
            ledger=str(self.ledger_dir),
        ) as span:
            logger.debug(
                "OrderManager punch begin mode=%s symbol=%s sec=%s side=%s qty=%s product=%s reason=%s corr=%s",
                self.mode,
                symbol,
                sec,
                side_u,
                qty,
                product,
                reason,
                corr,
            )
            wf = self._paper_workflow()
            result = wf.punch(
                PunchRequest(
                    side=side_u,
                    quantity=int(qty),
                    security_id=sec,
                    trading_symbol=str(symbol),
                    reason=reason,
                    product_type=str(product or "MARGIN"),
                    correlation_id=corr,
                )
            )
            self.last_result = result
            # Prefer last broker order id from attempts; else synthetic paper id
            order_id = ""
            attempt_summaries = []
            for att in reversed(result.attempts or []):
                attempt_summaries.append(
                    {
                        "broker_order_id": getattr(att, "broker_order_id", None),
                        "broker_order_ids": list(getattr(att, "broker_order_ids", None) or [])[:5],
                        "limit_price": getattr(att, "limit_price", None),
                        "filled_qty": getattr(att, "filled_qty", None),
                        "status": str(getattr(att, "status", None) or getattr(att, "state", None) or ""),
                    }
                )
                if getattr(att, "broker_order_id", None):
                    order_id = str(att.broker_order_id)
                    break
                ids = getattr(att, "broker_order_ids", None) or []
                if ids:
                    order_id = str(ids[-1])
                    break
            if not order_id:
                order_id = f"PAPER-{result.intent_id}"
            span["order_id"] = order_id
            span["filled_qty"] = getattr(result, "filled_qty", None)
            span["requested_qty"] = getattr(result, "requested_qty", None)
            span["terminal_state"] = str(getattr(getattr(result, "terminal_state", None), "value", getattr(result, "terminal_state", None)))
            span["intent_id"] = getattr(result, "intent_id", None)
            span["last_limit_price"] = getattr(result, "last_limit_price", None)
            span["attempts"] = attempt_summaries[:10]
            audit(
                "order_manager.punch_ato.result",
                corr=corr,
                mode=self.mode,
                order_id=order_id,
                filled_qty=span["filled_qty"],
                requested_qty=span["requested_qty"],
                terminal_state=span["terminal_state"],
                last_limit_price=span["last_limit_price"],
                attempts=attempt_summaries[:10],
            )
            logger.info(
                "OrderManager PAPER punch symbol=%s side=%s qty=%s filled=%s id=%s state=%s corr=%s",
                symbol,
                side_u,
                qty,
                result.filled_qty,
                order_id,
                span["terminal_state"],
                corr,
            )

            try:
                from core.paper_position_book import record_fill

                book_entry = record_fill(
                    symbol=str(symbol),
                    qty=int(getattr(result, "filled_qty", None) or qty),
                    side=side_u,
                    avg_price=float(getattr(result, "last_limit_price", None) or 0) or None,
                    security_id=sec,
                    source=str(reason),
                    order_id=order_id,
                    correlation_id=corr,
                )
                audit(
                    "order_manager.paper_book.recorded",
                    corr=corr,
                    leg_id=(book_entry or {}).get("leg_id"),
                    symbol=str(symbol),
                    qty=int(getattr(result, "filled_qty", None) or qty),
                    side=side_u,
                    order_id=order_id,
                )
                logger.debug(
                    "paper book recorded leg_id=%s symbol=%s qty=%s corr=%s",
                    (book_entry or {}).get("leg_id"),
                    symbol,
                    getattr(result, "filled_qty", None) or qty,
                    corr,
                )
            except Exception as book_exc:
                logger.warning("paper book record failed: %s", book_exc)
                audit("order_manager.paper_book.error", corr=corr, error=str(book_exc)[:300])
            return order_id


def attach_order_manager(ato_module: Any, order_manager: OrderManager | None) -> None:
    """Attach OM onto an ATOProtection instance (``ato.order_manager = …``)."""
    if order_manager is None:
        return
    ato_module.order_manager = order_manager
    logger.info("OrderManager attached mode=%s", order_manager.mode)
    audit("order_manager.attached", mode=order_manager.mode, ledger=str(order_manager.ledger_dir))

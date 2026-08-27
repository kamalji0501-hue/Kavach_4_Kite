"""Deployment order mode: paper | live.

Paper = full Kavach/ATO logic + live quotes; orders go to OrderManager paper sink
(never the exchange). Live = existing broker order path (ATO without paper OM).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("batman.order_mode")

OrderMode = Literal["paper", "live"]
VALID = frozenset({"paper", "live"})


def normalize_order_mode(raw: Any, *, default: OrderMode = "paper") -> OrderMode:
    mode = str(raw or default).strip().lower()
    if mode not in VALID:
        return default
    return mode  # type: ignore[return-value]


def order_mode_from_state(state: Any, *, default: OrderMode = "paper") -> OrderMode:
    if state is None:
        return default
    try:
        return normalize_order_mode(state.get("order_mode"), default=default)
    except Exception:
        return default


def order_mode_from_deployment(dep: dict[str, Any] | None, *, default: OrderMode = "paper") -> OrderMode:
    if not isinstance(dep, dict):
        return default
    return normalize_order_mode(dep.get("order_mode"), default=default)


def latest_deployment_order_mode(root: Path | None = None, *, default: OrderMode = "paper") -> OrderMode:
    """Read order_mode from newest batman_*.json deployment if present."""
    try:
        from core.batman_mode import deployments_dir, workspace_root

        dep_dir = deployments_dir(root or workspace_root())
    except Exception:
        return default
    if not dep_dir.is_dir():
        return default
    files = sorted(dep_dir.glob("batman_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return default
    try:
        import json

        data = json.loads(files[0].read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("order_mode deploy read failed: %s", exc)
        return default
    return order_mode_from_deployment(data if isinstance(data, dict) else None, default=default)


def configure_ato_order_sink(
    ato_module: Any,
    *,
    order_mode: OrderMode,
    workspace_root: Path | None = None,
    state: Any = None,
) -> str:
    """Attach paper OrderManager or clear it for live (legacy broker path).

    Returns the effective mode applied.
    """
    mode = normalize_order_mode(order_mode)
    try:
        from core.paper_trade_logging import set_trade_lane

        set_trade_lane(mode)
    except Exception:
        pass
    try:
        from core.batman_mode import data_root, workspace_root as ws

        root = workspace_root or ws()
        from core.order_manager import OrderManager, attach_order_manager

        if mode == "paper":
            om = OrderManager(mode="paper", ledger_dir=data_root(root) / "order_manager")
            attach_order_manager(ato_module, om)
            if state is not None:
                try:
                    state.set("order_mode", "paper")
                except Exception:
                    pass
            logger.info("[PAPER TRADE] Order sink PAPER — ATO punches via FakeBroker / paper book")
            try:
                from core.money_audit import audit

                audit(
                    "order_mode.sink.detail",
                    mode="paper",
                    via="order_manager",
                    ledger=str(data_root(root) / "order_manager"),
                    paper_book=str(data_root(root) / "paper_position_book.json"),
                )
            except Exception:
                pass
            return "paper"

        om = OrderManager(
            mode="live",
            ledger_dir=data_root(root) / "order_manager",
            live_broker=getattr(ato_module, "broker", None),
        )
        attach_order_manager(ato_module, om)
        if state is not None:
            try:
                state.set("order_mode", "live")
            except Exception:
                pass
        logger.info("Order sink LIVE — OrderManager ATO resting SL-L + Rescue")
        try:
            from core.money_audit import audit

            audit(
                "order_mode.sink.detail",
                mode="live",
                via="order_manager",
                note="ATO BUY resting trigger+limit; SELL SL-L; Rescue fill/exit",
            )
        except Exception:
            pass
        return "live"
    except Exception as exc:
        logger.warning("configure_ato_order_sink failed: %s", exc)
        return mode
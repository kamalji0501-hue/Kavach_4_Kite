"""Create the broker for the active Batman mode (dev | uat | prod)."""

from __future__ import annotations

import logging
from typing import Any

from core.batman_mode import get_mode, is_uat, orders_blocked, workspace_root
from core.broker import BatmanBroker

logger = logging.getLogger("batman.broker_factory")


def create_broker(client_code: str, access_token: str, root=None) -> Any:
    """Return BatmanBroker or ShadowBroker depending on config mode.

    Contract (enforced by tests/test_mode_isolation.py):
      - uat  → ShadowBroker (virtual orders + screenshot positions)
      - dev  → BatmanBroker with orders blocked
      - prod → BatmanBroker with live Dhan orders
    """
    root = root or workspace_root()
    mode = get_mode(root)

    if mode == "uat":
        from backtest_engine.shadow.shadow_broker import ShadowBroker

        broker = ShadowBroker.connect_with_token(client_code, access_token, workspace_root=root)
        logger.info("Broker factory: UAT ShadowBroker (virtual positions/orders)")
        return broker

    broker = BatmanBroker.connect_with_token(client_code, access_token)
    if orders_blocked(root):
        logger.info("Broker factory: mode=%s — live Dhan read; orders blocked", mode)
    else:
        logger.info("Broker factory: mode=%s — live Dhan broker", mode)
    return broker


def apply_runtime_mode_provider(broker: Any, state) -> None:
    """Wire order gate on real BatmanBroker from mode + legacy state."""
    if not hasattr(broker, "set_runtime_mode_provider"):
        return

    root = workspace_root()

    def _provider() -> str:
        if is_uat(root):
            return "mock"
        if orders_blocked(root):
            return "mock"
        legacy = str(state.get("control.runtime_mode", "live") or "live").strip().lower()
        return legacy if legacy in {"mock", "live"} else "live"

    broker.set_runtime_mode_provider(_provider)

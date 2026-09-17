"""Create the broker for the active Batman mode (dev | uat | prod).
UAT → ShadowBroker. prod/dev → Zerodha Kite REST or Dhan Tradehull."""

from __future__ import annotations

import logging
from typing import Any

from core.batman_mode import get_mode, is_uat, orders_blocked, workspace_root
from core.broker import BatmanBroker

logger = logging.getLogger("batman.broker_factory")


def create_broker(client_code: str, access_token: str, root=None) -> Any:
    """Return ShadowBroker / ZerodhaBroker / BatmanBroker (Dhan).

    Contract (enforced by tests/test_mode_isolation.py):
      - uat  → ShadowBroker (virtual orders + screenshot positions)
      - dev  → selected live adapter with orders blocked
      - prod → selected live adapter (MAIN_ORDER_BROKER=zerodha|dhan)
    """
    root = root or workspace_root()
    mode = get_mode(root)

    if mode == "uat":
        from backtest_engine.shadow.shadow_broker import ShadowBroker

        broker = ShadowBroker.connect_with_token(client_code, access_token, workspace_root=root)
        logger.info("Broker factory: UAT ShadowBroker (virtual positions/orders)")
        return broker

    from core.order_broker_select import dhan_client_and_token, get_main_order_broker

    main = get_main_order_broker(root)
    if main == "dhan":
        cc, tok = dhan_client_and_token(root)
        if (client_code or "").strip():
            cc = client_code.strip()
        if (access_token or "").strip():
            tok = access_token.strip()
        if not tok:
            from core.exceptions import BrokerAuthError

            raise BrokerAuthError(
                "Dhan is the main order broker but no JWT is saved. "
                "Paste a Dhan token on TOKEN, or set DHAN_CLIENT_CODE in dhan.env."
            )
        if not cc:
            from core.exceptions import BrokerAuthError

            raise BrokerAuthError(
                "Dhan is the main order broker but DHAN_CLIENT_CODE is empty "
                "in Credentials/config/dhan.env."
            )
        broker = BatmanBroker.connect_with_token(cc, tok)
        if orders_blocked(root):
            logger.info("Broker factory: mode=%s — Dhan Tradehull read; orders blocked", mode)
        else:
            logger.info("Broker factory: mode=%s — Dhan Tradehull live orders", mode)
        return broker

    from core.zerodha_broker import ZerodhaBroker

    del client_code, access_token
    broker = ZerodhaBroker.connect(root=root)
    if orders_blocked(root):
        logger.info("Broker factory: mode=%s — Zerodha REST read; orders blocked", mode)
    else:
        logger.info("Broker factory: mode=%s — Zerodha REST live broker", mode)
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

"""Resolve a live Kavach broker handle when runtime was started before token save."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("batman.broker_resolve")


def resolve_kavach_broker(*, root=None, runtime_broker: Any | None = None) -> Any | None:
    """Return runtime broker, or connect Zerodha REST from saved credentials."""
    if runtime_broker is not None:
        return runtime_broker
    try:
        from core.batman_mode import is_uat, workspace_root
        from core.broker_factory import create_broker
        from core.zerodha_credentials import load_zerodha_order_creds

        ws = root or workspace_root()
        if is_uat(ws):
            return None
        creds = load_zerodha_order_creds(ws)
        if not creds.ok:
            return None
        broker = create_broker(creds.user_id or "", creds.access_token, ws)
        logger.info("Resolved Zerodha broker for register last4=%s", creds.access_token[-4:])
        return broker
    except Exception as exc:
        logger.warning("resolve_kavach_broker failed: %s", exc)
        return None

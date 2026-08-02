"""Persist ShadowBroker virtual orders across KAVACH restarts (UAT)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from core.batman_mode import shadow_ledger_path, state_path
from core.process_lock import exclusive_file_lock

logger = logging.getLogger("backtest_engine.ledger_store")


def ledger_path(root: Path) -> Path:
    return shadow_ledger_path(root)


def load_orders(root: Path) -> list[dict[str, Any]]:
    path = ledger_path(root)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        orders = payload.get("orders") if isinstance(payload, dict) else payload
        if not isinstance(orders, list):
            return []
        return [dict(o) for o in orders if isinstance(o, dict)]
    except Exception as exc:
        logger.warning("Could not load shadow ledger %s: %s", path, exc)
        return []


def save_orders(root: Path, orders: list[dict[str, Any]]) -> None:
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "orders": orders,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    tmp = path.with_suffix(".tmp")
    try:
        with exclusive_file_lock(path, timeout=5.0):
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, default=str)
            tmp.replace(path)
    except Exception as exc:
        logger.error("Shadow ledger save failed: %s", exc)
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def clear_ledger(root: Path) -> None:
    path = ledger_path(root)
    if path.exists():
        path.unlink(missing_ok=True)
    logger.info("Shadow order ledger cleared")


def seed_from_uat_state(root: Path) -> list[dict[str, Any]]:
    """One-time rebuild of virtual orders from persisted ATO state (pre-ledger sessions)."""
    state_file = state_path(root)
    if not state_file.exists():
        return []

    try:
        with open(state_file, encoding="utf-8") as fh:
            state = json.load(fh)
    except Exception as exc:
        logger.warning("Shadow ledger seed: cannot read state: %s", exc)
        return []

    ato = state.get("ato") if isinstance(state.get("ato"), dict) else {}
    positions = state.get("positions") if isinstance(state.get("positions"), dict) else {}
    orders: list[dict[str, Any]] = []

    def _qty(side: str) -> int:
        leg = positions.get(f"{side}_buy")
        if isinstance(leg, dict):
            try:
                q = int(leg.get("qty") or 0)
                if q:
                    return abs(q)
            except (TypeError, ValueError):
                pass
        return 65

    def _append(oid: Any, symbol: Any, side: str, qty: int) -> None:
        if not oid or not symbol or qty <= 0:
            return
        orders.append(
            {
                "order_id": str(oid),
                "symbol": str(symbol),
                "qty": int(qty),
                "side": side.upper(),
                "status": "TRADED",
            }
        )

    # Only restore *open* protect BUYs. Seeding exit SELLs without a matching BUY
    # (common after a completed cycle: exit_order_id set, order_id cleared) created
    # ghost short protect qty and blocked ATO re-entry forever.
    ce_sym = ato.get("ce_protect_symbol")
    pe_sym = ato.get("pe_protect_symbol")
    if ato.get("ce_ato_active"):
        _append(ato.get("ce_order_id"), ce_sym, "BUY", _qty("ce"))
    if ato.get("pe_ato_active"):
        _append(ato.get("pe_order_id"), pe_sym, "BUY", _qty("pe"))

    if not orders:
        return []

    try:
        save_orders(root, orders)
        logger.info("Shadow ledger seeded %d orders from UAT state", len(orders))
    except Exception as exc:
        logger.warning("Shadow ledger seed save failed: %s", exc)
        return []

    return orders

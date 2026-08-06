"""Internal paper position book for order_mode=paper (no exchange)."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")
_LOCK = threading.RLock()
logger = logging.getLogger("batman.paper_position_book")


def _book_path(root: Path | None = None) -> Path:
    try:
        from core.batman_mode import data_root, workspace_root

        base = data_root(root or workspace_root())
    except Exception:
        base = Path(root or ".") / "data"
    path = Path(base) / "paper_position_book.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(_IST).isoformat(timespec="seconds")


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "legs": [], "updated_at": None}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("legs"), list):
            return raw
    except Exception as exc:
        logger.warning("paper book load failed: %s", exc)
    return {"schema_version": 1, "legs": [], "updated_at": None}


def _save(path: Path, data: dict[str, Any]) -> None:
    data["updated_at"] = _now()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def record_fill(
    *,
    symbol: str,
    qty: int,
    side: str,
    avg_price: float | None = None,
    security_id: str | None = None,
    source: str = "ato_breach",
    order_id: str | None = None,
    deployment_id: str | None = None,
    correlation_id: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Append or net a paper leg. BUY opens/adds long; SELL reduces/closes."""
    path = _book_path(root)
    side_u = str(side).upper()
    if side_u in {"B", "BUY"}:
        side_u = "BUY"
    elif side_u in {"S", "SELL"}:
        side_u = "SELL"
    else:
        raise ValueError(f"bad side {side!r}")

    with _LOCK:
        data = _load(path)
        legs: list[dict[str, Any]] = list(data.get("legs") or [])
        open_legs = [L for L in legs if not L.get("closed_at")]
        matching = [
            L
            for L in open_legs
            if str(L.get("trading_symbol") or "") == str(symbol)
            and str(L.get("security_id") or "") == str(security_id or L.get("security_id") or "")
        ]
        signed = int(qty) if side_u == "BUY" else -int(qty)
        if matching and side_u == "SELL":
            leg = matching[0]
            prev = int(leg.get("qty") or 0)
            new_qty = prev - abs(int(qty))
            if new_qty <= 0:
                leg["qty"] = 0
                leg["closed_at"] = _now()
                leg["close_order_id"] = order_id
                leg["close_source"] = source
            else:
                leg["qty"] = new_qty
            leg["last_event"] = source
            leg["updated_at"] = _now()
            entry = leg
        else:
            entry = {
                "leg_id": f"paper-{len(legs)+1}-{int(datetime.now().timestamp())}",
                "role": "ato_long" if side_u == "BUY" else "ato_exit",
                "security_id": str(security_id or symbol),
                "trading_symbol": str(symbol),
                "side": side_u,
                "qty": abs(int(qty)),
                "avg_price": float(avg_price) if avg_price is not None else None,
                "opened_at": _now(),
                "closed_at": None,
                "source": source,
                "order_mode": "paper",
                "order_id": order_id,
                "deployment_id": deployment_id,
                "correlation_id": correlation_id,
                "updated_at": _now(),
                "signed_qty_hint": signed,
            }
            legs.append(entry)
        data["legs"] = legs
        _save(path, data)
        try:
            from core.money_audit import audit

            audit("paper_book.path", path=str(path))
            audit(
                "paper_book.fill",
                symbol=str(symbol),
                side=side_u,
                qty=int(qty),
                order_id=order_id,
                source=source,
                avg_price=avg_price,
            )
        except Exception:
            pass
        return entry


def open_legs(root: Path | None = None) -> list[dict[str, Any]]:
    data = _load(_book_path(root))
    return [L for L in (data.get("legs") or []) if not L.get("closed_at") and int(L.get("qty") or 0) > 0]


def snapshot_text(root: Path | None = None) -> str:
    legs = open_legs(root)
    if not legs:
        return "No open paper legs."
    lines = ["Paper book (bot-executed):"]
    for L in legs:
        px = L.get("avg_price")
        px_s = f" @ {px}" if px is not None else ""
        lines.append(f"- {L.get('side')} {L.get('qty')} x {L.get('trading_symbol')}{px_s} ({L.get('source')})")
    return "\n".join(lines)
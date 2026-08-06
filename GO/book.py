"""GO-owned position book — never writes KAVACH batman_*.json deployments."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from core import utils as _u
from core.batman_mode import data_root, workspace_root

logger = logging.getLogger("batman.go.book")

_LOCK = threading.Lock()


def go_books_dir(root: Path | None = None) -> Path:
    path = data_root(root or workspace_root()) / "go" / "books"
    path.mkdir(parents=True, exist_ok=True)
    return path


def go_active_path(root: Path | None = None) -> Path:
    return go_books_dir(root) / "active.json"


def new_book_id() -> str:
    return _u.now_ist().strftime("go_%Y-%m-%d_%H-%M-%S")


def save_book(book: dict[str, Any], root: Path | None = None) -> Path:
    """Persist book to dated file and update active pointer."""
    root = root or workspace_root()
    book_id = str(book.get("id") or new_book_id())
    book["id"] = book_id
    book["updated_at_ist"] = _u.now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
    path = go_books_dir(root) / f"{book_id}.json"
    with _LOCK:
        path.write_text(json.dumps(book, indent=2), encoding="utf-8")
        go_active_path(root).write_text(
            json.dumps({"id": book_id, "path": str(path)}, indent=2),
            encoding="utf-8",
        )
    logger.info("GO book saved: %s status=%s", path.name, book.get("status"))
    return path


def load_active_book(root: Path | None = None) -> dict[str, Any] | None:
    root = root or workspace_root()
    pointer = go_active_path(root)
    if not pointer.exists():
        return None
    try:
        meta = json.loads(pointer.read_text(encoding="utf-8"))
        path = Path(str(meta.get("path") or ""))
        if not path.is_file():
            path = go_books_dir(root) / f"{meta.get('id')}.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("Failed to load GO active book: %s", exc)
        return None


def clear_active_pointer(root: Path | None = None) -> None:
    pointer = go_active_path(root)
    if pointer.exists():
        pointer.unlink(missing_ok=True)


def make_multileg_book(
    *,
    center_level: float,
    expiry: str,
    base_lots: int,
    lot_size: int,
    legs: list[dict[str, Any]],
    status: str = "open",
) -> dict[str, Any]:
    return {
        "id": new_book_id(),
        "mode": "multileg",
        "status": status,
        "center_level": center_level,
        "expiry": expiry,
        "base_lots": base_lots,
        "lot_size": lot_size,
        "created_at_ist": _u.now_ist().strftime("%Y-%m-%d %H:%M:%S IST"),
        "legs": legs,
        "exit_reason": None,
    }


def make_single_book(
    *,
    option_type: str,
    strike: int,
    symbol: str,
    qty: int,
    expiry: str,
    entry_premium: float | None,
    sl_price: float,
    target_price: float,
    order_id: str | None,
    status: str = "open",
) -> dict[str, Any]:
    return {
        "id": new_book_id(),
        "mode": "single",
        "status": status,
        "option_type": option_type.upper(),
        "strike": int(strike),
        "symbol": symbol,
        "qty": int(qty),
        "expiry": expiry,
        "created_at_ist": _u.now_ist().strftime("%Y-%m-%d %H:%M:%S IST"),
        "entry_premium": entry_premium,
        "sl_price": float(sl_price),
        "target_price": float(target_price),
        "trail_active": False,
        "trail_sl": float(sl_price),
        "trail_target": float(target_price),
        "peak_premium": entry_premium,
        "order_id": order_id,
        "exit_order_id": None,
        "exit_reason": None,
        "legs": [
            {
                "key": "single",
                "side": "BUY",
                "option_type": option_type.upper(),
                "strike": int(strike),
                "qty": int(qty),
                "symbol": symbol,
                "order_id": order_id,
                "status": "filled" if order_id else "pending",
            }
        ],
    }


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")

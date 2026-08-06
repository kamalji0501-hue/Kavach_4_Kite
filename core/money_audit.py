"""Money-critical audit trail — detailed JSONL + helpers; secrets never written.

Real-money debugging: every order, ATO engage, Telegram control action, and
backend punch should leave a structured trail under Logs/.../audit/.

Usage::

    from core.money_audit import audit, audit_span, configure_money_audit

    configure_money_audit(workspace_root, bot_name="kavach")
    audit("order.punch.start", mode="paper", symbol="NIFTY…", qty=65, side="BUY")
    with audit_span("ato.engage", side="CE", spot=24800):
        ...
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")
_LOCK = threading.Lock()
_AUDIT_PATH: Path | None = None
_DETAIL_PATH: Path | None = None
_PAPER_AUDIT_PATH: Path | None = None
_CORRELATION: ContextVar[str | None] = ContextVar("money_audit_corr", default=None)
_ROBOT: ContextVar[str | None] = ContextVar("money_audit_robot", default=None)

logger = logging.getLogger("batman.money_audit")

# Keys / substrings that must never appear in cleartext in audit files.
_SECRET_KEY_RE = re.compile(
    r"(?i)(token|access[_-]?token|refresh[_-]?token|jwt|password|passwd|secret|"
    r"api[_-]?key|client[_-]?secret|authorization|auth[_-]?header|bearer|"
    r"totp|otp|pin|private[_-]?key|pem|credential|dhan[_-]?access|"
    r"telegram[_-]?bot[_-]?token|bot[_-]?token)"
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(Bearer\s+[A-Za-z0-9\-._~+/]+=*|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r"\.[A-Za-z0-9_-]{10,}|\d{6}\b)"
)

_MAX_STR = 2000
_MAX_LIST = 50
_MAX_DEPTH = 6


def set_audit_robot(robot: str | None) -> None:
    _ROBOT.set(robot.lower() if robot else None)


def set_correlation_id(corr: str | None) -> None:
    _CORRELATION.set(corr)


def new_correlation_id(prefix: str = "c") -> str:
    corr = f"{prefix}-{uuid.uuid4().hex[:12]}"
    _CORRELATION.set(corr)
    return corr


def correlation_id() -> str | None:
    return _CORRELATION.get()


def redact(value: Any, *, depth: int = 0) -> Any:
    """Recursively redact secrets and bound payload size."""
    if depth > _MAX_DEPTH:
        return "<max_depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        if len(value) > _MAX_STR:
            value = value[:_MAX_STR] + f"…<trunc:{len(value)}>"
        return _SECRET_VALUE_RE.sub("<redacted>", value)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _MAX_LIST:
                out["…"] = f"<truncated {len(value) - _MAX_LIST} keys>"
                break
            ks = str(k)
            if _SECRET_KEY_RE.search(ks):
                out[ks] = "<redacted>"
            else:
                out[ks] = redact(v, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        head = [redact(v, depth=depth + 1) for v in seq[:_MAX_LIST]]
        if len(seq) > _MAX_LIST:
            head.append(f"<truncated {len(seq) - _MAX_LIST} items>")
        return head
    # dataclasses / simple objects
    if hasattr(value, "__dict__") and not isinstance(value, type):
        try:
            return redact(vars(value), depth=depth + 1)
        except Exception:
            return repr(value)[:_MAX_STR]
    text = repr(value)
    if len(text) > _MAX_STR:
        text = text[:_MAX_STR] + "…"
    return _SECRET_VALUE_RE.sub("<redacted>", text)


def _now_iso() -> str:
    return datetime.now(_IST).isoformat(timespec="milliseconds")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)


def audit_paths(workspace_root: Path, bot_name: str | None = None) -> tuple[Path, Path]:
    """Return (money_audit.jsonl, detail_debug.jsonl) under runtime Logs."""
    try:
        from core.batman_mode import log_root

        root = log_root(Path(workspace_root))
    except Exception:
        root = Path(workspace_root) / "logs" / "runtime"
    day = datetime.now(_IST).strftime("%Y-%m-%d")
    ym = datetime.now(_IST).strftime("%Y-%m")
    robot = (bot_name or _ROBOT.get() or "main").lower()
    base = root / ym / day / robot / "audit"
    return base / "money_audit.jsonl", base / "detail_debug.jsonl"


def configure_money_audit(
    workspace_root: Path,
    *,
    bot_name: str,
    settings: Mapping[str, Any] | None = None,
) -> Path:
    """Enable money JSONL + optional DEBUG boost for trading loggers."""
    global _AUDIT_PATH, _DETAIL_PATH, _PAPER_AUDIT_PATH
    cfg = dict(settings or {})
    enabled = bool(cfg.get("audit_jsonl", True))
    set_audit_robot(bot_name)
    money_path, detail_path = audit_paths(workspace_root, bot_name)
    _AUDIT_PATH = money_path
    _DETAIL_PATH = detail_path
    money_path.parent.mkdir(parents=True, exist_ok=True)

    # Always keep money_audit logger at INFO so events land even if root is WARNING.
    logger.setLevel(logging.INFO)
    logger.propagate = True

    if bool(cfg.get("debug_trading", True)):
        for name in (
            "batman",
            "batman.order_manager",
            "batman.money_audit",
            "modules",
            "modules.ato_protection",
            "bat_telegram",
            "place_order_bot",
            "place_order_bot.backend_workflow",
            "place_order_bot.execution",
            "place_order_bot.broker",
            "core.broker",
            "core.order_manager",
        ):
            logging.getLogger(name).setLevel(logging.DEBUG)

    # Mirror DEBUG+ from trading namespaces into detail_debug.jsonl (efficient, one line/event).
    if enabled and bool(cfg.get("detail_jsonl", True)):
        _attach_detail_handler(detail_path)

    if enabled:
        audit(
            "audit.configure",
            bot=bot_name,
            money_path=str(money_path),
            detail_path=str(detail_path),
            level=str(cfg.get("level", "")),
            debug_trading=bool(cfg.get("debug_trading", True)),
        )
    return money_path


def _attach_detail_handler(path: Path) -> None:
    root = logging.getLogger()
    # Avoid duplicate handlers on reconfigure
    for h in list(root.handlers):
        if getattr(h, "_batman_detail_jsonl", False):
            root.removeHandler(h)
    handler = _DetailJsonlHandler(path)
    handler.setLevel(logging.DEBUG)
    handler.addFilter(_TradingNamespaceFilter())
    root.addHandler(handler)


class _TradingNamespaceFilter(logging.Filter):
    _PREFIXES = (
        "batman",
        "modules",
        "bat_telegram",
        "place_order_bot",
        "core.broker",
        "core.order_manager",
        "telegram",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name or ""
        return any(name == p or name.startswith(p + ".") for p in self._PREFIXES)


class _DetailJsonlHandler(logging.Handler):
    _batman_detail_jsonl = True

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            if _SECRET_KEY_RE.search(msg) or _SECRET_VALUE_RE.search(msg):
                msg = _SECRET_VALUE_RE.sub("<redacted>", msg)
                # still scrub key=value pairs lightly
                msg = re.sub(
                    r"(?i)(token|password|secret|authorization|totp|pin)\s*[:=]\s*\S+",
                    r"\1=<redacted>",
                    msg,
                )
            payload = {
                "ts": _now_iso(),
                "level": record.levelname,
                "logger": record.name,
                "msg": msg[:_MAX_STR],
                "robot": _ROBOT.get(),
                "corr": _CORRELATION.get(),
                "module": getattr(record, "module", None),
                "func": record.funcName,
                "line": record.lineno,
            }
            if record.exc_info:
                payload["exc"] = "".join(traceback.format_exception(*record.exc_info))[-4000:]
            _append_jsonl(self.path, payload)
        except Exception:
            self.handleError(record)


def audit(event: str, *, level: str = "INFO", **fields: Any) -> None:
    """Emit one structured money-audit event (JSONL + logger)."""
    try:
        from core.paper_trade_logging import apply_message_prefix, get_trade_lane, set_trade_lane
    except Exception:  # pragma: no cover
        def get_trade_lane():  # type: ignore
            return "unknown"

        def set_trade_lane(_lane):  # type: ignore
            return None

        def apply_message_prefix(message, lane=None):  # type: ignore
            return message

    # Prefer explicit mode/trade_lane field; sync ContextVar for formatters.
    lane_field = fields.get("trade_lane") or fields.get("mode")
    if lane_field in {"paper", "live"}:
        set_trade_lane(str(lane_field))
    lane = get_trade_lane()
    if "trade_lane" not in fields:
        fields = {**fields, "trade_lane": lane}

    payload = {
        "ts": _now_iso(),
        "event": str(event),
        "robot": fields.pop("robot", None) or _ROBOT.get(),
        "corr": fields.pop("corr", None) or _CORRELATION.get(),
        "trade_lane": fields.get("trade_lane", lane),
        "fields": redact(fields),
    }
    path = _AUDIT_PATH
    if path is None:
        # best-effort under cwd if not configured yet
        path = Path("logs") / "audit" / "money_audit.jsonl"
    try:
        _append_jsonl(path, payload)
    except Exception as exc:
        logger.warning("money_audit write failed: %s", exc)

    if str(payload.get("trade_lane") or "") == "paper":
        paper_path = _PAPER_AUDIT_PATH
        if paper_path is None:
            paper_path = Path(path).parent / "money_audit_paper.jsonl"
        try:
            _append_jsonl(paper_path, payload)
        except Exception as exc:
            logger.warning("money_audit paper write failed: %s", exc)

    log_fn = getattr(logger, level.lower(), logger.info)
    # Compact human line — TradeLaneFormatter adds [PAPER TRADE]/[LIVE TRADE]
    flat = " ".join(f"{k}={v!r}" for k, v in list(redact(fields).items())[:20])
    log_fn("AUDIT %s %s", event, flat)


@contextmanager
def audit_span(event: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """Time a critical section; always logs start + end (ok/error)."""
    corr = fields.pop("corr", None) or _CORRELATION.get() or new_correlation_id("span")
    set_correlation_id(corr)
    bag: dict[str, Any] = {"corr": corr}
    t0 = time.perf_counter()
    audit(f"{event}.start", corr=corr, **fields)
    try:
        yield bag
    except Exception as exc:
        extra = {k: v for k, v in {**fields, **bag}.items() if k != "corr" and not str(k).startswith("_")}
        audit(
            f"{event}.error",
            corr=corr,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            error_type=type(exc).__name__,
            error=str(exc)[:500],
            **extra,
        )
        raise
    else:
        extra = {k: v for k, v in {**fields, **bag}.items() if k != "corr" and not str(k).startswith("_")}
        audit(
            f"{event}.ok",
            corr=corr,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            **extra,
        )


def audit_exception(event: str, exc: BaseException, **fields: Any) -> None:
    audit(
        event,
        level="ERROR",
        error_type=type(exc).__name__,
        error=str(exc)[:800],
        traceback="".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-4000:],
        **fields,
    )

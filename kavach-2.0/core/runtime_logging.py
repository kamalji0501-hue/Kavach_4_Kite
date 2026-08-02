from __future__ import annotations

import contextvars
import logging
import threading
import zoneinfo
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_LOCK = threading.Lock()
_LOGGING_ROBOT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "logging_robot", default=None
)

_ROBOT_NAMES = frozenset(
    {"main", "drishti", "kavach", "kavach2", "jagran", "lakshmi", "saransh", "sanchalak"}
)

_MODULE_ALIASES = {
    "main": "main",
    "drishti": "drishti",
    "kavach": "kavach",
    "kavach2": "kavach2",
    "lakshmi": "lakshmi",
    "saransh": "saransh",
    "sanchalak": "sanchalak",
    "incidents": "jagran",
    "jagran": "jagran",
    "nifty_ltp_feed": "nifty_ltp_feed",
    "nifty_ltp": "nifty_ltp_feed",
    "ato_protection": "ato_protection",
}

_MODULE_TO_ROBOT = {
    "nifty_ltp_feed": "drishti",
    "ato_protection": "kavach",
    "incidents": "jagran",
}


@dataclass
class LoggingSinkFailure:
    sink: str
    module: str
    error: str
    ts_ist: datetime


_FAILURES: deque[LoggingSinkFailure] = deque(maxlen=200)


def set_logging_robot(robot: str | None) -> None:
    """Bind unmapped loggers to the active bot process (drishti/kavach/jagran)."""
    if robot is None:
        _LOGGING_ROBOT.set(None)
        return
    name = robot.lower()
    if name not in _ROBOT_NAMES:
        raise ValueError(f"Unknown robot for logging context: {robot!r}")
    _LOGGING_ROBOT.set(name)


def _format_time_ist(ts: datetime) -> str:
    return ts.astimezone(_IST).strftime("%H%M%S.%f")[:-3] + " IST"


def _ym_folder(ts: datetime) -> str:
    return ts.strftime("%Y-%m")


def _day_folder(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d")


def _window_name(ts: datetime) -> str:
    # Special close split per locked design.
    if ts.hour == 15 and ts.minute < 30:
        return f"{ts.strftime('%Y%m%d')}_1500_1530"
    if ts.hour == 15 and ts.minute >= 30:
        return f"{ts.strftime('%Y%m%d')}_post_1530_1600"

    if ts.hour >= 16 or ts.hour < 9:
        start = ts.replace(minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=1)
        return f"{ts.strftime('%Y%m%d')}_post_{start.strftime('%H%M')}_{end.strftime('%H%M')}"

    start = ts.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    return f"{ts.strftime('%Y%m%d')}_{start.strftime('%H%M')}_{end.strftime('%H%M')}"


def _module_for_record(record: logging.LogRecord) -> str:
    name = (record.name or "").lower()
    for key, alias in _MODULE_ALIASES.items():
        if key in name:
            return alias

    parts = [p for p in name.split(".") if p]
    if len(parts) >= 2:
        return parts[1]
    return parts[0] if parts else "main"


def _robot_for_module(module: str) -> str | None:
    if module in _ROBOT_NAMES:
        return module
    mapped = _MODULE_TO_ROBOT.get(module)
    if mapped:
        return mapped
    return _LOGGING_ROBOT.get()


def _line_for_record(record: logging.LogRecord, ts_ist: datetime) -> str:
    stage = getattr(record, "stage", "-")
    step = getattr(record, "step", "-")
    cid = getattr(record, "correlation_id", "-")
    err_code = getattr(record, "error_code", "-")
    module = _module_for_record(record)
    msg = record.getMessage().replace("\n", " ").strip()
    return (
        f"{_format_time_ist(ts_ist)} | {record.levelname} | {module.upper()} | "
        f"{stage} | {step} | {cid} | {msg} | {err_code}\n"
    )


def runtime_day_dir(workspace_root: Path, ts: datetime | None = None) -> Path:
    """logs_{mode}/runtime/YYYY-MM/YYYY-MM-DD/ (IST)."""
    when = ts or datetime.now(_IST)
    try:
        from core.batman_mode import log_runtime_root

        base = log_runtime_root(workspace_root)
    except Exception:
        base = workspace_root / "logs" / "runtime"
    return base / _ym_folder(when) / _day_folder(when)


def robot_logs_dir(workspace_root: Path, robot: str, ts: datetime | None = None) -> Path:
    return runtime_day_dir(workspace_root, ts) / robot.lower() / "logs"


def robot_errors_dir(workspace_root: Path, robot: str, ts: datetime | None = None) -> Path:
    return runtime_day_dir(workspace_root, ts) / robot.lower() / "errors"


def _is_error_level(record: logging.LogRecord) -> bool:
    return record.levelno >= logging.ERROR


class WindowedRuntimeFileHandler(logging.Handler):
    def __init__(self, root_dir: Path):
        super().__init__(level=logging.INFO)
        self._root_dir = root_dir

    def emit(self, record: logging.LogRecord) -> None:
        ts_ist = datetime.fromtimestamp(record.created, tz=_IST)
        line = _line_for_record(record, ts_ist)
        module = _module_for_record(record)
        robot = _robot_for_module(module)
        window = _window_name(ts_ist)
        is_error = _is_error_level(record)

        day_root = self._root_dir / _ym_folder(ts_ist) / _day_folder(ts_ist)
        main_logs_dir = day_root / "logs"
        main_path = main_logs_dir / f"runtime_{window}.log"

        with _LOCK:
            main_logs_dir.mkdir(parents=True, exist_ok=True)

            self._write_with_health(
                main_path, line, sink="main", module=module, ts_ist=ts_ist
            )
            day_main_all = main_logs_dir / "all.log"
            self._write_with_health(
                day_main_all, line, sink="main_day_all", module=module, ts_ist=ts_ist
            )

            if is_error:
                main_err = main_logs_dir / f"runtime_{window}_errors.log"
                self._write_with_health(
                    main_err, line, sink="main_errors", module=module, ts_ist=ts_ist
                )

            if robot is None:
                return

            robot_logs_dir = day_root / robot / "logs"
            robot_errors_dir = day_root / robot / "errors"
            robot_logs_dir.mkdir(parents=True, exist_ok=True)
            robot_errors_dir.mkdir(parents=True, exist_ok=True)

            module_path = robot_logs_dir / f"{module}_{window}.log"
            day_robot_all = robot_logs_dir / "all.log"
            self._write_with_health(
                module_path, line, sink="robot_module", module=module, ts_ist=ts_ist
            )
            self._write_with_health(
                day_robot_all, line, sink="robot_day_all", module=module, ts_ist=ts_ist
            )
            if module != robot:
                robot_path = robot_logs_dir / f"{robot}_{window}.log"
                self._write_with_health(
                    robot_path, line, sink="robot_aggregate", module=module, ts_ist=ts_ist
                )

            if is_error:
                module_err = robot_errors_dir / f"{module}_{window}_errors.log"
                self._write_with_health(
                    module_err,
                    line,
                    sink="robot_module_errors",
                    module=module,
                    ts_ist=ts_ist,
                )
                if module != robot:
                    robot_err = robot_errors_dir / f"{robot}_{window}_errors.log"
                    self._write_with_health(
                        robot_err,
                        line,
                        sink="robot_window_errors",
                        module=module,
                        ts_ist=ts_ist,
                    )
                day_robot_err = robot_errors_dir / "all_errors.log"
                self._write_with_health(
                    day_robot_err,
                    line,
                    sink="robot_day_errors",
                    module=module,
                    ts_ist=ts_ist,
                )

    @staticmethod
    def _write_with_health(
        path: Path,
        line: str,
        *,
        sink: str,
        module: str,
        ts_ist: datetime,
    ) -> None:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception as exc:
            _FAILURES.append(
                LoggingSinkFailure(
                    sink=sink,
                    module=module,
                    error=str(exc),
                    ts_ist=ts_ist,
                )
            )


def drain_logging_failures() -> list[LoggingSinkFailure]:
    with _LOCK:
        items = list(_FAILURES)
        _FAILURES.clear()
        return items


def configure_runtime_logging(config: dict[str, Any], workspace_root: Path) -> None:
    cfg = config.get("logging", {}) if isinstance(config, dict) else {}
    enabled = bool(cfg.get("enabled", True))
    level_name = str(cfg.get("level", "INFO")).upper()
    root_dir = cfg.get("root_dir", "logs/runtime")

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level_name, logging.INFO))

    # Keep stdout visibility for local debug while adding runtime file routing.
    stream_present = any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers)
    if not stream_present:
        root_logger.addHandler(logging.StreamHandler())

    if not enabled:
        return

    root_dir = cfg.get("root_dir", "logs/runtime")
    path = Path(str(root_dir))
    abs_root = path if path.is_absolute() else workspace_root / path
    handler = WindowedRuntimeFileHandler(abs_root)
    root_logger.addHandler(handler)

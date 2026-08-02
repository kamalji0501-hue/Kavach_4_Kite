"""Daily session logs for Phase 1 bulk start/stop launchers (IST, runtime layout)."""

from __future__ import annotations

import threading
import zoneinfo
from datetime import datetime
from pathlib import Path

from core.batman_mode import runtime_root

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_LOCK = threading.Lock()

LAUNCHER_KINDS = frozenset({"stop_all", "start_all", "supervisor"})


def launcher_day_root(workspace_root: Path, kind: str, ts: datetime | None = None) -> Path:
    """logs/{mode}/runtime/YYYY-MM/YYYY-MM-DD/launchers/<kind>/"""
    if kind not in LAUNCHER_KINDS:
        raise ValueError(f"Unknown launcher kind: {kind}")
    from core.runtime_logging import runtime_day_dir

    return runtime_day_dir(workspace_root, ts) / "launchers" / kind


def launcher_logs_dir(workspace_root: Path, kind: str, ts: datetime | None = None) -> Path:
    return launcher_day_root(workspace_root, kind, ts) / "logs"


def launcher_errors_dir(workspace_root: Path, kind: str, ts: datetime | None = None) -> Path:
    return launcher_day_root(workspace_root, kind, ts) / "errors"


def _format_line(level: str, module: str, message: str, *, ts: datetime) -> str:
    msg = message.replace("\n", " ").strip()
    t = ts.astimezone(_IST).strftime("%H%M%S.%f")[:-3] + " IST"
    return f"{t} | {level} | {module.upper()} | - | - | - | {msg} | -\n"


class LauncherSessionLogger:
    """Append-only logger for one bulk launcher run."""

    def __init__(self, workspace_root: Path, kind: str) -> None:
        if kind not in LAUNCHER_KINDS:
            raise ValueError(f"Unknown launcher kind: {kind}")
        self._root = workspace_root
        self._kind = kind
        self._module = kind.replace("_", "_")  # stop_all / start_all

    def _write(self, level: str, message: str) -> None:
        ts = datetime.now(_IST)
        line = _format_line(level, self._module, message, ts=ts)
        logs_dir = launcher_logs_dir(self._root, self._kind, ts)
        errors_dir = launcher_errors_dir(self._root, self._kind, ts)
        with _LOCK:
            logs_dir.mkdir(parents=True, exist_ok=True)
            with open(logs_dir / "all.log", "a", encoding="utf-8") as fh:
                fh.write(line)
            if level in ("ERROR", "CRITICAL", "WARNING"):
                errors_dir.mkdir(parents=True, exist_ok=True)
                with open(errors_dir / "all_errors.log", "a", encoding="utf-8") as fh:
                    fh.write(line)

    def info(self, message: str, *args) -> None:
        text = message % args if args else message
        self._write("INFO", text)
        print(text)

    def warning(self, message: str, *args) -> None:
        text = message % args if args else message
        self._write("WARNING", text)
        print(text)
        self._record_incident("WARNING", text)

    def error(self, message: str, *args) -> None:
        text = message % args if args else message
        self._write("ERROR", text)
        print(text, file=__import__("sys").stderr)
        self._record_incident("ERROR", text)

    def _record_incident(self, level: str, message: str) -> None:
        if level not in ("ERROR", "WARNING"):
            return
        try:
            from core.incident_tracker import record_incident

            domain = "start_all" if self._kind in ("start_all", "supervisor") else "stop_all"
            scenario = f"{self._kind}_{level.lower()}"
            record_incident(
                domain=domain,
                scenario=scenario,
                message=message,
                severity="error" if level == "ERROR" else "warning",
                module=self._kind,
                cause_hint="See launcher log and Show Bot Status.bat.",
            )
        except Exception:
            pass

    def log_path_hint(self) -> str:
        ts = datetime.now(_IST)
        path = launcher_logs_dir(self._root, self._kind, ts)
        try:
            rel = path.relative_to(runtime_root(self._root))
            return str(rel).replace("/", "\\")
        except ValueError:
            return str(path)

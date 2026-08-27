"""In-process handles shared with Kavach Telegram."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class WebRuntime:
    root: Path
    state: Any = None
    broker: Any = None
    event_bus: Any = None
    ato: Any = None
    client_code: str = ""
    web_password: str = ""
    session_secret: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


_RUNTIME: WebRuntime | None = None


def set_runtime(rt: WebRuntime) -> None:
    global _RUNTIME
    _RUNTIME = rt


def get_runtime() -> WebRuntime | None:
    return _RUNTIME


def require_runtime() -> WebRuntime:
    rt = _RUNTIME
    if rt is None:
        raise RuntimeError("Kavach web runtime is not started")
    return rt

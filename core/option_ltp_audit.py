"""Daily audit log for registered option + ATO protect LTPs."""

from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("batman.option_ltp_audit")

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def format_option_ltp_log_line(
    now: datetime,
    quotes: dict[str, float],
    *,
    event: str | None = None,
) -> str:
    """``HH:MM:SS.mmm | role=px | role=px …`` (stable role order when possible)."""
    ts = f"{now.strftime('%H:%M:%S')}.{now.microsecond // 1000:03d}"
    preferred = (
        "pe_buy",
        "pe_sell",
        "ce_buy",
        "ce_sell",
        "pe_protect",
        "ce_protect",
    )
    parts: list[str] = []
    seen: set[str] = set()
    for role in preferred:
        if role in quotes:
            parts.append(f"{role}={float(quotes[role]):.2f}")
            seen.add(role)
    for role in sorted(quotes.keys()):
        if role not in seen:
            parts.append(f"{role}={float(quotes[role]):.2f}")
    body = " | ".join(parts) if parts else "none"
    if event:
        return f"{ts} | {body} | {event}\n"
    return f"{ts} | {body}\n"


def append_option_ltp_log(
    log_dir: Path,
    now: datetime,
    quotes: dict[str, float],
    *,
    event: str | None = None,
) -> Path:
    """Append one line to ``option_ltp_YYYYMMDD.log``."""
    log_dir.mkdir(parents=True, exist_ok=True)
    day = now.strftime("%Y%m%d")
    log_path = log_dir / f"option_ltp_{day}.log"
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(format_option_ltp_log_line(now, quotes, event=event))
    return log_path

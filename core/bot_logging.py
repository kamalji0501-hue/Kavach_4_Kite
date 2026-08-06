"""Unified logging bootstrap — single root: logs/runtime/."""

from __future__ import annotations


import json

import logging

from datetime import datetime

from pathlib import Path

from typing import Any

from zoneinfo import ZoneInfo


from core.runtime_logging import (
    configure_runtime_logging,
    robot_errors_dir,
    robot_logs_dir,
    runtime_day_dir,
    set_logging_robot,
)

_IST = ZoneInfo("Asia/Kolkata")

_VALID_BOTS = frozenset(
    {"drishti", "go", "kavach", "kavach2", "jagran", "main", "saransh", "sanchalak", "lakshmi", "ratripal"}
)


def load_logging_settings(workspace_root: Path) -> dict[str, Any]:
    """Read logging block from config/settings.json with safe defaults."""

    settings_path = workspace_root / "config" / "settings.json"

    defaults: dict[str, Any] = {
        "enabled": True,
        "level": "DEBUG",
        "root_dir": "logs/runtime",
        "audit_jsonl": True,
        "detail_jsonl": True,
        "debug_trading": True,
    }

    if not settings_path.exists():

        return defaults

    try:

        with open(settings_path, encoding="utf-8") as fh:

            raw = json.load(fh)

        if isinstance(raw, dict) and isinstance(raw.get("logging"), dict):

            defaults.update(raw["logging"])

    except Exception:

        pass

    return defaults


def bot_all_log_path(
    workspace_root: Path,
    bot_name: str,
    *,
    ts: datetime | None = None,
) -> Path:
    """Single cumulative log for a robot on a given IST day."""

    return robot_logs_dir(workspace_root, bot_name, ts) / "all.log"


def bot_all_errors_path(
    workspace_root: Path,
    bot_name: str,
    *,
    ts: datetime | None = None,
) -> Path:
    """Single cumulative error log for a robot on a given IST day."""

    return robot_errors_dir(workspace_root, bot_name, ts) / "all_errors.log"


def bot_nifty_ltp_log_dir(
    workspace_root: Path,
    *,
    ts: datetime | None = None,
) -> Path:
    """Legacy GIFT / mixed audit folder under today's DRISHTI runtime folder."""

    return robot_logs_dir(workspace_root, "drishti", ts) / "nifty_ltp"


def bot_nifty_rest_ltp_log_dir(
    workspace_root: Path,
    *,
    ts: datetime | None = None,
) -> Path:
    """REST NIFTY poll audit: ``nifty_rest_ltp/rest_ltp_YYYYMMDD.log``."""

    return robot_logs_dir(workspace_root, "drishti", ts) / "nifty_rest_ltp"


def bot_nifty_websocket_ltp_log_dir(
    workspace_root: Path,
    *,
    ts: datetime | None = None,
) -> Path:
    """WebSocket NIFTY tick audit: ``nifty_websocket_ltp/ws_ltp_YYYYMMDD.log``."""

    return robot_logs_dir(workspace_root, "drishti", ts) / "nifty_websocket_ltp"




def bot_option_ltp_log_dir(
    workspace_root: Path,
    *,
    ts: datetime | None = None,
) -> Path:
    """Registered + ATO protect option LTP audit: ``option_ltp/option_ltp_YYYYMMDD.log``."""

    return robot_logs_dir(workspace_root, "drishti", ts) / "option_ltp"


def bot_ato_tick_csv_dir(
    workspace_root: Path,
    *,
    ts: datetime | None = None,
) -> Path:
    """NIFTY + ATO CE/PE tick CSV mirror under DRISHTI day logs."""

    return robot_logs_dir(workspace_root, "drishti", ts) / "ato_tick_csv"

def main_all_log_path(workspace_root: Path, *, ts: datetime | None = None) -> Path:
    """Single cumulative main timeline for an IST day (all robots)."""

    return runtime_day_dir(workspace_root, ts) / "logs" / "all.log"


# Back-compat aliases (deprecated — use bot_all_log_path)


def bot_startup_log_path(workspace_root: Path, bot_name: str) -> Path:

    return bot_all_log_path(workspace_root, bot_name)


def bot_startup_errors_log_path(workspace_root: Path, bot_name: str) -> Path:

    return bot_all_errors_path(workspace_root, bot_name)


def bot_log_dir(workspace_root: Path, bot_name: str) -> Path:

    return robot_logs_dir(workspace_root, bot_name)


def _attach_domain_incident_handler(
    workspace_root: Path, domain: str, fmt: logging.Formatter
) -> None:
    from core.incident_log_handler import DomainIncidentHandler

    handler = DomainIncidentHandler(workspace_root, domain)
    handler.setFormatter(fmt)
    logging.getLogger().addHandler(handler)


def attach_main_incident_handler(workspace_root: Path) -> None:
    """Attach incident tracking for main.py five-bot orchestrator."""
    from core.paper_trade_logging import TradeLaneFormatter

    fmt = TradeLaneFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    _attach_domain_incident_handler(workspace_root, "main", fmt)


def configure_bot_logging(
    *,
    workspace_root: Path,
    bot_name: str,
) -> Path:
    """Console + runtime logs only (IST, date-wise under logs/runtime/).



    Layout (single root):

      logs/runtime/YYYY-MM/YYYY-MM-DD/logs/all.log           ← main (all bots)

      logs/runtime/YYYY-MM/YYYY-MM-DD/logs/runtime_{window}.log

      logs/runtime/YYYY-MM/YYYY-MM-DD/{bot}/logs/all.log     ← tail this for one bot

      logs/runtime/YYYY-MM/YYYY-MM-DD/{bot}/errors/all_errors.log

    """

    try:
        from core.batman_mode import effective_logging_settings

        settings = effective_logging_settings(workspace_root)
    except Exception:
        settings = load_logging_settings(workspace_root)

    level_name = str(settings.get("level", "INFO")).upper()

    level = getattr(logging, level_name, logging.INFO)

    name = bot_name.lower()

    if name not in _VALID_BOTS:

        raise ValueError(f"Unknown bot for logging: {bot_name!r}")

    set_logging_robot(name)

    from core.paper_trade_logging import TradeLaneFormatter

    fmt = TradeLaneFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = logging.getLogger()

    root.setLevel(level)

    root.handlers.clear()

    console = logging.StreamHandler()

    console.setFormatter(fmt)

    root.addHandler(console)

    configure_runtime_logging({"logging": settings}, workspace_root)

    try:
        from core.money_audit import configure_money_audit

        configure_money_audit(workspace_root, bot_name=name, settings=settings)
        try:
            from core.money_audit import audit

            audit(
                "logging.bootstrap.evidence",
                bot=name,
                level=str(settings.get("level")),
                audit_jsonl=bool(settings.get("audit_jsonl", True)),
                detail_jsonl=bool(settings.get("detail_jsonl", True)),
                debug_trading=bool(settings.get("debug_trading", True)),
                log_hint=str(bot_all_log_path(workspace_root, name)),
            )
        except Exception:
            pass
    except Exception as exc:
        logging.getLogger(__name__).warning("money_audit configure failed: %s", exc)

    from core.incident_log_handler import DomainIncidentHandler

    _attach_domain_incident_handler(workspace_root, name, fmt)

    tail_path = bot_all_log_path(workspace_root, name)

    tail_path.parent.mkdir(parents=True, exist_ok=True)

    robot_errors_dir(workspace_root, name).mkdir(parents=True, exist_ok=True)

    return tail_path

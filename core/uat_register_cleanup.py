"""UAT /register — wipe prior book, deployments, and virtual orders before fresh OCR."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from core.batman_mode import deployments_dir, is_uat, uat_screenshot_dir, workspace_root
from core.uat_positions import positions_json_path

logger = logging.getLogger("batman.uat_register_cleanup")


def prepare_uat_register_fresh(
    root: Path | None = None,
    *,
    state: Any = None,
    broker: Any = None,
) -> dict[str, Any]:
    """
    Register is a clean slate: archive deployments, delete positions.json,
    reset state, clear ShadowBroker virtual orders.
    """
    root = root or workspace_root()
    if not is_uat(root):
        return {"skipped": True, "reason": "not_uat"}

    summary: dict[str, Any] = {"ok": True}

    # Archive active deployment files (not armed anymore for this session).
    # Prefer KAVACH 2.0; legacy kavach.bot is past-project fallback only.
    try:
        try:
            import bat_telegram.bots.kavach2.bot as kavach_bot
        except ImportError:
            import bat_telegram.bots.kavach.bot as kavach_bot  # legacy

        moved = kavach_bot._archive_active_deployments()
        summary["archived_deployments"] = moved
        if moved:
            logger.info("UAT register cleanup: archived %s", moved)
    except Exception as exc:
        logger.warning("UAT register cleanup: archive failed: %s", exc)
        summary["archive_error"] = str(exc)

    # Remove OCR/stale positions.json; keep cursor_chat book from Cursor screenshot skill
    pos_path = positions_json_path(root)
    if pos_path.is_file():
        keep_chat = False
        try:
            import json

            with open(pos_path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and data.get("source") == "cursor_chat":
                keep_chat = True
                summary["kept_cursor_chat_positions"] = True
        except Exception:
            pass
        if not keep_chat:
            pos_path.unlink()
            summary["removed_positions_json"] = True
            logger.info("UAT register cleanup: removed %s", pos_path)

    # Clear shadow virtual order book on broker instance
    if broker is not None and hasattr(broker, "_orders"):
        broker._orders.clear()
        summary["cleared_virtual_orders"] = True
    try:
        from backtest_engine.shadow.ledger_store import clear_ledger

        clear_ledger(root)
        summary["cleared_shadow_order_ledger"] = True
    except Exception as exc:
        logger.warning("UAT register cleanup: shadow ledger clear failed: %s", exc)
        summary["shadow_ledger_error"] = str(exc)

    # Reset persisted Batman state (deployment not confirmed)
    if state is not None:
        try:
            try:
                from bat_telegram.bots.kavach2.bot import _state_reset
            except ImportError:
                from bat_telegram.bots.kavach.bot import _state_reset  # legacy

            _state_reset(state)
            state.set("deployment.confirmed", False, save=False)
            state.set("deployment.batman_complete", False, save=False)
            state.set("algo.paused", False, save=False)
            state.save()
            summary["state_reset"] = True
        except Exception as exc:
            logger.warning("UAT register cleanup: state reset failed: %s", exc)
            summary["state_reset_error"] = str(exc)

    try:
        from core.saransh_session_sync import saransh_session_reset_feeds_only

        saransh_session_reset_feeds_only(root=root)
        summary["saransh_feeds_reset"] = True
    except Exception as exc:
        logger.warning("UAT register cleanup: SARANSH feed reset failed: %s", exc)
        summary["saransh_feeds_reset_error"] = str(exc)

    dep_dir = deployments_dir(root)
    summary["deploy_dir"] = str(dep_dir)
    summary["screenshot_dir"] = str(uat_screenshot_dir(root))
    return summary

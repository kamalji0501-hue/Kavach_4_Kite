"""UAT automatic screenshot ingest (Sensibull → positions.json). Screenshot is source of truth."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.batman_mode import deployments_dir, is_uat, uat_screenshot_dir, workspace_root
from core.uat_positions import find_screenshot_images, positions_json_path

logger = logging.getLogger("batman.uat_ingest")


class UATIngestError(Exception):
    """Screenshot missing or OCR parse failed."""


def ingest_uat_screenshot(
    root: Path | None = None,
    *,
    required: bool = False,
    allow_while_armed: bool = False,
    newest_only: bool = False,
) -> dict[str, Any]:
    """
    OCR Sensibull screenshot → positions.json.

    When newest_only=True (Register flow): only the latest image in
    uat/deployed_positions/ is used — never reuses an old positions.json.
    """
    root = root or workspace_root()
    if not is_uat(root):
        return {"skipped": True, "reason": "not_uat_mode"}

    if allow_while_armed is False:
        try:
            import bat_telegram.bots.kavach.bot as kavach_bot

            kavach_bot._DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
            if kavach_bot._find_active_deployment() is not None:
                logger.info("UAT ingest skipped — Batman armed; complete Batman before new screenshot")
                return {
                    "skipped": True,
                    "reason": "batman_armed",
                    "message": "Batman is armed. Tap Batman Complete before using a new screenshot.",
                }
        except Exception:
            dep_dir = deployments_dir(root)
            if dep_dir.is_dir() and any(dep_dir.glob("batman_*.json")):
                return {
                    "skipped": True,
                    "reason": "batman_armed",
                    "message": "Batman is armed. Tap Batman Complete before using a new screenshot.",
                }

    images = find_screenshot_images(uat_screenshot_dir(root))
    if not images:
        msg = (
            f"No screenshot in {uat_screenshot_dir(root)}. "
            "Paste a full Sensibull strategy-builder PNG/JPG there "
            "(OCR fallback expects 4 legs; prefer cursor_chat 8-leg book)."
        )
        if required:
            raise UATIngestError(msg)
        logger.warning(msg)
        return {"ok": False, "error": msg}

    from backtest_engine.uat.sensibull_parser import parse_sensibull_image

    to_try = [images[0]] if newest_only else images
    errors: list[str] = []
    fixture: dict[str, Any] | None = None
    image_used: Path | None = None

    for image in to_try:
        logger.info("UAT ingest: OCR screenshot %s", image.name)
        try:
            fixture = parse_sensibull_image(image)
            image_used = image
            break
        except Exception as exc:
            err = f"{image.name}: {exc}"
            errors.append(err)
            logger.warning("UAT ingest failed %s — %s", image.name, exc)

    if fixture is None:
        hint = (
            "Paste a full Sensibull screenshot showing classic 4 legs "
            "(PE sell/buy, CE buy/sell) with strikes and premiums, "
            "or use cursor_chat 8-leg book instead. Partial screenshots fail OCR."
        )
        msg = (
            f"Could not read Sensibull book from screenshot. {errors[0] if errors else 'unknown'}. {hint}"
        )
        logger.error(msg)
        if required:
            raise UATIngestError(msg) from None
        return {"ok": False, "error": msg, "parse_errors": errors}

    image = image_used or images[0]
    out = positions_json_path(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(fixture, fh, indent=2)
        fh.write("\n")

    logger.info("UAT positions.json written from %s (%d legs)", image.name, len(fixture.get("legs", [])))
    return {
        "ok": True,
        "image": image.name,
        "positions_path": str(out),
        "expiry_date": fixture.get("expiry_date"),
        "spot": fixture.get("spot_at_capture"),
    }


def ingest_uat_at_startup(root: Path | None = None) -> dict[str, Any]:
    """KAVACH boot: use cursor_chat positions.json; do not run slow multi-PNG OCR."""
    root = root or workspace_root()
    if not is_uat(root):
        return {"skipped": True, "reason": "not_uat_mode"}

    from core.uat_chat_positions import (
        is_cursor_chat_positions,
        is_valid_positions_file,
        load_positions_json,
    )

    if is_valid_positions_file(root):
        data = load_positions_json(root) or {}
        if is_cursor_chat_positions(data):
            logger.info(
                "UAT startup: cursor_chat positions.json ready (%s)",
                data.get("source_image", "positions.json"),
            )
            return {
                "ok": True,
                "skipped": True,
                "reason": "cursor_chat_ready",
                "method": "cursor_chat",
                "expiry_date": data.get("expiry_date"),
            }
        logger.info("UAT startup: existing positions.json — skip OCR")
        return {"ok": True, "skipped": True, "reason": "positions_json_present"}

    images = find_screenshot_images(uat_screenshot_dir(root))
    if not images:
        msg = f"No screenshot in {uat_screenshot_dir(root)}"
        logger.warning(msg)
        return {"ok": False, "error": msg}

    return ingest_uat_screenshot(root, required=False, newest_only=True)


def ingest_uat_for_register(
    root: Path | None = None,
    *,
    prefer_chat: bool = True,
) -> dict[str, Any]:
    """
    Register ingest: use cursor_chat positions.json when valid; else OCR screenshot.
    """
    root = root or workspace_root()
    if not is_uat(root):
        return {"skipped": True, "reason": "not_uat_mode"}

    from core.uat_chat_positions import (
        UATChatPositionsError,
        is_cursor_chat_positions,
        is_valid_positions_file,
        load_positions_json,
        validate_fixture,
    )

    if prefer_chat:
        data = load_positions_json(root)
        if data and is_cursor_chat_positions(data):
            try:
                validate_fixture(data)
                logger.info("UAT register: using cursor_chat positions.json (skip OCR)")
                return {
                    "ok": True,
                    "method": "cursor_chat",
                    "positions_path": str(positions_json_path(root)),
                    "expiry_date": data.get("expiry_date"),
                    "spot": data.get("spot_at_capture"),
                }
            except UATChatPositionsError as exc:
                logger.warning("cursor_chat positions invalid: %s", exc)

    if is_valid_positions_file(root) and not prefer_chat:
        data = load_positions_json(root)
        return {
            "ok": True,
            "method": "existing_json",
            "positions_path": str(positions_json_path(root)),
            "expiry_date": (data or {}).get("expiry_date"),
        }

    try:
        return ingest_uat_screenshot(root, required=True, newest_only=True)
    except UATIngestError:
        raise UATIngestError(
            "No valid UAT positions. Paste Sensibull screenshot in Cursor chat with: "
            "UAT POSITIONS @uat-sensibull-from-chat — then Register again. "
            "See UAT_CHAT_POSITIONS.md"
        ) from None


def publish_uat_ingest_failure(event_bus: Any, error: str, *, image: str = "") -> None:
    if event_bus is None:
        return
    try:
        from core.event_bus import Event

        event_bus.publish(
            Event.MODULE_ERROR,
            {
                "module": "kavach",
                "scenario": "uat_screenshot_ingest",
                "severity": "warning",
                "category": "uat",
                "title": "UAT screenshot ingest failed",
                "error_message": error,
                "image": image,
                "environment": "uat",
            },
        )
    except Exception as exc:
        logger.warning("Could not publish UAT ingest incident: %s", exc)

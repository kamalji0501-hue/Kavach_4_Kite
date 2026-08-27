"""Shared ATO working profile — same recipe for UAT and prod (live)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.batman_mode import workspace_root
from core.buffer_config import (
    BufferKind,
    legacy_int_from_buffer,
    normalize_buffer_field,
    serialize_buffer_field,
)

logger = logging.getLogger("batman.ato_working_profile")

_PROFILE_NAME = "ato_working_profile.json"


def working_profile_path(root: Path | None = None) -> Path:
    ws = root or workspace_root()
    return ws / "config" / _PROFILE_NAME


def load_working_profile(root: Path | None = None) -> dict[str, Any] | None:
    path = working_profile_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not load ATO working profile %s: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def apply_working_profile_to_state(
    state: Any,
    *,
    root: Path | None = None,
    save: bool = True,
    force: bool = False,
    for_deploy: bool = False,
) -> bool:
    """Overlay proven recipe onto live state.

    Buffers, manage_sides, and Register poll are **not** overwritten unless ``apply_buffers_on_deploy_confirm`` /
    ``apply_buffers_on_ato_restore`` is true (or ``force``), so Register / Buffer
    Manager values stick.
    """
    profile = load_working_profile(root)
    if not profile:
        return False
    if not force:
        flag = "apply_on_deploy_confirm" if for_deploy else "apply_on_ato_restore"
        default = bool(for_deploy)
        if not profile.get(flag, default):
            return False

    apply_buffers = bool(
        force
        or profile.get(
            "apply_buffers_on_deploy_confirm" if for_deploy else "apply_buffers_on_ato_restore",
            False,
        )
    )

    if apply_buffers:
        pe_entry = normalize_buffer_field(
            profile.get("pe_entry_buffer", profile.get("pe_entry_buffer_points", 20))
        )
        pe_retrace = normalize_buffer_field(
            profile.get("pe_retrace_buffer", profile.get("pe_retrace_points", 10))
        )
        ce_entry = normalize_buffer_field(
            profile.get("ce_entry_buffer", profile.get("ce_entry_buffer_points", 0))
        )
        ce_retrace = normalize_buffer_field(
            profile.get("ce_retrace_buffer", profile.get("ce_retrace_points", 5))
        )
        state.set("ato.pe_entry_buffer_points", pe_entry, save=False)
        state.set("ato.pe_retrace_points", pe_retrace, save=False)
        state.set("ato.ce_entry_buffer_points", ce_entry, save=False)
        state.set("ato.ce_retrace_points", ce_retrace, save=False)
    else:
        pe_entry = state.get("ato.pe_entry_buffer_points")
        pe_retrace = state.get("ato.pe_retrace_points")

    # Never stomp Register manage_sides (operator chose pe/ce/both).
    apply_manage = bool(force or profile.get("apply_manage_sides_on_deploy_confirm", False))
    if apply_manage:
        state.set("ato.manage_sides", profile.get("manage_sides", "pe"), save=False)
    manage_now = state.get("ato.manage_sides", profile.get("manage_sides", "pe"))

    # Register poll wins unless the profile explicitly forces it.
    apply_poll = bool(
        force
        or profile.get(
            "apply_poll_on_deploy_confirm" if for_deploy else "apply_poll_on_ato_restore",
            False,
        )
    )
    poll = profile.get("poll_interval_seconds")
    if apply_poll and poll is not None:
        state.set("ato.poll_interval_seconds", int(poll), save=False)
    poll_now = state.get("ato.poll_interval_seconds", poll)
    if save:
        state.save()
    logger.info(
        "ATO working profile applied to state (%s): buffers=%s PE entry=%s retrace=%s "
        "manage=%s%s poll=%s%s",
        profile.get("label", "unnamed"),
        "yes" if apply_buffers else "kept",
        pe_entry,
        pe_retrace,
        manage_now,
        "" if apply_manage else " (kept)",
        poll_now,
        "" if apply_poll else " (kept)",
    )
    return True


def apply_working_profile_to_deploy(
    dep: dict[str, Any],
    *,
    root: Path | None = None,
    force: bool = False,
) -> bool:
    """Overlay proven recipe onto a deployment dict (mutates in place).

    Operator entry/exit buffers, manage_sides, and Register poll are preserved unless explicitly
    enabled in the profile (or ``force``).
    """
    profile = load_working_profile(root)
    if not profile:
        return False
    if not force and not profile.get("apply_on_deploy_confirm", True):
        return False

    ato = dep.setdefault("ato", {})
    apply_buffers = bool(force or profile.get("apply_buffers_on_deploy_confirm", False))

    if apply_buffers:
        pe_entry = normalize_buffer_field(
            profile.get("pe_entry_buffer", profile.get("pe_entry_buffer_points", 20))
        )
        pe_retrace = normalize_buffer_field(
            profile.get("pe_retrace_buffer", profile.get("pe_retrace_points", 10))
        )
        ce_entry = normalize_buffer_field(
            profile.get("ce_entry_buffer", profile.get("ce_entry_buffer_points", 0))
        )
        ce_retrace = normalize_buffer_field(
            profile.get("ce_retrace_buffer", profile.get("ce_retrace_points", 5))
        )

        ato["pe_entry_buffer"] = serialize_buffer_field(pe_entry, BufferKind.PREDEFINED)
        ato["pe_retrace_buffer"] = serialize_buffer_field(pe_retrace, BufferKind.PREDEFINED)
        ato["ce_entry_buffer"] = serialize_buffer_field(ce_entry, BufferKind.CUSTOM)
        ato["ce_retrace_buffer"] = serialize_buffer_field(ce_retrace, BufferKind.CUSTOM)
        ato["pe_entry_buffer_points"] = legacy_int_from_buffer(pe_entry)
        ato["pe_retrace_points"] = legacy_int_from_buffer(pe_retrace, default=10)
        ato["ce_entry_buffer_points"] = legacy_int_from_buffer(ce_entry)
        ato["ce_retrace_points"] = legacy_int_from_buffer(ce_retrace, default=5)

    apply_poll = bool(force or profile.get("apply_poll_on_deploy_confirm", False))
    poll = profile.get("poll_interval_seconds")
    if apply_poll and poll is not None:
        ato["poll_interval_seconds"] = int(poll)

    apply_manage = bool(force or profile.get("apply_manage_sides_on_deploy_confirm", False))
    if apply_manage:
        dep["ato_manage_sides"] = profile.get("manage_sides", dep.get("ato_manage_sides", "pe"))
    elif not dep.get("ato_manage_sides"):
        dep["ato_manage_sides"] = "both"
    return True

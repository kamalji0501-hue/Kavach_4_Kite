"""Optional Phase 1 bots (SARANSH) — eligibility without blocking core trio."""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
_PLACEHOLDER_MARKERS = ("<ENTER", "YOUR_", "PLACEHOLDER", "CHANGEME")


def _is_placeholder(value: str | None) -> bool:
    if not value or not str(value).strip():
        return True
    upper = str(value).upper()
    return any(m in upper for m in _PLACEHOLDER_MARKERS)


def optional_bot_enabled(bot_name: str, *, root: Path | None = None) -> tuple[bool, str]:
    """Return (eligible, reason). False reason is safe to log (no secrets)."""
    base = root or ROOT
    name = bot_name.strip().lower()
    params_path = base / "telegram" / "bots" / name / "params.json"
    token_path = base / "telegram" / "bots" / name / "token.env"

    if not params_path.is_file():
        return False, f"{name}: params.json missing"
    try:
        params = json.loads(params_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, f"{name}: params.json unreadable"
    if not params.get("enabled", True):
        return False, f"{name}: disabled in params.json"

    if not token_path.is_file():
        return False, f"{name}: token.env missing"

    env = dotenv_values(token_path)
    prefix = name.upper()
    token = (env.get(f"{prefix}_BOT_TOKEN") or env.get("BOT_TOKEN") or "").strip()
    chat = (env.get(f"{prefix}_CHAT_ID") or env.get("CHAT_ID") or "").strip()
    if _is_placeholder(token):
        return False, f"{name}: token placeholder"
    if _is_placeholder(chat):
        return False, f"{name}: chat_id placeholder"

    start_dir = base / "Execution" / "Start Bots"
    if name == "saransh":
        candidates = [start_dir / "start Saransh.sh", start_dir / "start Saransh.bat"]
    else:
        title = name.title()
        candidates = [start_dir / f"start {title}.sh", start_dir / f"start {title}.bat"]
    if not any(p.is_file() for p in candidates):
        return False, f"{name}: start launcher not deployed yet ({candidates[0].name})"

    return True, "ok"

"""Batman runtime mode: dev | uat | prod (single config key + env override)."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any, Literal

ModeName = Literal["dev", "uat", "prod"]
_VALID_MODES: frozenset[str] = frozenset({"dev", "uat", "prod"})
_CONFIG_REL = Path("config") / "batman_mode.json"
_LOCAL_RUNTIME_REL = Path("config") / "local_runtime.json"
_ENV_MODE = "BATMAN_MODE"
_ENV_RUNTIME_ROOT = "BATMAN_RUNTIME_ROOT"
_ENV_LOGS_ROOT = "BATMAN_LOGS_ROOT"
_ENV_DATA_REPORTS_ROOT = "BATMAN_DATA_REPORTS_ROOT"
_ENV_SECRETS_ROOT = "BATMAN_SECRETS_ROOT"
_EXECUTED_DATA_DIR = "Batman Executed Data"


def workspace_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _expand_path(raw: str, *, workspace: Path) -> Path:
    text = raw.strip()
    # Windows-style env vars in shared configs (ChromeOS / Linux have no USERPROFILE).
    home = str(Path.home())
    for win_var in ("%USERPROFILE%", "%HOMEPATH%", "%HOME%"):
        text = text.replace(win_var, home)
    text = os.path.expandvars(os.path.expanduser(text))
    path = Path(text)
    if not path.is_absolute():
        return (workspace / path).resolve()
    return path.resolve()


def _config_path(root: Path | None = None) -> Path:
    return (root or workspace_root()) / _CONFIG_REL


def load_mode_config(root: Path | None = None) -> dict[str, Any]:
    path = _config_path(root)
    if not path.is_file():
        raw: dict[str, Any] = {"mode": "dev", "modes": {}}
    else:
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        raw = loaded if isinstance(loaded, dict) else {"mode": "dev", "modes": {}}

    ws = root or workspace_root()
    local_path = ws / _LOCAL_RUNTIME_REL
    if local_path.is_file():
        try:
            with open(local_path, encoding="utf-8") as fh:
                local = json.load(fh)
            if isinstance(local, dict):
                for key in (
                    "runtime_root",
                    "logs_root",
                    "data_reports_root",
                    "secrets_root",
                ):
                    if key in local and local[key]:
                        raw[key] = local[key]
        except Exception:
            pass
    return raw


def get_mode(root: Path | None = None) -> ModeName:
    """Current mode: BATMAN_MODE env overrides config file."""
    env = (os.environ.get(_ENV_MODE) or "").strip().lower()
    if env in _VALID_MODES:
        return env  # type: ignore[return-value]
    cfg = load_mode_config(root)
    mode = str(cfg.get("mode", "dev")).strip().lower()
    if mode not in _VALID_MODES:
        return "dev"
    return mode  # type: ignore[return-value]


def set_mode(mode: str, root: Path | None = None) -> Path:
    """Persist mode to config/batman_mode.json (used by Mode/*.bat)."""
    mode = mode.strip().lower()
    if mode not in _VALID_MODES:
        raise ValueError(f"Invalid mode {mode!r}; use dev, uat, or prod")

    root = root or workspace_root()
    path = _config_path(root)
    cfg = load_mode_config(root)
    cfg["mode"] = mode
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    return path


def get_mode_spec(root: Path | None = None) -> dict[str, Any]:
    cfg = load_mode_config(root)
    mode = get_mode(root)
    modes = cfg.get("modes") if isinstance(cfg.get("modes"), dict) else {}
    spec = modes.get(mode) if isinstance(modes, dict) else None
    return spec if isinstance(spec, dict) else {}


def executed_data_root(root: Path | None = None) -> Path:
    """Parent of Logs + Data and Reports (Desktop/Batman Executed Data)."""
    return (Path.home() / "Desktop" / _EXECUTED_DATA_DIR).resolve()


def _legacy_runtime_root(root: Path | None = None) -> Path | None:
    """Single-folder runtime_root (pre-split layout), if configured."""
    ws = root or workspace_root()
    env = (os.environ.get(_ENV_RUNTIME_ROOT) or "").strip()
    if env:
        return _expand_path(env, workspace=ws)
    cfg = load_mode_config(ws)
    if _uses_split_layout(cfg):
        return None
    configured = str(cfg.get("runtime_root") or "").strip()
    if configured:
        return _expand_path(configured, workspace=ws)
    return None


def _uses_split_layout(cfg: dict[str, Any]) -> bool:
    return bool(str(cfg.get("logs_root") or "").strip()) or bool(
        str(cfg.get("data_reports_root") or "").strip()
    )


def data_reports_base(root: Path | None = None) -> Path:
    """External data + reports root (default: Desktop/.../Data and Reports).

    When an explicit *root* is passed (tests / alternate workspaces), never fall
    back to the Windows Desktop path — keep artifacts under that root.
    """
    ws = root or workspace_root()
    env = (os.environ.get(_ENV_DATA_REPORTS_ROOT) or "").strip()
    if env:
        return _expand_path(env, workspace=ws)
    cfg = load_mode_config(ws)
    configured = str(cfg.get("data_reports_root") or "").strip()
    if configured:
        return _expand_path(configured, workspace=ws)
    legacy = _legacy_runtime_root(ws)
    if legacy is not None:
        return legacy
    # Explicit non-workspace root (pytest tmp_path, etc.): stay inside it.
    if root is not None and root.resolve() != workspace_root().resolve():
        return root.resolve()
    return (executed_data_root(ws) / "Data and Reports").resolve()


def logs_base(root: Path | None = None) -> Path:
    """External logs root (default: Desktop/Batman Executed Data/Logs)."""
    ws = root or workspace_root()
    env = (os.environ.get(_ENV_LOGS_ROOT) or "").strip()
    if env:
        return _expand_path(env, workspace=ws)
    cfg = load_mode_config(ws)
    configured = str(cfg.get("logs_root") or "").strip()
    if configured:
        return _expand_path(configured, workspace=ws)
    legacy = _legacy_runtime_root(ws)
    if legacy is not None:
        return legacy / "logs"
    if root is not None and root.resolve() != workspace_root().resolve():
        return (root / "logs").resolve()
    return (executed_data_root(ws) / "Logs").resolve()


def secrets_root(root: Path | None = None) -> Path:
    """Secrets outside git — Telegram tokens, optional Dhan .env (default: Desktop/Batman-Secrets)."""
    ws = root or workspace_root()
    env = (os.environ.get(_ENV_SECRETS_ROOT) or "").strip()
    if env:
        return _expand_path(env, workspace=ws)
    cfg = load_mode_config(ws)
    configured = str(cfg.get("secrets_root") or "").strip()
    if configured:
        return _expand_path(configured, workspace=ws)
    if root is not None and root.resolve() != workspace_root().resolve():
        return (root / "secrets").resolve()
    return (Path.home() / "Desktop" / "Batman-Secrets").resolve()


def runtime_root(root: Path | None = None) -> Path:
    """Umbrella runtime parent for display/relative paths (split or legacy)."""
    ws = root or workspace_root()
    legacy = _legacy_runtime_root(ws)
    if legacy is not None:
        return legacy
    if root is not None and root.resolve() != workspace_root().resolve():
        return root.resolve()
    return executed_data_root(ws)


def secrets_bot_dir(bot_name: str, root: Path | None = None) -> Path:
    return secrets_root(root) / "telegram" / "bots" / bot_name.strip().lower()


def secrets_dhan_env_path(root: Path | None = None) -> Path:
    return secrets_root(root) / "config" / ".env"


def secrets_telegram_bots_env_path(root: Path | None = None) -> Path:
    """Consolidated Telegram bot tokens on the desktop/runtime."""
    from core.telegram_credentials import secrets_telegram_bots_env_path as _p

    return _p(root)


def shared_data_dir(root: Path | None = None) -> Path:
    """Cross-mode shared artifacts (JWT, NIFTY cache, DRISHTI/JAGRAN locks)."""
    return data_reports_base(root) / "data" / "shared"


def data_root(root: Path | None = None) -> Path:
    mode = get_mode(root)
    return data_reports_base(root) / "data" / mode


def log_root(root: Path | None = None) -> Path:
    mode = get_mode(root)
    return logs_base(root) / mode


def reports_root(root: Path | None = None) -> Path:
    return data_reports_base(root) / "reports"


def daily_test_execution_dir(root: Path | None = None) -> Path:
    return reports_root(root) / "daily_test_execution"


def reliability_artifacts_dir(root: Path | None = None) -> Path:
    return reports_root(root) / "reliability"


def feedback_loop_dir(root: Path | None = None) -> Path:
    return reports_root(root) / "feedback_loop"


def log_runtime_root(root: Path | None = None) -> Path:
    return log_root(root) / "runtime"


def deployments_dir(root: Path | None = None) -> Path:
    return data_root(root) / "deployments"


def session_bundle_dir(root: Path | None = None) -> Path:
    return data_root(root) / "session_bundle"


def incidents_root(root: Path | None = None) -> Path:
    return data_root(root) / "analytics" / "incidents"


def access_token_path(root: Path | None = None) -> Path:
    return shared_data_dir(root) / "access_token.json"


def nifty_ltp_cache_path(root: Path | None = None) -> Path:
    return shared_data_dir(root) / "nifty_ltp_cache.json"


def shadow_ledger_path(root: Path | None = None) -> Path:
    return data_root(root) / "shadow_order_ledger.json"


def bot_lock_path(bot_name: str, root: Path | None = None) -> Path:
    """Mode-aware lock paths (DRISHTI/JAGRAN shared; KAVACH/SARANSH per mode)."""
    key = bot_name.strip().lower()
    if key == "kavach":
        return kavach_lock_path(root)
    if key == "saransh":
        return saransh_lock_path(root)
    if key == "kavach2":
        return kavach2_lock_path(root)
    return shared_data_dir(root) / f"{key}.lock"


def kavach_lock_path(root: Path | None = None) -> Path:
    return data_root(root) / "kavach.lock"


def saransh_lock_path(root: Path | None = None) -> Path:
    return data_root(root) / "saransh.lock"


def kavach2_lock_path(root: Path | None = None) -> Path:
    return data_root(root) / "kavach2.lock"


def state_path(root: Path | None = None) -> Path:
    return data_root(root) / "batman_state.json"


def uat_screenshot_dir(root: Path | None = None) -> Path:
    return data_root(root) / "deployed_positions"


def orders_blocked(root: Path | None = None) -> bool:
    spec = get_mode_spec(root)
    orders = str(spec.get("orders", "")).lower()
    return orders in {"blocked", "virtual"}


def is_uat(root: Path | None = None) -> bool:
    return get_mode(root) == "uat"


def is_prod(root: Path | None = None) -> bool:
    return get_mode(root) == "prod"


def prod_hostname_guard(root: Path | None = None) -> str | None:
    """Warn when prod mode on a non-VPS hostname (informational only)."""
    if not is_prod(root):
        return None
    host = socket.gethostname().lower()
    if any(tag in host for tag in ("vps", "server", "prod", "aws", "azure", "ip-172", "ec2", "compute")):
        return None
    return (
        f"Mode is prod but hostname looks like a laptop ({host!r}). "
        "Confirm before live orders."
    )


def trading_runtime_umbrella(root: Path | None = None) -> Path | None:
    """Parent of Logs/Data/Credentials when using split Trading_Runtime layout."""
    ws = root or workspace_root()
    lb = logs_base(ws)
    if lb.name.lower() == "logs":
        return lb.parent
    return None


def ensure_runtime_layout(root: Path | None = None) -> dict[str, Path]:
    """Create standard runtime folders (idempotent)."""
    ws = root or workspace_root()
    mode = get_mode(ws)
    paths = {
        "executed_data_root": executed_data_root(ws),
        "logs_base": logs_base(ws),
        "data_reports_base": data_reports_base(ws),
        "runtime_root": runtime_root(ws),
        "secrets_root": secrets_root(ws),
        "shared_data": shared_data_dir(ws),
        "data": data_root(ws),
        "logs": log_root(ws),
        "reports": reports_root(ws),
        "daily_tests": daily_test_execution_dir(ws),
        "uat_positions": uat_screenshot_dir(ws),
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    for sub in ("config", "telegram", "bots"):
        (secrets_root(ws) / sub).mkdir(parents=True, exist_ok=True)
    (secrets_root(ws) / "Tokens").mkdir(parents=True, exist_ok=True)
    umbrella = trading_runtime_umbrella(ws)
    if umbrella is not None:
        for name in (
            "Temp",
            "Cache",
            "Backups",
            "Health",
            "Exports",
            "Screenshots",
            "Database",
            "User",
            "Config",
        ):
            (umbrella / name).mkdir(parents=True, exist_ok=True)
            paths[f"scaffold_{name.lower()}"] = umbrella / name
    return paths


def effective_logging_settings(workspace_root_path: Path) -> dict[str, Any]:
    """Merge settings.json logging block with mode-specific absolute log root."""
    from core.bot_logging import load_logging_settings

    base = load_logging_settings(workspace_root_path)
    base["root_dir"] = str(log_runtime_root(workspace_root_path))
    base["batman_mode"] = get_mode(workspace_root_path)
    return base

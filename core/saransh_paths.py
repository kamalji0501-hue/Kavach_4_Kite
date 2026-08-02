"""Mode-aware SARANSH / ATO analytics paths under data/{mode}/."""

from __future__ import annotations

from pathlib import Path

from core.batman_mode import data_root, deployments_dir


def ato_analytics_dir(root: Path | None = None) -> Path:
    return data_root(root) / "analytics" / "ato"


def saransh_analytics_dir(root: Path | None = None) -> Path:
    return data_root(root) / "analytics" / "saransh"


def ato_cycle_feed_path(root: Path | None = None) -> Path:
    return ato_analytics_dir(root) / "ato_cycle_feed.jsonl"


def ato_cycle_state_path(root: Path | None = None) -> Path:
    return ato_analytics_dir(root) / "ato_cycle_state.json"


def session_manifest_path(root: Path | None = None) -> Path:
    return data_root(root) / "analytics" / "session_manifest.json"


def legacy_telemetry_csv_path(root: Path | None = None) -> Path:
    """CSV telemetry until JSON feed validated (P1+)."""
    return ato_analytics_dir(root) / "ato_execution_telemetry.csv"


def deployment_dir(root: Path | None = None) -> Path:
    return deployments_dir(root)

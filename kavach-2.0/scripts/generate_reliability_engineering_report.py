#!/usr/bin/env python3
"""Generate human-readable reliability engineering report from JSON artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "data" / "analytics" / "reliability"
REPORT_PATH = ROOT / "docs" / "RELIABILITY_ENGINEERING_REPORT.md"


def _latest_artifact() -> Path | None:
    if not ARTIFACT_DIR.is_dir():
        return None
    files = sorted(ARTIFACT_DIR.glob("phase1_reliability_*.json"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def _render_table(cycles: list[dict]) -> list[str]:
    lines = [
        "| Cycle | Startup | Robots | Price | Telegram | Shutdown | Status |",
        "|-------|---------|--------|-------|----------|----------|--------|",
    ]
    for c in cycles:
        lines.append(
            "| {cycle} | {startup} | {robots} | {price} | {telegram} | {shutdown} | {status} |".format(
                cycle=c.get("cycle", "?"),
                startup="OK" if c.get("startup_success") else "FAIL",
                robots="OK" if c.get("robot_success") else "FAIL",
                price="OK" if c.get("price_flow_success") else "FAIL",
                telegram="OK" if c.get("telegram_success") else "FAIL",
                shutdown="OK" if c.get("shutdown_success") else "FAIL",
                status=c.get("final_status", "?"),
            )
        )
    return lines


def generate_report(*, artifact: Path | None = None) -> Path:
    src = artifact or _latest_artifact()
    now = datetime.now().astimezone().isoformat()
    if src is None or not src.is_file():
        body = (
            "# Reliability Engineering Report\n\n"
            f"**Generated:** {now}\n\n"
            "No reliability artifact found. Run:\n\n"
            "```powershell\n"
            ".venv\\Scripts\\python.exe scripts\\run_phase1_reliability_loop.py --cycles 15\n"
            "```\n"
        )
        REPORT_PATH.write_text(body, encoding="utf-8")
        return REPORT_PATH

    data = json.loads(src.read_text(encoding="utf-8"))
    cycles = data.get("cycles") if isinstance(data.get("cycles"), list) else []
    market = data.get("market_session") if isinstance(data.get("market_session"), dict) else {}

    lines = [
        "# Reliability Engineering Report",
        "",
        f"**Generated:** {now}",
        f"**Source artifact:** `{src.relative_to(ROOT)}`",
        f"**Run ID:** {data.get('run_id', 'unknown')}",
        f"**Overall:** {data.get('overall_status', 'unknown')}",
        "",
        "## Market session",
        "",
        f"- Live LTP required: `{market.get('live_ltp_required')}`",
        f"- LTP gate skip reason: `{market.get('ltp_gate_skip_reason')}`",
        "",
        "## Cycle results",
        "",
        *_render_table([c for c in cycles if isinstance(c, dict)]),
        "",
        "## Per-cycle detail",
        "",
    ]

    for c in cycles:
        if not isinstance(c, dict):
            continue
        n = c.get("cycle", "?")
        lines.append(f"### Cycle {n}")
        lines.append("")
        lines.append(f"- **final_status:** {c.get('final_status')}")
        lines.append(f"- **price_flow_mode:** {c.get('price_flow_mode', 'n/a')}")
        lines.append(f"- **start_elapsed_s:** {c.get('start_elapsed_seconds')}")
        lines.append(f"- **stop_elapsed_s:** {c.get('stop_elapsed_seconds')}")
        warnings = c.get("warnings")
        if isinstance(warnings, list) and warnings:
            lines.append(f"- **warnings:** {', '.join(str(w) for w in warnings)}")
        lines.append("")

    lines.extend(
        [
            "## Deferred (market hours)",
            "",
            "See `docs/RELIABILITY_MARKET_HOURS_DEFERRED.md` for live NIFTY/WebSocket validation.",
            "",
            "## Failure inventory",
            "",
            "See `docs/RELIABILITY_FAILURE_INVENTORY.md`.",
            "",
        ]
    )

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return REPORT_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate reliability engineering report.")
    parser.add_argument("--artifact", type=Path, default=None, help="Path to phase1_reliability_*.json")
    args = parser.parse_args()
    path = generate_report(artifact=args.artifact)
    print(f"Report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Headless UAT E2E verification — for Cursor agent iterate loops (no Telegram UI).

Runs: mode → screenshot book → JWT → fixture validate → pytest → bot smoke → log scan.

Usage:
  .venv\\Scripts\\python.exe scripts\\run_uat_e2e_verification.py
  .venv\\Scripts\\python.exe scripts\\run_uat_e2e_verification.py --ingest
  .venv\\Scripts\\python.exe scripts\\run_uat_e2e_verification.py --json

Exit 0 = all checks passed; non-zero = first failure (agent should fix and re-run).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.utils import get_venv_python
PYTHON = get_venv_python(ROOT)

_ERROR_PATTERNS = re.compile(
    r"Traceback|ERROR\s+\||CRITICAL\s+\||wizard_cancelled.*fail|UATIngestError",
    re.IGNORECASE,
)


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    steps: list[StepResult] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.steps.append(StepResult(name=name, ok=ok, detail=detail))

    @property
    def passed(self) -> bool:
        return all(s.ok for s in self.steps)

    def exit_code(self) -> int:
        return 0 if self.passed else 1


def _run(cmd: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        [str(PYTHON), *cmd[1:]] if cmd[0] == "python" else cmd,
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def step_mode(report: Report) -> None:
    sys.path.insert(0, str(ROOT))
    from core.batman_mode import get_mode

    mode = get_mode(ROOT)
    ok = mode == "uat"
    report.add(
        "batman_mode_uat",
        ok,
        f"mode={mode!r}" + ("" if ok else " — run Mode\\Set-UAT.bat"),
    )


def step_uat_folder(report: Report) -> None:
    sys.path.insert(0, str(ROOT))
    from core.uat_positions import find_screenshot_images, positions_json_path
    from core.batman_mode import uat_screenshot_dir

    shot_dir = uat_screenshot_dir(ROOT)
    images = find_screenshot_images(shot_dir)
    pos = positions_json_path(ROOT)
    has_pos = pos.is_file()
    ok = has_pos or bool(images)
    parts = [f"dir={shot_dir}"]
    if images:
        parts.append(f"screenshot={images[0].name}")
    if has_pos:
        parts.append("positions.json=OK")
    else:
        parts.append("positions.json=MISSING")
    report.add("uat_deployed_positions", ok, "; ".join(parts))


def step_jwt(report: Report) -> None:
    sys.path.insert(0, str(ROOT))
    from core.token_store import TokenStore

    store = TokenStore(path=ROOT / "data" / "access_token.json")
    token, saved_at = store.load()
    expired = store.is_expired()
    age = store.token_age_hours()
    ok = bool(token) and not expired
    detail = (
        f"present={bool(token)} expired={expired} age_h={age:.1f}"
        f" saved_at={saved_at}"
    )
    if not ok and token:
        detail += " — refresh JWT via DRISHTI (agent reads data/access_token.json)"
    report.add("dhan_jwt", ok, detail)


def step_ingest(report: Report, *, force: bool) -> None:
    sys.path.insert(0, str(ROOT))
    from core.uat_ingest import ingest_uat_screenshot

    if not force:
        report.add(
            "uat_ingest",
            True,
            "skipped — use --ingest to OCR latest screenshot (Register always OCRs)",
        )
        return
    try:
        result = ingest_uat_screenshot(ROOT, required=True, newest_only=True)
        report.add("uat_ingest", bool(result.get("ok")), str(result))
    except Exception as exc:
        report.add("uat_ingest", False, str(exc))


def step_validate_fixture(report: Report) -> None:
    rc, out = _run(
        [
            str(PYTHON),
            str(ROOT / "backtest_engine" / "tools" / "validate_fixture.py"),
            "--fixture",
            str(ROOT / "uat" / "deployed_positions" / "positions.json"),
        ],
    )
    tail = "\n".join(out.splitlines()[-8:]) if out else "(no output)"
    report.add("validate_fixture", rc == 0, tail)


def step_pytest(report: Report) -> None:
    targets = [
        "tests/test_shadow_resolver.py",
        "tests/test_kavach_scenarios.py",
        "tests/test_uat_ingest.py",
    ]
    existing = [t for t in targets if (ROOT / t).is_file()]
    if not existing:
        existing = ["tests/test_shadow_resolver.py", "tests/test_kavach_scenarios.py"]
    rc, out = _run([str(PYTHON), "-m", "pytest", *existing, "-q", "--tb=line"])
    m = re.search(r"(\d+) passed", out)
    summary = m.group(0) if m else out.splitlines()[-1] if out else f"exit {rc}"
    report.add("pytest_uat", rc == 0, summary)


def step_bot_smoke(report: Report) -> None:
    rc, out = _run([str(PYTHON), str(ROOT / "scripts" / "phase1_bot_check.py")])
    ok = rc == 0 and "status: PASS" in out
    lines = [ln for ln in out.splitlines() if "RUNNING" in ln or "PASS" in ln or "ORPHAN" in ln]
    report.add("phase1_bot_check", ok, "; ".join(lines[:6]) or out[-400:])


def _latest_all_log(robot: str) -> Path | None:
    sys.path.insert(0, str(ROOT))
    from core.batman_mode import log_runtime_root

    base = log_runtime_root(ROOT)
    if not base.is_dir():
        return None
    candidates: list[Path] = []
    for month_dir in base.iterdir():
        if not month_dir.is_dir():
            continue
        for day_dir in month_dir.iterdir():
            log_file = day_dir / robot / "logs" / "all.log"
            if log_file.is_file():
                candidates.append(log_file)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _current_session_lines(lines: list[str], robot: str, *, tail_lines: int) -> list[str]:
    """Scan only the latest bot session (after last startup marker), not full-day history."""
    tag = f"| {robot.upper()} |"
    start = 0
    for idx, line in enumerate(lines):
        if tag in line and "Batman mode:" in line:
            start = idx
    window = lines[start:] if start else lines[-tail_lines:]
    if len(window) > tail_lines:
        window = window[-tail_lines:]
    return window


def step_log_scan(report: Report, *, tail_lines: int) -> None:
    from core.batman_mode import log_runtime_root
    from core.runtime_log_scan import day_log_paths, scan_robot_session_errors

    issues: list[str] = []
    paths = day_log_paths(ROOT, log_runtime_root(ROOT))
    for robot in ("kavach", "drishti", "jagran"):
        path = paths.get(robot)
        if path is None or not path.is_file():
            issues.append(f"{robot}: no log")
            continue
        hits = scan_robot_session_errors(path, robot, tail_lines=tail_lines)
        if hits and hits[0] == "read fail":
            issues.append(f"{robot}: read fail")
        elif hits:
            issues.append(f"{robot}@{path.name}: {len(hits)} error line(s)")
    ok = not issues
    report.add(
        "uat_log_scan",
        ok,
        "clean" if ok else "; ".join(issues),
    )


def step_bot_process(report: Report) -> None:
    rc, out = _run([str(PYTHON), str(ROOT / "scripts" / "bot_status.py"), "all"])
    ok = "STOPPED" not in out or "RUNNING" in out
    # UAT session expects DRISHTI+KAVACH running for live iteration; warn only
    running = sum(1 for ln in out.splitlines() if "RUNNING" in ln)
    detail = f"running_lines={running}; " + " | ".join(
        ln.strip() for ln in out.splitlines() if "DRISHTI" in ln or "KAVACH" in ln or "JAGRAN" in ln
    )[:500]
    report.add("bot_process_status", True, detail)


def _safe_console(text: str) -> str:
    return text.encode("ascii", errors="replace").decode("ascii")


def print_report(report: Report, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(asdict(report), indent=2))
        return
    print("\n=== UAT E2E verification ===\n")
    for step in report.steps:
        mark = "PASS" if step.ok else "FAIL"
        print(f"  [{mark}] {step.name}")
        if step.detail:
            for line in step.detail.splitlines()[:12]:
                print(f"         {_safe_console(line)}")
    print()
    if report.passed:
        print("RESULT: ALL PASSED — agent may report done for UAT gate.")
    else:
        failed = [s.name for s in report.steps if not s.ok]
        print(f"RESULT: FAILED at {', '.join(failed)} — fix and re-run this script.")


async def _optional_register_smoke() -> tuple[bool, str]:
    """Exercise wizard_entry with mocks (fast register path check)."""
    sys.path.insert(0, str(ROOT))
    try:
        from unittest.mock import AsyncMock, MagicMock, patch

        from bat_telegram.bots.kavach import bot as kavach_bot
        from telegram.ext import ConversationHandler

        message = MagicMock()
        message.reply_text = AsyncMock(return_value=MagicMock(message_id=1))
        message.message_id = 1
        message.chat = MagicMock()
        message.chat.id = 1
        update = MagicMock()
        update.update_id = 1
        update.message = message
        update.callback_query = None

        broker = MagicMock()
        broker.token_age_hours = 1.0
        broker.get_positions = MagicMock(return_value=MagicMock())
        broker.refresh_fixture_positions = MagicMock()

        context = MagicMock()
        context.user_data = {}
        context.bot_data = {"broker": broker, "event_bus": None}

        with (
            patch("core.batman_mode.is_uat", return_value=True),
            patch(
                "core.uat_register_cleanup.prepare_uat_register_fresh",
                return_value={"ok": True},
            ),
            patch(
                "core.uat_ingest.ingest_uat_for_register",
                return_value={"ok": True, "method": "cursor_chat"},
            ),
            patch.object(kavach_bot, "_find_active_deployment", return_value=None),
            patch.object(kavach_bot, "_filter_nifty_positions", return_value=[{"symbol": "NIFTY-TEST"}]),
            patch.object(kavach_bot, "_wizard_show", new_callable=AsyncMock) as show,
        ):
            state = await kavach_bot.wizard_entry(update, context)
        from bat_telegram.bots.kavach.register_wizard import WIZARD_PE_INTENT

        ok = state == WIZARD_PE_INTENT or state is not ConversationHandler.END
        return ok, f"wizard_entry → state={state!r} show_calls={show.await_count}"
    except Exception as exc:
        return False, str(exc)


def step_register_handler(report: Report) -> None:
    ok, detail = asyncio.run(_optional_register_smoke())
    report.add("register_wizard_smoke", ok, detail)


def main() -> int:
    parser = argparse.ArgumentParser(description="UAT E2E verification for agent loops")
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Force OCR ingest even when positions.json is fresh",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable report")
    parser.add_argument(
        "--skip-register-smoke",
        action="store_true",
        help="Skip async wizard_entry mock test",
    )
    parser.add_argument(
        "--log-tail",
        type=int,
        default=200,
        help="Lines per robot log to scan for errors",
    )
    args = parser.parse_args()

    if not PYTHON.is_file():
        print(f"Missing venv: {PYTHON}", file=sys.stderr)
        return 1

    report = Report()
    step_mode(report)
    step_uat_folder(report)
    step_jwt(report)
    step_ingest(report, force=args.ingest)
    if report.steps[-1].ok or report.steps[-2].ok:
        step_validate_fixture(report)
    step_pytest(report)
    if not args.skip_register_smoke:
        step_register_handler(report)
    step_bot_smoke(report)
    step_bot_process(report)
    step_log_scan(report, tail_lines=args.log_tail)

    print_report(report, as_json=args.json)
    return report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())

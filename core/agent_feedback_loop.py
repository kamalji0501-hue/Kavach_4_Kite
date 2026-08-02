"""Agent feedback loop — orchestrate diagnose → test → logs → report (iterate until stable)."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.runtime_log_scan import day_log_paths, scan_robot_session_errors
from core.utils import get_venv_python

_IST = ZoneInfo("Asia/Kolkata")
_ROOT = Path(__file__).resolve().parents[1]
_PYTHON = get_venv_python(_ROOT)
_OUT_DIR = _ROOT / "data" / "analytics" / "feedback_loop"
_START_BATS = _ROOT / "Execution" / "Start Bots"


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str
    duration_s: float = 0.0


@dataclass
class CycleResult:
    cycle: int
    steps: list[StepResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(s.ok for s in self.steps)


def _run(cmd: list[str], *, timeout: int = 600) -> tuple[int, str]:
    if not _PYTHON.is_file():
        return 1, f"missing venv: {_PYTHON}"
    proc = subprocess.run(
        cmd,
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def restart_bot(robot: str, *, wait_cache: bool = False) -> StepResult:
    """Stop then start one Phase 1 bot via official launcher (.sh on Linux, .bat on Windows)."""
    import sys

    robot = robot.lower()
    stop_script = _ROOT / "scripts" / f"stop_{robot}.py"
    title = robot.title()
    start_sh = _START_BATS / f"start {title}.sh"
    start_bat = _START_BATS / f"start {title}.bat"
    launcher = start_sh if start_sh.is_file() else start_bat
    if not stop_script.is_file() or not launcher.is_file():
        return StepResult(f"restart_{robot}", False, f"missing launcher for {robot}")
    t0 = time.perf_counter()
    _run([str(_PYTHON), str(stop_script), "--silent"], timeout=120)
    _run([str(_PYTHON), str(_ROOT / "scripts" / "ensure_bot_stopped.py"), robot, "--force"], timeout=60)
    if sys.platform == "win32":
        subprocess.Popen(
            ["cmd", "/c", str(launcher)],
            cwd=str(_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.Popen(
            ["bash", str(launcher)],
            cwd=str(_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    from core.bot_process_status import BotRunState, classify_bot

    ok = False
    for _ in range(45):
        time.sleep(2)
        status = classify_bot(robot, root=_ROOT)
        if status.state is BotRunState.RUNNING:
            ok = True
            break
    detail = f"state={classify_bot(robot, root=_ROOT).state.name}"
    if wait_cache and ok:
        from core.feed_recovery import is_nifty_cache_trading_ready

        for _ in range(30):
            ready, age = is_nifty_cache_trading_ready()
            if ready:
                detail += f" cache_ready age={age:.0f}s"
                break
            time.sleep(2)
        else:
            ok = False
            detail += " cache_not_ready_after_restart"
    return StepResult(f"restart_{robot}", ok, detail, duration_s=time.perf_counter() - t0)


def restart_bots_cascade(bots: tuple[str, ...]) -> list[StepResult]:
    """Restart bots in order; DRISHTI waits for LTP cache, then restarts dependents."""
    results: list[StepResult] = []
    ordered = list(bots)
    if "drishti" in ordered:
        ordered.remove("drishti")
        results.append(restart_bot("drishti", wait_cache=True))
        for dep in ("kavach", "saransh"):
            if dep in bots:
                results.append(restart_bot(dep))
                if dep in ordered:
                    ordered.remove(dep)
    for bot in ordered:
        results.append(restart_bot(bot))
    return results


def step_session_log_scan(*, tail_lines: int = 400, when: datetime | None = None) -> StepResult:
    """Scan latest bot session logs for ERROR patterns (mode-aware log root)."""
    t0 = time.perf_counter()
    from core.batman_mode import log_runtime_root

    paths = day_log_paths(_ROOT, log_runtime_root(_ROOT), when=when)
    issues: list[str] = []
    for robot, path in paths.items():
        hits = scan_robot_session_errors(path, robot, tail_lines=tail_lines)
        if hits and hits[0] == "read fail":
            issues.append(f"{robot}: read fail")
        elif hits:
            issues.append(f"{robot}: {len(hits)} error line(s) in current session")
    ok = not issues
    return StepResult(
        "session_log_scan",
        ok,
        "clean" if ok else "; ".join(issues),
        duration_s=time.perf_counter() - t0,
    )


def run_step(name: str, cmd: list[str], *, timeout: int = 600, retries: int = 1) -> StepResult:
    last: StepResult | None = None
    for attempt in range(max(1, retries)):
        t0 = time.perf_counter()
        rc, out = _run(cmd, timeout=timeout)
        tail = out[-1200:] if len(out) > 1200 else out
        ok = rc == 0
        if name == "uat_e2e":
            ok = "ALL PASSED" in out or "RESULT: ALL PASSED" in out
        if name == "phase1_check":
            ok = rc == 0 and "FAIL" not in out.upper().split("STATUS:")[-1][:80]
        last = StepResult(name, ok, tail or f"exit {rc}", duration_s=time.perf_counter() - t0)
        if ok:
            return last
        if attempt + 1 < retries:
            time.sleep(5)
    assert last is not None
    return last


def run_cycle(
    cycle: int,
    *,
    restart_bots: tuple[str, ...] = (),
    skip_uat_e2e: bool = False,
) -> CycleResult:
    result = CycleResult(cycle=cycle)
    if restart_bots:
        result.steps.extend(restart_bots_cascade(restart_bots))
        time.sleep(5)
    diag_retries = 3 if restart_bots and cycle == 1 else 1
    for robot in ("drishti", "kavach", "jagran"):
        result.steps.append(
            run_step(
                f"diagnose_{robot}",
                [str(_PYTHON), str(_ROOT / "scripts" / "diagnose_robot.py"), robot],
                retries=diag_retries,
            )
        )
    result.steps.append(
        run_step("audit_tokens", [str(_PYTHON), str(_ROOT / "scripts" / "audit_bot_tokens.py")])
    )
    result.steps.append(
        run_step("phase1_check", [str(_PYTHON), str(_ROOT / "scripts" / "phase1_bot_check.py")])
    )
    result.steps.append(
        run_step(
            "pytest_core",
            [
                str(_PYTHON),
                "-m",
                "pytest",
                "tests/test_feed_recovery.py",
                "tests/test_incident_knowledge.py",
                "tests/test_agent_feedback_loop.py",
                "tests/test_runtime_log_scan.py",
                "-q",
                "--tb=line",
            ],
            timeout=180,
        )
    )
    if not skip_uat_e2e:
        result.steps.append(
            run_step(
                "uat_e2e",
                [str(_PYTHON), str(_ROOT / "scripts" / "run_uat_e2e_verification.py")],
                timeout=300,
            )
        )
    result.steps.append(step_session_log_scan())
    result.steps.append(
        run_step("incident_report", [str(_PYTHON), str(_ROOT / "scripts" / "incident_mgmt.py"), "report"])
    )
    result.steps.append(
        run_step(
            "verify_incident_fixes",
            [str(_PYTHON), str(_ROOT / "scripts" / "verify_incident_fixes.py")],
            timeout=300,
        )
    )
    try:
        from core.incident_excel_export import default_xlsx_path, export_incident_registry_xlsx

        export_incident_registry_xlsx()
        result.steps.append(StepResult("incident_excel", True, str(default_xlsx_path()), 0.5))
    except Exception as exc:
        result.steps.append(StepResult("incident_excel", False, str(exc), 0.0))
    return result


def write_latest_report(
    cycles: list[CycleResult],
    *,
    run_id: str,
    elapsed_s: float,
) -> Path:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=_IST)
    log_path = _OUT_DIR / now.strftime("%Y-%m") / now.strftime("%Y-%m-%d") / f"feedback_{run_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        f"# Agent Feedback Loop — {now.strftime('%Y-%m-%d %H:%M:%S IST')}",
        "",
        f"run_id: `{run_id}`",
        f"cycles: {len(cycles)}",
        f"elapsed: {elapsed_s:.1f}s",
        f"result: **{'PASS' if cycles and cycles[-1].passed else 'FAIL'}**",
        "",
    ]
    for cr in cycles:
        lines.append(f"## Cycle {cr.cycle} — {'PASS' if cr.passed else 'FAIL'}")
        lines.append("")
        for step in cr.steps:
            mark = "PASS" if step.ok else "FAIL"
            lines.append(f"- [{mark}] `{step.name}` ({step.duration_s:.1f}s)")
            if not step.ok:
                preview = step.detail.replace("\n", " ")[:240]
                lines.append(f"  - {preview}")
        lines.append("")

    md_path = _OUT_DIR / "LATEST_RUN.md"
    body = "\n".join(lines)
    md_path.write_text(body, encoding="utf-8")
    log_path.write_text(body, encoding="utf-8")
    return md_path


def run_feedback_loop(
    *,
    max_cycles: int = 4,
    restart_bots: tuple[str, ...] = (),
    skip_uat_e2e: bool = False,
    stop_on_pass: bool = True,
) -> int:
    """Run up to ``max_cycles`` diagnose/test iterations; return 0 when stable."""
    run_id = datetime.now(tz=_IST).strftime("%Y%m%d_%H%M%S")
    t0 = time.perf_counter()
    cycles: list[CycleResult] = []
    restart_once = restart_bots

    for cycle in range(1, max_cycles + 1):
        cr = run_cycle(
            cycle,
            restart_bots=restart_once if cycle == 1 else (),
            skip_uat_e2e=skip_uat_e2e,
        )
        cycles.append(cr)
        write_latest_report(cycles, run_id=run_id, elapsed_s=time.perf_counter() - t0)
        if cr.passed and stop_on_pass:
            return 0
        if cycle < max_cycles:
            time.sleep(5)

    return 0 if cycles and cycles[-1].passed else 1

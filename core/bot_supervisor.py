"""Phase 1 bot supervisor — spawn and stop run_*.py without .bat chains."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from core.bot_lifecycle import reconcile_all
from core.bot_process_status import PHASE1_BOTS, BotRunState, classify_bot
from core.startup_gates import wait_bot_running, wait_drishti_ltp_ready

ROOT = Path(__file__).resolve().parents[1]

START_ORDER = ("drishti", "kavach2", "jagran")
OPTIONAL_ORDER = ("saransh",)

_CREATE_NEW_CONSOLE = 0x00000010


@dataclass
class SpawnedBot:
    robot: str
    pid: int
    script: str


def _python_exe(root: Path) -> Path:
    from core.utils import get_venv_python

    return get_venv_python(root)


def _runner_script(root: Path, robot: str) -> Path:
    return root / PHASE1_BOTS[robot]["runner"]


def supervisor_state_path(root: Path) -> Path:
    return root / "data" / "supervisor" / "state.json"


def _load_state(root: Path) -> dict:
    path = supervisor_state_path(root)
    if not path.exists():
        return {"children": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {"children": {}}
    except (json.JSONDecodeError, OSError):
        return {"children": {}}


def _save_state(root: Path, children: dict[str, int]) -> None:
    path = supervisor_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"children": children, "updated_at": time.time()}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _spawn_env() -> dict[str, str]:
    env = os.environ.copy()
    env["BATMAN_LAUNCHED_VIA_BAT"] = "1"
    env["BATMAN_SUPERVISOR"] = "1"
    return env


def spawn_bot(robot: str, *, root: Path | None = None, new_console: bool = True) -> SpawnedBot:
    """Start one bot as a direct Python child (no start .bat)."""
    base = root or ROOT
    key = robot.lower()
    if key not in PHASE1_BOTS:
        raise ValueError(f"Unknown robot: {key}")

    py = _python_exe(base)
    script = _runner_script(base, key)
    if not py.is_file():
        raise FileNotFoundError(f"Python venv not found: {py}")
    if not script.is_file():
        raise FileNotFoundError(f"Runner not found: {script}")

    flags = (
        getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        if new_console and sys.platform == "win32"
        else 0
    )
    popen_kwargs: dict = {
        "cwd": str(base),
        "env": _spawn_env(),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = flags
    else:
        # Detach from parent terminal so bots survive launcher exit (no SIGHUP).
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen([str(py), str(script.name)], **popen_kwargs)
    return SpawnedBot(robot=key, pid=proc.pid, script=str(script.name))


def stop_tracked_children(*, root: Path | None = None) -> None:
    """Terminate PIDs recorded by supervisor state file."""
    base = root or ROOT
    state = _load_state(base)
    raw_children = state.get("children")
    children: dict[str, object] = raw_children if isinstance(raw_children, dict) else {}
    for _robot, pid in list(children.items()):
        if not isinstance(pid, (int, float, str)):
            continue
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            continue
        if pid_int <= 0:
            continue
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid_int), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            try:
                os.kill(pid_int, 9)
            except OSError:
                pass
    _save_state(base, {})


def stop_all_bots(
    *,
    root: Path | None = None,
    close_launcher_windows: bool = False,
) -> int:
    """Stop via supervisor state + standard stop scripts."""
    from scripts.phase1_stop_all import run_stop_all

    base = root or ROOT
    stop_tracked_children(root=base)
    reconcile_all(root=base, kill_orphans=True)
    return run_stop_all(silent=not close_launcher_windows, popup_on_failure=False)


def start_all_bots(
    *,
    root: Path | None = None,
    force: bool = False,
    wait_seconds: float = 120.0,
    new_console: bool = True,
    log=None,
) -> int:
    """Reconcile → stop → spawn DRISHTI → KAVACH2 → JAGRAN (+ optional SARANSH)."""
    base = root or ROOT

    def _log(msg: str, *args) -> None:
        if log is not None:
            text = msg % args if args else msg
            log.info(text)

    _log("Supervisor: reconcile all bots")
    for result in reconcile_all(root=base, kill_orphans=force):
        _log("  %s: %s -> %s", result.robot.upper(), result.action, result.state.value)

    _log("Supervisor: stop all (clean slate)")
    stop_rc = stop_all_bots(root=base)
    if stop_rc != 0:
        _log("Supervisor: stop-all failed (%s)", stop_rc)
        return 1

    children: dict[str, int] = {}
    _log("Supervisor: spawn DRISHTI")
    spawned = spawn_bot("drishti", root=base, new_console=new_console)
    children["drishti"] = spawned.pid
    _save_state(base, children)

    if not wait_bot_running("drishti", timeout_seconds=wait_seconds * 0.5, root=base):
        _log("Supervisor: DRISHTI did not reach RUNNING — aborting start")
        return 1
    # Repeated full-stop/full-start sweeps can leave DRISHTI needing longer than 90s
    # to publish the first fresh cache write, so keep the LTP gate aligned with the
    # overall startup budget instead of failing early on a stale pre-start snapshot.
    ltp_timeout = max(90.0, min(wait_seconds, 180.0))
    ltp_ok, ltp_detail = wait_drishti_ltp_ready(timeout_seconds=ltp_timeout, root=base)
    _log("Supervisor: LTP gate %s (%s)", "OK" if ltp_ok else "FAIL", ltp_detail)
    if not ltp_ok and not any(
        skip in ltp_detail for skip in ("off_calendar_day", "pre_market", "post_market")
    ):
        _log("Supervisor: LTP gate failed during market session — aborting start")
        return 1

    _log("Supervisor: spawn KAVACH 2.0")
    spawned = spawn_bot("kavach2", root=base, new_console=new_console)
    children["kavach2"] = spawned.pid
    _save_state(base, children)
    wait_bot_running("kavach2", timeout_seconds=60.0, root=base)

    _log("Supervisor: spawn JAGRAN")
    spawned = spawn_bot("jagran", root=base, new_console=new_console)
    children["jagran"] = spawned.pid
    _save_state(base, children)
    wait_bot_running("jagran", timeout_seconds=45.0, root=base)

    from core.optional_bot_startup import optional_bot_enabled

    for optional in OPTIONAL_ORDER:
        ok, reason = optional_bot_enabled(optional, root=base)
        if not ok:
            _log("Supervisor: skip %s (%s)", optional.upper(), reason)
            continue
        _log("Supervisor: spawn %s", optional.upper())
        spawned = spawn_bot(optional, root=base, new_console=new_console)
        children[optional] = spawned.pid
        _save_state(base, children)
        wait_bot_running(optional, timeout_seconds=45.0, root=base)

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        running = all(
            classify_bot(r, root=base).state is BotRunState.RUNNING for r in START_ORDER
        )
        if running:
            _log("Supervisor: all core bots RUNNING")
            return 0
        time.sleep(5.0)

    _log("Supervisor: timeout waiting for RUNNING")
    return 2

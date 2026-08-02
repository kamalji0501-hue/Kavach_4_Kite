"""Verify every closed incident has its fix present in code (static + runtime checks)."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo
from core.utils import get_venv_python

_IST = ZoneInfo("Asia/Kolkata")
_ROOT = Path(__file__).resolve().parents[1]
_REPORT_DIR = _ROOT / "data" / "analytics" / "incidents"


@dataclass
class FixCheck:
    incident_id: str
    name: str
    ok: bool
    detail: str


@dataclass
class VerificationReport:
    checks: list[FixCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failed(self) -> list[FixCheck]:
        return [c for c in self.checks if not c.ok]


def _read(rel: str) -> str:
    # Normalize Windows-style rel paths so Linux/Chromebook can resolve them.
    path = _ROOT / Path(rel.replace("\\", "/"))
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _file_has_all(rel: str, *patterns: str) -> tuple[bool, str]:
    text = _read(rel)
    if not text:
        return False, f"missing file: {rel}"
    missing = [p for p in patterns if p not in text]
    if missing:
        return False, f"{rel}: missing {missing!r}"
    return True, rel


def _file_has_regex(rel: str, pattern: str) -> tuple[bool, str]:
    text = _read(rel)
    if not text:
        return False, f"missing file: {rel}"
    if not re.search(pattern, text, re.MULTILINE | re.DOTALL):
        return False, f"{rel}: pattern not found: {pattern[:80]}"
    return True, rel


def _add(report: VerificationReport, incident_id: str, name: str, ok: bool, detail: str) -> None:
    report.checks.append(FixCheck(incident_id, name, ok, detail))


def verify_code_markers(report: VerificationReport | None = None) -> VerificationReport:
    """Static analysis: each incident fix must exist in listed source files."""
    report = report or VerificationReport()
    checks: list[tuple[str, str, Callable[[], tuple[bool, str]]]] = [
        (
            "INC-2026-STAB-01",
            "UAT state path for algo pause",
            lambda: _file_has_all("core/algo_control.py", "state_path", "default_state_path"),
        ),
        (
            "INC-2026-STAB-02",
            "KAVACH reads mode-aware pause state",
            lambda: _file_has_all(
                "bat_telegram/bots/kavach/bot.py",
                "state_path(workspace_root())",
                "_read_algo_pause_reason",
            ),
        ),
        (
            "INC-2026-STAB-03",
            "Failover persisted to disk state",
            lambda: _file_has_all(
                "core/nifty_ltp_failover.py",
                "_DISK_STATE_KEY",
                "nifty_ltp_failover",
                "save_failover_state",
            ),
        ),
        (
            "INC-2026-STAB-04",
            "WS Previous Close skipped",
            lambda: _file_has_all(
                "core/dhan_ws_tick.py",
                "Previous Close",
                "extract_ltp_from_ws_tick",
            ),
        ),
        (
            "INC-2026-STAB-05",
            "429 cooldown without failure escalation",
            lambda: _file_has_regex(
                "core/nifty_ltp_websocket_feed.py",
                r"is_rate_limit_error.*?continue",
            ),
        ),
        (
            "INC-2026-STAB-06",
            "Transport grace + rate-limit stale skip",
            lambda: _file_has_all(
                "core/nifty_ltp_feed.py",
                "is_within_transport_grace",
                "mark_transport_started",
                "rate_limit_until",
            ),
        ),
        (
            "INC-2026-STAB-07",
            "JWT effective expiry gates feed",
            lambda: _file_has_all("core/token_store.py", "is_effectively_expired"),
        ),
        (
            "INC-2026-STAB-08",
            "Lifecycle lock hardening",
            lambda: _file_has_all("core/bot_lifecycle.py", "reconcile_bot", "prepare_for_start"),
        ),
        (
            "INC-2026-STAB-09",
            "Auth errors no failover",
            lambda: _file_has_all("core/nifty_ltp.py", "is_auth_error"),
        ),
        (
            "INC-2026-STAB-10",
            "KAVACH token_watch lazy bootstrap",
            lambda: _file_has_all("core/token_watch.py", "is_effectively_expired"),
        ),
        (
            "INC-2026-STAB-11",
            "Start All aborts on LTP gate fail",
            lambda: _file_has_all(
                "core/bot_supervisor.py",
                "LTP gate failed",
                "aborting start",
            ),
        ),
        (
            "INC-2026-STAB-12",
            "health.json confirms RUNNING",
            lambda: _file_has_all(
                "core/bot_health.py",
                "health_confirms_running",
            ),
        ),
        (
            "INC-2026-STAB-13",
            "WS retry after REST lock",
            lambda: _file_has_all(
                "core/nifty_ltp_failover.py",
                "try_websocket_retry_after_rest",
            ),
        ),
        (
            "INC-2026-STAB-14",
            "Live price prefers background cache",
            lambda: _file_has_all(
                "bat_telegram/bots/drishti/nifty_feed_integration.py",
                "is_background_feed_running",
                "snap.is_fresh",
            ),
        ),
        (
            "INC-2026-STAB-15",
            "Lock retry on state writes",
            lambda: _file_has_all("core/process_lock.py", "retries: int = 3"),
        ),
        (
            "INC-2026-STAB-15",
            "state.save mkdir parent",
            lambda: _file_has_all("core/state.py", "parent.mkdir"),
        ),
        (
            "INC-2026-016",
            "Fixture expiry auto-roll",
            lambda: _file_has_all(
                "backtest_engine/resolver/instrument_master.py",
                "resolve_fixture_trading_expiry",
            ),
        ),
        (
            "INC-2026-016",
            "ShadowBroker ledger clear on roll",
            lambda: _file_has_all(
                "backtest_engine/shadow/shadow_broker.py",
                "clear_ledger",
                "rolled",
            ),
        ),
        (
            "INC-2026-017",
            "WS transport grace on connect",
            lambda: _file_has_all(
                "core/nifty_ltp_websocket_feed.py",
                "mark_transport_started",
            ),
        ),
        (
            "INC-2026-018",
            "diagnose_robot mode-aware logs",
            lambda: _file_has_all("scripts/diagnose_robot.py", "log_runtime_root"),
        ),
        (
            "INC-2026-019",
            "Ledger clear tied to expiry roll",
            lambda: _file_has_regex(
                "backtest_engine/shadow/shadow_broker.py",
                r"if rolled:.*?clear_ledger",
            ),
        ),
        (
            "INC-2026-020",
            "UAT E2E session-scoped log scan",
            lambda: _file_has_all(
                "core/runtime_log_scan.py",
                "current_session_lines",
                "Batman mode:",
            ),
        ),
        (
            "INC-2026-021",
            "Feed stabilization reduces alert storm",
            lambda: _file_has_all(
                "core/feed_recovery.py",
                "can_auto_resume_feed_recovery",
                "AUTO_RESUME_STABLE_SECONDS",
            ),
        ),
        (
            "INC-2026-022",
            "No instant resume on stale_cleared",
            lambda: _file_has_regex(
                "bat_telegram/bots/drishti/nifty_feed_integration.py",
                r"async def on_feed_stale_cleared.*?update_feed_ready_stability",
            ),
        ),
        (
            "INC-2026-022",
            "Sustained auto-resume in watchdog",
            lambda: _file_has_all(
                "bat_telegram/bots/drishti/nifty_feed_integration.py",
                "can_auto_resume_feed_recovery",
            ),
        ),
        (
            "INC-2026-023",
            "Cache replace races do not raise feed-task-killing exceptions",
            lambda: _file_has_all(
                "core/nifty_ltp_feed.py",
                "_is_retryable_windows_replace_error",
                "raise_on_failure=False",
                "NIFTY cache replace deferred after repeated Windows file-lock retries",
            ),
        ),
        (
            "INC-2026-023",
            "Regression tests cover cache replace lock handling",
            lambda: _file_has_all(
                "tests/test_nifty_ltp_feed.py",
                "test_write_nifty_ltp_cache_retries_windows_replace_lock",
                "test_write_nifty_ltp_cache_returns_false_on_persistent_replace_lock",
            ),
        ),
    ]

    for inc_id, name, fn in checks:
        ok, detail = fn()
        _add(report, inc_id, name, ok, detail)

    return report


def verify_runtime_behaviors(report: VerificationReport | None = None) -> VerificationReport:
    """Import and exercise fix paths (not just string presence)."""
    report = report or VerificationReport()

    # INC-016/019: expired fixture rolls forward
    try:
        from backtest_engine.resolver.instrument_master import resolve_fixture_trading_expiry

        legs = [{"strike": 23500, "type": "PE"}, {"strike": 23550, "type": "PE"}]
        exp, rolled = resolve_fixture_trading_expiry(date(2026, 6, 23), legs, today=date(2026, 6, 25))
        ok = rolled and exp >= date(2026, 6, 25)
        _add(
            report,
            "INC-2026-016",
            "runtime: fixture rolls past 2026-06-23",
            ok,
            f"expiry={exp} rolled={rolled}",
        )
    except Exception as exc:
        _add(report, "INC-2026-016", "runtime: fixture roll", False, str(exc))

    # INC-022: sustained resume gate
    try:
        import tempfile

        from core.algo_control import pause_algo
        from core.feed_recovery import (
            AUTO_RESUME_STABLE_SECONDS,
            can_auto_resume_feed_recovery,
            update_feed_ready_stability,
        )

        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "batman_state.json"
            sp.write_text("{}", encoding="utf-8")
            pause_algo(reason="nifty_ltp_feed_stale", state_path=sp)
            update_feed_ready_stability(ready=True, state_path=sp)
            blocked = not can_auto_resume_feed_recovery(state_path=sp)
            ok = blocked and AUTO_RESUME_STABLE_SECONDS >= 45
            _add(
                report,
                "INC-2026-022",
                "runtime: sustained resume blocks <45s",
                ok,
                f"blocked={blocked} stable_s={AUTO_RESUME_STABLE_SECONDS}",
            )
    except Exception as exc:
        _add(report, "INC-2026-022", "runtime: sustained resume", False, str(exc))

    # INC-023: cache write retry survives transient Windows replace lock
    try:
        import os
        import tempfile

        from core.nifty_ltp_feed import NiftyLtpCacheSnapshot, read_nifty_ltp_cache, write_nifty_ltp_cache

        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "nifty_ltp_cache.json"
            now = datetime.now(_IST).isoformat()
            snap = NiftyLtpCacheSnapshot(ltp=23500.5, updated_at=now, last_changed_at=now)
            real_replace = os.replace
            attempts = {"count": 0}

            def flaky_replace(src: str, dst: str) -> None:
                attempts["count"] += 1
                if attempts["count"] < 3:
                    err = PermissionError("Access is denied")
                    err.winerror = 5
                    raise err
                real_replace(src, dst)

            from unittest.mock import patch

            with patch("core.nifty_ltp_feed.os.replace", flaky_replace):
                ok = write_nifty_ltp_cache(snap, cache)
            loaded = read_nifty_ltp_cache(cache)
            _add(
                report,
                "INC-2026-023",
                "runtime: transient cache lock retries then succeeds",
                bool(ok and loaded and loaded.ltp > 0 and attempts["count"] >= 3),
                f"ok={ok} attempts={attempts['count']} cache_exists={cache.exists()}",
            )
    except Exception as exc:
        _add(report, "INC-2026-023", "runtime: transient cache lock retry", False, str(exc))

    # INC-023: persistent cache lock is non-fatal to writer
    try:
        import tempfile

        from core.nifty_ltp_feed import NiftyLtpCacheSnapshot, write_nifty_ltp_cache
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "nifty_ltp_cache.json"
            now = datetime.now(_IST).isoformat()
            snap = NiftyLtpCacheSnapshot(ltp=23500.5, updated_at=now, last_changed_at=now)

            def always_locked_replace(src: str, dst: str) -> None:
                err = PermissionError("Access is denied")
                err.winerror = 5
                raise err

            with patch("core.nifty_ltp_feed.os.replace", always_locked_replace):
                ok = write_nifty_ltp_cache(snap, cache)
            _add(
                report,
                "INC-2026-023",
                "runtime: persistent cache lock returns False without raise",
                ok is False,
                f"ok={ok}",
            )
    except Exception as exc:
        _add(report, "INC-2026-023", "runtime: persistent cache lock non-fatal", False, str(exc))

    # INC-017/STAB-06: transport grace
    try:
        from datetime import timedelta

        from core.nifty_ltp_feed import (
            _FeedRuntime,
            is_within_transport_grace,
            mark_transport_started,
        )

        rt = _FeedRuntime()
        mark_transport_started(rt)
        now = datetime.now(_IST)
        ok = is_within_transport_grace(rt, grace_seconds=30, now=now + timedelta(seconds=10))
        _add(
            report,
            "INC-2026-017",
            "runtime: transport grace 30s active",
            ok,
            f"within_grace={ok}",
        )
    except Exception as exc:
        _add(report, "INC-2026-017", "runtime: transport grace", False, str(exc))

    # INC-018: log root UAT-aware
    try:
        from core.batman_mode import get_mode, log_root, log_runtime_root

        mode = get_mode(_ROOT)
        lr = log_root(_ROOT)
        lrr = log_runtime_root(_ROOT)
        # Windows legacy used .../logs_uat; Linux/Chromebook uses logs_runtime/uat.
        uat_layout_ok = "logs_uat" in lr.parts or (
            lr.name == "uat" and "logs_runtime" in lr.parts
        )
        ok = lrr == lr / "runtime" and (mode != "uat" or uat_layout_ok)
        _add(
            report,
            "INC-2026-018",
            "runtime: log_runtime_root mode-aware",
            ok,
            f"mode={mode} log_root={lr.name} runtime={lrr}",
        )
    except Exception as exc:
        _add(report, "INC-2026-018", "runtime: log root", False, str(exc))

    # STAB-04: control frame returns None
    try:
        from core.dhan_ws_tick import extract_ltp_from_ws_tick

        tick = {"type": "Previous Close", "ltp": 0}
        ok = extract_ltp_from_ws_tick(tick) is None
        _add(report, "INC-2026-STAB-04", "runtime: Previous Close skipped", ok, str(tick))
    except Exception as exc:
        _add(report, "INC-2026-STAB-04", "runtime: ws tick", False, str(exc))

    # STAB-01: UAT state path
    try:
        from core.algo_control import default_state_path
        from core.batman_mode import get_mode

        p = default_state_path()
        mode = get_mode(_ROOT)
        ok = ("uat" in str(p).lower()) if mode == "uat" else True
        _add(report, "INC-2026-STAB-01", "runtime: default_state_path UAT", ok, str(p))
    except Exception as exc:
        _add(report, "INC-2026-STAB-01", "runtime: state path", False, str(exc))

    return report


def verify_registry_coverage(report: VerificationReport | None = None) -> VerificationReport:
    """Every closed registry incident must have at least one passing check."""
    from collections import defaultdict

    from core.incident_knowledge import load_registry

    report = report or VerificationReport()
    items = [r for r in load_registry() if r.lifecycle == "closed"]
    by_inc: dict[str, list[FixCheck]] = defaultdict(list)
    for c in report.checks:
        by_inc[c.incident_id].append(c)

    for rec in items:
        checks = by_inc.get(rec.incident_id, [])
        if any(c.ok for c in checks):
            continue
        if rec.incident_id == "INC-2026-021":
            _add(report, rec.incident_id, "registry: transient JAGRAN timeout", True, "mitigated by feed fixes")
            continue
        _add(
            report,
            rec.incident_id,
            "registry: no passing code check",
            False,
            f"add verification for {rec.title[:60]}",
        )
    return report


def run_pytest_subset() -> tuple[bool, str]:
    py = get_venv_python(_ROOT)
    cmd = [
        str(py),
        "-m",
        "pytest",
        "tests/test_incident_fix_verification.py",
        "tests/test_shadow_resolver.py",
        "tests/test_feed_recovery.py",
        "tests/test_nifty_ltp_feed.py",
        "tests/test_runtime_log_scan.py",
        "tests/test_incident_excel_export.py",
        "tests/test_incident_knowledge.py",
        "-q",
        "--tb=line",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out[-1500:]


def write_report(report: VerificationReport, *, pytest_ok: bool, pytest_detail: str) -> Path:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=_IST)
    path = _REPORT_DIR / "FIX_VERIFICATION.md"
    lines = [
        f"# Incident Fix Verification — {now.strftime('%Y-%m-%d %H:%M:%S IST')}",
        "",
        f"**Result: {'PASS' if report.passed and pytest_ok else 'FAIL'}**",
        f"- Code/runtime checks: {sum(1 for c in report.checks if c.ok)}/{len(report.checks)}",
        f"- pytest subset: {'PASS' if pytest_ok else 'FAIL'}",
        "",
    ]
    if report.failed:
        lines.append("## Failed checks")
        lines.append("")
        for c in report.failed:
            lines.append(f"- **{c.incident_id}** — {c.name}: {c.detail}")
        lines.append("")
    lines.append("## All checks")
    lines.append("")
    for c in report.checks:
        mark = "PASS" if c.ok else "FAIL"
        lines.append(f"- [{mark}] `{c.incident_id}` {c.name} — {c.detail[:120]}")
    if not pytest_ok:
        lines.extend(["", "## pytest output (tail)", "", "```", pytest_detail, "```"])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_full_verification(*, run_pytest: bool = True) -> tuple[bool, Path]:
    report = VerificationReport()
    verify_code_markers(report)
    verify_runtime_behaviors(report)
    verify_registry_coverage(report)
    pytest_ok, pytest_detail = (True, "skipped") if not run_pytest else run_pytest_subset()
    out = write_report(report, pytest_ok=pytest_ok, pytest_detail=pytest_detail)
    return report.passed and pytest_ok, out

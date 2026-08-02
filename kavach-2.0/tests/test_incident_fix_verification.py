"""Gate: every closed incident fix must be verified in code."""

from __future__ import annotations

from core.incident_fix_verification import (
    run_full_verification,
    verify_code_markers,
    verify_registry_coverage,
    verify_runtime_behaviors,
)


def test_all_incident_code_markers_pass() -> None:
    report = verify_code_markers()
    failed = report.failed
    assert not failed, "\n".join(f"{c.incident_id} {c.name}: {c.detail}" for c in failed)


def test_all_incident_runtime_behaviors_pass() -> None:
    report = verify_runtime_behaviors()
    failed = report.failed
    assert not failed, "\n".join(f"{c.incident_id} {c.name}: {c.detail}" for c in failed)


def test_registry_incidents_covered() -> None:
    base = verify_code_markers()
    verify_runtime_behaviors(base)
    report = verify_registry_coverage(base)
    failed = report.failed
    assert not failed, "\n".join(f"{c.incident_id}: {c.detail}" for c in failed)


def test_full_verification_gate() -> None:
    ok, path = run_full_verification(run_pytest=False)
    assert path.is_file()
    assert ok, path.read_text(encoding="utf-8")[:2000]

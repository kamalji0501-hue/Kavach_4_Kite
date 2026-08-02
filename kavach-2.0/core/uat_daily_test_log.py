"""Structured logging for daily UAT test suite runs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from core.batman_mode import daily_test_execution_dir
from core.uat_daily_tests import CaseResult

IST = ZoneInfo("Asia/Kolkata")
_LOG_ROOT = daily_test_execution_dir() / "logs"


class DailyTestLogger:
    """IST text log: per-run file + append-only daily all.log."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        now = datetime.now(tz=IST)
        month = now.strftime("%Y-%m")
        day = now.strftime("%Y-%m-%d")
        self._dir = _LOG_ROOT / month / day
        self._dir.mkdir(parents=True, exist_ok=True)
        self._run_path = self._dir / f"daily_suite_{run_id}.log"
        self._all_path = _LOG_ROOT / month / day / "all.log"
        self._fh = self._run_path.open("a", encoding="utf-8")
        self._line(f"=== UAT daily suite start run_id={run_id} ===")

    @property
    def run_log_path(self) -> Path:
        return self._run_path

    def _line(self, text: str) -> None:
        ts = datetime.now(tz=IST).strftime("%H%M%S.%f")[:-3]
        row = f"{ts} IST | {text}\n"
        self._fh.write(row)
        self._fh.flush()
        with self._all_path.open("a", encoding="utf-8") as all_fh:
            all_fh.write(row)

    def log_case(self, result: CaseResult, *, catalog_name: str = "") -> None:
        if result.skipped:
            status = "SKIP"
        elif result.ok:
            status = "PASS"
        else:
            status = "FAIL"
        name = f" {catalog_name}" if catalog_name else ""
        self._line(
            f"{status} | {result.case_id}{name} | {result.duration_ms:.0f}ms | {result.detail[:240]}"
        )
        if result.metrics:
            self._line(f"  metrics | {result.case_id} | {result.metrics}")

    def log_summary(
        self,
        *,
        passed: int,
        failed: int,
        skipped: int,
        elapsed_s: float,
        matrix_path: Path | None = None,
    ) -> None:
        self._line(
            f"=== SUMMARY run_id={self.run_id} PASS={passed} FAIL={failed} "
            f"SKIP={skipped} elapsed={elapsed_s:.1f}s ==="
        )
        if matrix_path:
            self._line(f"matrix | {matrix_path.resolve()}")
        self._fh.close()

    @staticmethod
    def default_log_dir() -> Path:
        return _LOG_ROOT

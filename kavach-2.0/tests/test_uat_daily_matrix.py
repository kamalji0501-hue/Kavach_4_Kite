"""UAT daily test matrix — one pytest per catalog case (shared runners)."""

from __future__ import annotations

import pytest

from core.uat_daily_tests import RUNNERS, TEST_CATALOG


@pytest.mark.parametrize(
    "case_id",
    [c.case_id for c in TEST_CATALOG],
    ids=[c.case_id for c in TEST_CATALOG],
)
def test_uat_daily_case(case_id: str) -> None:
    runner = RUNNERS[case_id]
    result = runner()
    if result.skipped:
        pytest.skip(result.detail)
    assert result.ok, f"{case_id}: {result.detail}"

from datetime import time
from pathlib import Path

from core.option_ltp_uat_lookup import load_option_ltp_ticks, lookup_quotes_at, lookup_protect_premium


def test_lookup_option_ltp_differs_across_day(tmp_path: Path) -> None:
    log = tmp_path / "option_ltp_20260723.log"
    log.write_text(
        "09:15:00.000 | pe_protect=90.00 | ce_protect=100.00 | backtest_1m\n"
        "10:00:00.000 | pe_protect=80.00 | ce_protect=110.00 | backtest_1m\n"
        "15:29:00.000 | pe_protect=70.00 | ce_protect=81.00 | backtest_1m\n",
        encoding="utf-8",
    )
    ticks = load_option_ltp_ticks(str(log.resolve()))
    assert len(ticks) == 3
    early = lookup_quotes_at(ticks, time(9, 15))
    late = lookup_quotes_at(ticks, time(15, 29))
    assert early is not None and late is not None
    assert early["ce_protect"] == 100.0
    assert late["ce_protect"] == 81.0
    assert early["ce_protect"] != late["ce_protect"]

    # Monkeypath resolve via writing under expected structure is heavy; call lookup with patched path
    # by using load+quotes path above. Protect premium helper needs resolve — patch via writing
    # is covered indirectly. Direct:
    from core import option_ltp_uat_lookup as mod

    old = mod.resolve_option_ltp_log_path
    mod.resolve_option_ltp_log_path = lambda root, day=None: log  # type: ignore
    try:
        buy = lookup_protect_premium(
            symbol="NIFTY-Aug2026-24250-CE",
            root=tmp_path,
            replay_market_time=time(9, 15),
        )
        sell = lookup_protect_premium(
            symbol="NIFTY-Aug2026-24250-CE",
            root=tmp_path,
            replay_market_time=time(15, 29),
        )
        assert buy == 100.0
        assert sell == 81.0
        assert buy != sell
    finally:
        mod.resolve_option_ltp_log_path = old

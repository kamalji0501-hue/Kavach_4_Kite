"""Tests for GIFT NIFTY off-hours validation feed."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from core.gift_nifty_ltp import (
    GIFT_NIFTY_SECURITY_ID,
    GIFT_NIFTY_SYMBOL,
    append_gift_nifty_audit_log,
    fetch_gift_nifty_ltp_rest,
    read_gift_nifty_cache,
    seed_gift_nifty_cache,
)

_IST = ZoneInfo("Asia/Kolkata")


@patch("core.gift_nifty_ltp.httpx.post")
def test_fetch_gift_nifty_ltp_rest_parses_price(mock_post) -> None:
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "data": {"IDX_I": {str(GIFT_NIFTY_SECURITY_ID): {"last_price": 23690.0}}},
        "status": "success",
    }
    ltp = fetch_gift_nifty_ltp_rest("1106926362", "jwt")
    assert ltp == pytest.approx(23690.0)
    body = mock_post.call_args.kwargs["json"]
    assert body == {"IDX_I": [GIFT_NIFTY_SECURITY_ID]}


def test_gift_cache_roundtrip(tmp_path: Path) -> None:
    cache_path = tmp_path / "gift.json"
    snap = seed_gift_nifty_cache(23690.0, poll_interval_seconds=2, path=cache_path)
    assert snap.symbol == GIFT_NIFTY_SYMBOL
    loaded = read_gift_nifty_cache(cache_path)
    assert loaded is not None
    assert loaded.is_fresh(max_age_seconds=30.0)


def test_append_gift_nifty_audit_log_format(tmp_path: Path) -> None:
    now = datetime(2026, 6, 2, 2, 15, 3, tzinfo=_IST)
    path = append_gift_nifty_audit_log(
        tmp_path, now, 23690.0, "dhan_rest", event="probe"
    )
    assert path.name == "gift_nifty_ltp_20260602.log"
    assert path.read_text(encoding="utf-8").strip() == (
        "2026-06-02 02:15:03 IST,23690.00,dhan_rest,probe"
    )


@pytest.mark.asyncio
@patch("core.gift_nifty_probe.fetch_gift_nifty_ltp_rest_with_retry", return_value=23690.0)
@patch("core.gift_nifty_probe.is_nse_market_session", return_value=False)
async def test_gift_probe_ticks_off_hours(mock_session, mock_fetch, tmp_path: Path) -> None:
    from core.gift_nifty_probe import GiftNiftyProbeService
    from core.nifty_ltp_feed import NiftyLtpFeedConfig

    service = GiftNiftyProbeService(
        client_code="1106926362",
        token_getter=lambda: "jwt",
        config=NiftyLtpFeedConfig(poll_interval_seconds=2),
        cache_path=tmp_path / "gift.json",
        log_dir=tmp_path / "logs",
    )
    await service._tick()
    snap = read_gift_nifty_cache(tmp_path / "gift.json")
    assert snap is not None
    assert snap.ltp == pytest.approx(23690.0)
    assert snap.probe_healthy is True
    audit = list((tmp_path / "logs").glob("gift_nifty_ltp_*.log"))
    assert len(audit) == 1


@pytest.mark.asyncio
@patch("core.gift_nifty_probe.fetch_gift_nifty_ltp_rest_with_retry")
@patch("core.gift_nifty_probe.is_nse_market_session", return_value=True)
async def test_gift_probe_skips_during_nse_session(mock_session, mock_fetch, tmp_path: Path) -> None:
    from core.gift_nifty_probe import GiftNiftyProbeService
    from core.nifty_ltp_feed import NiftyLtpFeedConfig

    service = GiftNiftyProbeService(
        client_code="1106926362",
        token_getter=lambda: "jwt",
        config=NiftyLtpFeedConfig(poll_interval_seconds=2),
        cache_path=tmp_path / "gift.json",
    )
    await service._tick()
    mock_fetch.assert_not_called()

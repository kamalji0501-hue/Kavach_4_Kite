"""Tests for core.nifty_ltp helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.exceptions import BrokerAuthError, BrokerConnectionError
from core.nifty_ltp import (
    _extract_dhan_error,
    check_market_data_subscription,
    fetch_nifty_ltp_rest,
    fetch_nifty_ltp_rest_with_retry,
    is_auth_error,
    is_rate_limit_error,
    validate_dhan_access_token,
)


def test_extract_dhan_error_from_dict_payload() -> None:
    response = MagicMock()
    response.text = "raw"
    response.json.return_value = {"data": {"806": "Data APIs not Subscribed"}}
    assert "Data APIs not Subscribed" in _extract_dhan_error(response)


@patch("core.nifty_ltp.httpx.get")
def test_validate_dhan_access_token_ok(mock_get) -> None:
    mock_get.return_value = MagicMock(status_code=200, text="ok")
    ok, err = validate_dhan_access_token("1106926362", "jwt")
    assert ok is True
    assert err == ""


@patch("core.nifty_ltp.httpx.post")
def test_check_market_data_subscription_not_subscribed(mock_post) -> None:
    mock_post.return_value = MagicMock(
        status_code=401,
        text='{"data":{"806":"Data APIs not Subscribed"}}',
    )
    mock_post.return_value.json.return_value = {"data": {"806": "Data APIs not Subscribed"}}
    ok, err = check_market_data_subscription("1106926362", "jwt")
    assert ok is False
    assert "not subscribed" in err.lower()


@patch("core.nifty_ltp.httpx.post")
def test_fetch_nifty_ltp_rest_parses_price(mock_post) -> None:
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {
        "data": {"data": {"IDX_I": {"13": {"last_price": 23879.45}}}}
    }
    ltp = fetch_nifty_ltp_rest("1106926362", "jwt")
    assert ltp == pytest.approx(23879.45)


@patch("core.nifty_ltp.httpx.post")
def test_fetch_nifty_ltp_rest_parses_live_flat_data_shape(mock_post) -> None:
    """Dhan live response: data.IDX_I directly (no nested data.data)."""
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {
        "data": {"IDX_I": {"13": {"last_price": 23539.05}}},
        "status": "success",
    }
    ltp = fetch_nifty_ltp_rest("1106926362", "jwt")
    assert ltp == pytest.approx(23539.05)


@patch("core.nifty_ltp.httpx.post")
def test_fetch_nifty_ltp_rest_raises_on_429(mock_post) -> None:
    mock_post.return_value = MagicMock(status_code=429, text="Too Many Requests")
    mock_post.return_value.json.return_value = {"message": "Too Many Requests"}
    with pytest.raises(BrokerConnectionError, match="429"):
        fetch_nifty_ltp_rest("1106926362", "jwt")


def test_is_rate_limit_error() -> None:
    assert is_rate_limit_error("Too many requests (HTTP 429).")
    assert is_rate_limit_error("HTTP 429")
    assert is_rate_limit_error("rate limit exceeded")
    assert not is_rate_limit_error("connection timeout")


def test_is_auth_error() -> None:
    assert is_auth_error("Dhan rejected the access token (HTTP 401).")
    assert is_auth_error("invalid token")
    assert not is_auth_error("connection timeout")


@patch("core.nifty_ltp.httpx.post")
def test_fetch_nifty_ltp_rest_raises_on_401(mock_post) -> None:
    mock_post.return_value = MagicMock(status_code=401, text="Unauthorized")
    mock_post.return_value.json.return_value = {"message": "Invalid Token"}
    with pytest.raises(BrokerAuthError, match="401"):
        fetch_nifty_ltp_rest("1106926362", "jwt")


@patch("core.nifty_ltp.time.sleep")
@patch("core.nifty_ltp.fetch_nifty_ltp_rest")
def test_fetch_nifty_ltp_rest_with_retry_no_retry_on_auth(mock_fetch, mock_sleep) -> None:
    mock_fetch.side_effect = BrokerAuthError("HTTP 401")
    with pytest.raises(BrokerAuthError):
        fetch_nifty_ltp_rest_with_retry("1106926362", "jwt", max_attempts=3)
    assert mock_fetch.call_count == 1
    mock_sleep.assert_not_called()


@patch("core.nifty_ltp.time.sleep")
@patch("core.nifty_ltp.fetch_nifty_ltp_rest")
def test_fetch_nifty_ltp_rest_with_retry_recovers(mock_fetch, mock_sleep) -> None:
    mock_fetch.side_effect = [
        BrokerConnectionError("HTTP 429"),
        23500.0,
    ]
    ltp = fetch_nifty_ltp_rest_with_retry("1106926362", "jwt", max_attempts=3)
    assert ltp == pytest.approx(23500.0)
    assert mock_fetch.call_count == 2
    mock_sleep.assert_called_once()


@patch("core.nifty_ltp.time.sleep")
@patch("core.nifty_ltp.fetch_nifty_ltp_rest")
def test_fetch_nifty_ltp_rest_with_retry_exhausted(mock_fetch, mock_sleep) -> None:
    mock_fetch.side_effect = BrokerConnectionError("HTTP 429")
    with pytest.raises(BrokerConnectionError):
        fetch_nifty_ltp_rest_with_retry("1106926362", "jwt", max_attempts=2)
    assert mock_fetch.call_count == 2
    assert mock_sleep.call_count == 1


@patch("core.nifty_ltp.check_market_data_subscription", return_value=(False, "no data"))
@patch("core.nifty_ltp.validate_dhan_access_token", return_value=(True, ""))
@pytest.mark.asyncio
async def test_fetch_nifty_ltp_raises_on_subscription(mock_auth, mock_sub) -> None:
    from core.nifty_ltp import fetch_nifty_ltp

    with pytest.raises(BrokerAuthError):
        await fetch_nifty_ltp("1106926362", "jwt")


@patch("core.nifty_ltp.fetch_nifty_ltp_websocket", return_value=24100.25)
@patch("core.nifty_ltp.check_market_data_subscription", return_value=(True, ""))
@patch("core.nifty_ltp.validate_dhan_access_token", return_value=(True, ""))
@pytest.mark.asyncio
async def test_fetch_nifty_ltp_uses_websocket_primary(mock_auth, mock_sub, mock_ws) -> None:
    """Primary path is WebSocket; REST fallback is not used on WS success."""
    from core.nifty_ltp import fetch_nifty_ltp

    with patch("core.nifty_ltp.fetch_nifty_ltp_rest_with_retry") as mock_rest:
        ltp, source = await fetch_nifty_ltp("1106926362", "jwt")
    assert ltp == pytest.approx(24100.25)
    assert "websocket" in source.lower()
    mock_ws.assert_called_once()
    mock_rest.assert_not_called()


def test_rest_ltp_writes_same_cache_path(tmp_path, monkeypatch) -> None:
    """Writer contract: REST-fetched LTP still lands in nifty_ltp_cache.json."""
    from core.nifty_ltp_feed import seed_nifty_ltp_cache, read_nifty_ltp_cache

    cache = tmp_path / "nifty_ltp_cache.json"
    monkeypatch.setattr(
        "core.nifty_ltp_feed.default_cache_path",
        lambda: cache,
    )
    seed_nifty_ltp_cache(24155.10, source="dhan_rest", path=cache)
    snap = read_nifty_ltp_cache(cache)
    assert snap is not None
    assert snap.ltp == pytest.approx(24155.10)
    assert snap.source == "dhan_rest"
    assert cache.is_file()
    assert cache.name == "nifty_ltp_cache.json"
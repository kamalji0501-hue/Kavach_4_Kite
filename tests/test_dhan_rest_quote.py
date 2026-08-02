"""REST-only Dhan quote client (no Tradehull)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from core.dhan_rest_quote import DhanRestQuoteClient, cached_rest_quote_client


def test_cached_rest_quote_client_reuses_instance() -> None:
    broker = type("B", (), {"_client_code": "CC", "_access_token": "tok"})()
    a = cached_rest_quote_client(broker)
    b = cached_rest_quote_client(broker)
    assert a is b
    assert isinstance(a, DhanRestQuoteClient)


@patch(
    "backtest_engine.resolver.instrument_master.resolve_nifty_option",
    return_value=type("I", (), {"security_id": 42290})(),
)
@patch("core.dhan_rest_quote.fetch_fno_ltp_rest", return_value={42290: 150.0})
def test_get_nifty_option_ltps_rest(mock_ltp, _mock_resolve) -> None:
    client = DhanRestQuoteClient("CC", "jwt")
    out = client.get_nifty_option_ltps([(23450, "CE")], expiry_date=date(2026, 6, 9))
    assert out.get((23450, "CE")) == 150.0
    mock_ltp.assert_called_once()

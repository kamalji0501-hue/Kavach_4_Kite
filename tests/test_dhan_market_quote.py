"""Dhan marketfeed/ltp parsing for NSE F&O."""

from __future__ import annotations

from core.dhan_market_quote import parse_marketfeed_ltp


def test_parse_marketfeed_nse_fno() -> None:
    payload = {
        "status": "success",
        "data": {
            "NSE_FNO": {
                "42259": {"last_price": 17.55},
                "42261": {"last_price": 21.05},
            }
        },
    }
    out = parse_marketfeed_ltp(payload, "NSE_FNO", [42259, 42261])
    assert out == {42259: 17.55, 42261: 21.05}

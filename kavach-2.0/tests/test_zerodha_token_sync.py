"""Disk Kite token must replace the live REST client without a Kavach restart."""
from __future__ import annotations

from core import zerodha_credentials as zc


class _FakeBroker:
    def __init__(self, token: str = "OLDTOKEN") -> None:
        self._access_token = token
        self.reloads: list[tuple[str, str]] = []

    def hot_reload_token(self, client_code: str, access_token: str) -> None:
        self._access_token = access_token
        self.reloads.append((client_code, access_token))


def test_sync_reloads_when_disk_token_differs(monkeypatch) -> None:
    fake = _FakeBroker("OLDTOKEN")
    zc.register_live_order_broker(fake)

    class _Creds:
        ok = True
        api_key = "abc"
        access_token = "NEWTOKEN1234"

    monkeypatch.setattr(zc, "load_zerodha_order_creds", lambda root=None, log=True: _Creds())
    assert zc.sync_live_zerodha_token(fake, force=False) is True
    assert fake._access_token == "NEWTOKEN1234"
    assert fake.reloads[-1][1] == "NEWTOKEN1234"


def test_sync_skips_when_already_current(monkeypatch) -> None:
    fake = _FakeBroker("SAME")
    zc.register_live_order_broker(fake)

    class _Creds:
        ok = True
        api_key = "abc"
        access_token = "SAME"

    monkeypatch.setattr(zc, "load_zerodha_order_creds", lambda root=None, log=True: _Creds())
    assert zc.sync_live_zerodha_token(fake, force=False) is False
    assert fake.reloads == []

"""Unit tests for Dhan PIN/TOTP auth (mocked — no live Dhan, no real secrets)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from core.dhan_pin_totp import (
    extract_access_token,
    load_pin_totp_credentials_from_env,
    obtain_access_token_via_pin_totp,
    pin_totp_env_present,
)

_NO_SECRETS = patch("core.dhan_pin_totp.ensure_dhan_secrets_loaded", lambda *a, **k: None)


class TestDhanPinTotpEnv(unittest.TestCase):
    def setUp(self) -> None:
        self._p = patch("core.dhan_pin_totp.ensure_dhan_secrets_loaded", lambda *a, **k: None)
        self._p.start()
        self.addCleanup(self._p.stop)

    def test_missing_env(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(pin_totp_env_present())
            self.assertIsNone(load_pin_totp_credentials_from_env())

    def test_load_ok_and_repr_hides_secrets(self) -> None:
        env = {
            "DHAN_CLIENT_CODE": "C123",
            "DHAN_PIN": "654321",
            "DHAN_TOTP_SECRET": "BASE32SEEDTEST",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(pin_totp_env_present())
            creds = load_pin_totp_credentials_from_env(require=True)
        assert creds is not None
        self.assertEqual(creds.client_code, "C123")
        self.assertEqual(creds.pin, "654321")
        self.assertEqual(creds.totp_secret, "BASE32SEEDTEST")
        dumped = repr(creds)
        self.assertNotIn("654321", dumped)
        self.assertNotIn("BASE32SEEDTEST", dumped)

    def test_require_pin(self) -> None:
        with patch.dict(os.environ, {"DHAN_CLIENT_CODE": "C123"}, clear=True):
            with self.assertRaisesRegex(ValueError, "DHAN_PIN"):
                load_pin_totp_credentials_from_env(require=True)

    def test_client_id_alias(self) -> None:
        env = {
            "DHAN_CLIENT_ID": "CID9",
            "DHAN_PIN": "111111",
            "DHAN_TOTP_SECRET": "SEEDONLY",
        }
        with patch.dict(os.environ, env, clear=True):
            creds = load_pin_totp_credentials_from_env(require=True)
        assert creds is not None
        self.assertEqual(creds.client_code, "CID9")


class TestDhanPinTotpLogin(unittest.TestCase):
    def setUp(self) -> None:
        self._p = patch("core.dhan_pin_totp.ensure_dhan_secrets_loaded", lambda *a, **k: None)
        self._p.start()
        self.addCleanup(self._p.stop)

    def test_login_tradehull_pin_totp_kwargs(self) -> None:
        mock_th = MagicMock()
        mock_th.return_value.instrument_df = object()
        mock_th.return_value.token_id = "jwt-token"
        fake_mod = MagicMock(Tradehull=mock_th)
        env = {
            "DHAN_CLIENT_CODE": "C123",
            "DHAN_PIN": "654321",
            "DHAN_TOTP_SECRET": "BASE32SEEDTEST",
        }
        with patch.dict(os.environ, env, clear=True):
            creds = load_pin_totp_credentials_from_env(require=True)
        with patch.dict("sys.modules", {"Dhan_Tradehull": fake_mod}):
            from core.dhan_pin_totp import login_tradehull_pin_totp

            tsl = login_tradehull_pin_totp(creds)  # type: ignore[arg-type]
        mock_th.assert_called_once_with(
            ClientCode="C123",
            mode="pin_totp",
            pin="654321",
            totp_secret="BASE32SEEDTEST",
        )
        self.assertIs(tsl, mock_th.return_value)

    def test_obtain_access_token(self) -> None:
        fake = MagicMock()
        fake.token_id = "jwt-abc"
        env = {
            "DHAN_CLIENT_CODE": "C123",
            "DHAN_PIN": "654321",
            "DHAN_TOTP_SECRET": "BASE32SEEDTEST",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("core.dhan_pin_totp.login_tradehull_pin_totp", return_value=fake):
                client, token = obtain_access_token_via_pin_totp()
        self.assertEqual(client, "C123")
        self.assertEqual(token, "jwt-abc")

    def test_extract_access_token_missing(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no access token"):
            extract_access_token(MagicMock(token_id="", access_token=""))


class TestBrokerPinTotp(unittest.TestCase):
    def test_connect_with_pin_totp(self) -> None:
        mock_th = MagicMock()
        mock_inst = MagicMock()
        mock_inst.token_id = "jwt-from-pin"
        mock_th.return_value = mock_inst
        fake_mod = MagicMock(Tradehull=mock_th)
        with patch.dict("sys.modules", {"Dhan_Tradehull": fake_mod}):
            with patch("core.broker._sync_tradehull_token_cache"):
                from core.broker import BatmanBroker

                broker = BatmanBroker.connect_with_pin_totp(
                    "C123", "654321", "BASE32SEEDTEST"
                )
        self.assertEqual(broker._client_code, "C123")
        self.assertEqual(broker._access_token, "jwt-from-pin")
        mock_th.assert_called_once_with(
            ClientCode="C123",
            mode="pin_totp",
            pin="654321",
            totp_secret="BASE32SEEDTEST",
        )

    def test_connect_with_pin_totp_rejects_empty(self) -> None:
        from core.broker import BatmanBroker
        from core.exceptions import BrokerAuthError

        with self.assertRaises(BrokerAuthError):
            BatmanBroker.connect_with_pin_totp("", "1", "2")


if __name__ == "__main__":
    unittest.main()

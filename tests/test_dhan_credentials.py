"""Tests for Dhan secrets_root mapping (no real secrets)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.dhan_credentials import (
    apply_dhan_secrets_env,
    dhan_secrets_status,
    load_dhan_env_values,
    resolve_dhan_env_path,
)


class TestDhanCredentials(unittest.TestCase):
    def test_prefers_dhan_env_over_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            cfg.mkdir(parents=True)
            (cfg / ".env").write_text(
                "DHAN_CLIENT_CODE=FROM_DOTENV\nDHAN_PIN=111111\nDHAN_TOTP_SECRET=SEEDA\n",
                encoding="utf-8",
            )
            (cfg / "dhan.env").write_text(
                "DHAN_CLIENT_CODE=FROM_DHAN_ENV\nDHAN_PIN=222222\nDHAN_TOTP_SECRET=SEEDB\n",
                encoding="utf-8",
            )
            with patch("core.batman_mode.secrets_root", return_value=root):
                path = resolve_dhan_env_path(root)
                vals = load_dhan_env_values(root)
                st = dhan_secrets_status(root)
            self.assertEqual(path, cfg / "dhan.env")
            self.assertEqual(vals["DHAN_CLIENT_CODE"], "FROM_DHAN_ENV")
            self.assertEqual(vals["DHAN_PIN"], "222222")
            self.assertTrue(st["pin_totp_ready"])

    def test_ignores_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            cfg.mkdir(parents=True)
            (cfg / "dhan.env").write_text(
                "DHAN_CLIENT_CODE=<ENTER_DHAN_CLIENT_CODE>\n"
                "DHAN_PIN=<ENTER_DHAN_PIN_IF_USED>\n"
                "DHAN_TOTP_SECRET=<ENTER_DHAN_TOTP_SECRET_IF_USED>\n",
                encoding="utf-8",
            )
            with patch("core.batman_mode.secrets_root", return_value=root):
                vals = load_dhan_env_values(root)
                st = dhan_secrets_status(root)
            self.assertEqual(vals, {})
            self.assertFalse(st["pin_totp_ready"])

    def test_apply_sets_environ(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            cfg.mkdir(parents=True)
            (cfg / "dhan.env").write_text(
                "DHAN_CLIENT_CODE=C9\nDHAN_PIN=654321\nDHAN_TOTP_SECRET=BASE32SEED\n",
                encoding="utf-8",
            )
            with patch("core.batman_mode.secrets_root", return_value=root):
                with patch.dict(os.environ, {}, clear=True):
                    apply_dhan_secrets_env(root)
                    self.assertEqual(os.environ.get("DHAN_CLIENT_CODE"), "C9")
                    self.assertEqual(os.environ.get("DHAN_PIN"), "654321")


if __name__ == "__main__":
    unittest.main()

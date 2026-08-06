"""Tests for money_audit redaction and JSONL emit."""

from __future__ import annotations

import json
from pathlib import Path

from core.money_audit import audit, configure_money_audit, redact


def test_redact_secrets() -> None:
    raw = {
        "symbol": "NIFTY",
        "access_token": "super-secret-token-value",
        "Authorization": "Bearer abc.def.ghi",
        "nested": {"totp": "123456", "qty": 65},
        "msg": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.aaa.bbb",
    }
    out = redact(raw)
    assert out["symbol"] == "NIFTY"
    assert out["access_token"] == "<redacted>"
    assert out["Authorization"] == "<redacted>"
    assert out["nested"]["totp"] == "<redacted>"
    assert out["nested"]["qty"] == 65
    assert "<redacted>" in out["msg"]
    assert "super-secret" not in json.dumps(out)


def test_audit_writes_jsonl(tmp_path: Path, monkeypatch) -> None:
    # Point log_root via batman_mode if available; else configure still writes.
    path = configure_money_audit(tmp_path, bot_name="kavach", settings={"audit_jsonl": True, "detail_jsonl": False, "debug_trading": False})
    audit("order.punch.test", mode="paper", qty=65, token="must-not-appear")
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    last = json.loads(lines[-1])
    assert last["event"] == "order.punch.test"
    blob = json.dumps(last)
    assert "must-not-appear" not in blob
    assert "<redacted>" in blob or "token" in blob

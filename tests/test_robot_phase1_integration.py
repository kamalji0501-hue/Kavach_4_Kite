"""End-to-end-ish Phase-1 robot guards (no Telegram, no real Dhan)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.order_mode import configure_ato_order_sink, normalize_order_mode
from core.paper_position_book import open_legs, record_fill, snapshot_text
from core.wizard_plan import build_wizard_plan, question_index


def test_order_mode_roundtrip_in_deployment_shape(tmp_path: Path) -> None:
    dep = {
        "schema_version": 1.1,
        "order_mode": "paper",
        "ato": {"ce_protect_symbol": "CE", "pe_protect_symbol": "PE"},
        "positions": {},
    }
    assert normalize_order_mode(dep["order_mode"]) == "paper"
    (tmp_path / "batman_test.json").write_text(json.dumps(dep), encoding="utf-8")
    loaded = json.loads((tmp_path / "batman_test.json").read_text(encoding="utf-8"))
    assert loaded["order_mode"] == "paper"


def test_live_and_paper_sink_toggle(tmp_path: Path, monkeypatch) -> None:
    import core.batman_mode as bm

    monkeypatch.setattr(bm, "data_root", lambda root=None: tmp_path)
    monkeypatch.setattr(bm, "workspace_root", lambda: tmp_path)

    class Ato:
        order_manager = None

    ato = Ato()
    assert configure_ato_order_sink(ato, order_mode="paper", workspace_root=tmp_path) == "paper"
    assert ato.order_manager is not None
    assert configure_ato_order_sink(ato, order_mode="live", workspace_root=tmp_path) == "live"
    assert ato.order_manager is None
    # toggle back
    assert configure_ato_order_sink(ato, order_mode="paper", workspace_root=tmp_path) == "paper"
    assert ato.order_manager is not None


def test_paper_book_snapshot(tmp_path: Path, monkeypatch) -> None:
    import core.paper_position_book as pb

    monkeypatch.setattr(pb, "_book_path", lambda root=None: tmp_path / "book.json")
    record_fill(symbol="NIFTY CE", qty=65, side="BUY", avg_price=12.5, source="ato_protect")
    assert len(open_legs()) == 1
    text = snapshot_text()
    assert "NIFTY CE" in text
    assert "65" in text


def test_wizard_question_numbers_stable() -> None:
    plan = build_wizard_plan(pe_enabled=True, ce_enabled=True)
    assert plan[0] == "order_mode"
    idx, total = question_index(plan, "order_mode")
    assert idx == 1
    assert total == len(plan)
    cidx, _ = question_index(plan, "confirm")
    assert cidx == total


def test_register_wizard_exports_order_mode_state() -> None:
    from bat_telegram.bots.kavach2 import register_wizard as rw

    assert hasattr(rw, "WIZARD_ORDER_MODE")
    assert hasattr(rw, "_CB_ORDER_MODE")
    assert hasattr(rw, "wizard_order_mode")
    assert rw._CB_ORDER_MODE == "wiz_omode"
    # ConversationHandler may be mocked in suite conftest — check source wiring instead
    src = Path(rw.__file__).read_text(encoding="utf-8")
    assert "WIZARD_ORDER_MODE:" in src
    assert "wizard_order_mode" in src
    assert "_CB_ORDER_MODE" in src


@pytest.mark.skipif(
    not Path("/home/ubuntu/place-order-bot").is_dir(),
    reason="place-order-bot not on this host",
)
def test_order_manager_paper_fill_and_book(tmp_path: Path, monkeypatch) -> None:
    import sys

    pob = Path("/home/ubuntu/place-order-bot")
    if str(pob) not in sys.path:
        sys.path.insert(0, str(pob))
    import core.paper_position_book as pb
    from core.order_manager import OrderManager

    monkeypatch.setattr(pb, "_book_path", lambda root=None: tmp_path / "book.json")
    om = OrderManager(mode="paper", ledger_dir=tmp_path / "om", default_ltp=101.0)
    oid = om.punch_ato(symbol="NIFTY T", qty=65, side="BUY", security_id="9", reason="verify")
    assert oid
    assert open_legs()

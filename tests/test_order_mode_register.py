"""Paper/Live register + order sink safety."""

from __future__ import annotations

from pathlib import Path

from core.order_mode import configure_ato_order_sink, normalize_order_mode
from core.paper_position_book import open_legs, record_fill
from core.wizard_plan import build_wizard_plan


def test_wizard_plan_starts_with_order_mode() -> None:
    plan = build_wizard_plan(pe_enabled=True, ce_enabled=True)
    assert plan[0] == "order_mode"
    assert plan[-1] == "confirm"


def test_normalize_order_mode() -> None:
    assert normalize_order_mode("PAPER") == "paper"
    assert normalize_order_mode("live") == "live"
    assert normalize_order_mode("nope") == "paper"


def test_configure_sink_paper_attaches_om(tmp_path: Path, monkeypatch) -> None:
    class FakeAto:
        order_manager = None

    # Point data_root at tmp
    import core.batman_mode as bm

    monkeypatch.setattr(bm, "data_root", lambda root=None: tmp_path)
    monkeypatch.setattr(bm, "workspace_root", lambda: tmp_path)
    ato = FakeAto()
    mode = configure_ato_order_sink(ato, order_mode="paper", workspace_root=tmp_path)
    assert mode == "paper"
    assert ato.order_manager is not None
    assert ato.order_manager.mode == "paper"


def test_configure_sink_live_clears_om(tmp_path: Path, monkeypatch) -> None:
    class FakeAto:
        order_manager = object()

    import core.batman_mode as bm

    monkeypatch.setattr(bm, "data_root", lambda root=None: tmp_path)
    ato = FakeAto()
    mode = configure_ato_order_sink(ato, order_mode="live", workspace_root=tmp_path)
    assert mode == "live"
    assert ato.order_manager is None


def test_paper_book_record(tmp_path: Path, monkeypatch) -> None:
    import core.paper_position_book as pb

    monkeypatch.setattr(pb, "_book_path", lambda root=None: tmp_path / "paper_position_book.json")
    record_fill(symbol="NIFTY TEST CE", qty=65, side="BUY", avg_price=100.5, source="ato_protect")
    legs = open_legs()
    assert len(legs) == 1
    assert legs[0]["qty"] == 65
    record_fill(symbol="NIFTY TEST CE", qty=65, side="SELL", source="ato_retrace")
    assert open_legs() == []


def test_order_manager_paper_no_live_broker(tmp_path: Path, monkeypatch) -> None:
    """Paper punch must not call a real broker place method."""
    import sys

    # Ensure place-order on path
    pob = Path("/home/ubuntu/place-order-bot")
    if pob.is_dir() and str(pob) not in sys.path:
        sys.path.insert(0, str(pob))

    from core.order_manager import OrderManager

    class BoomBroker:
        def place_aggressive_limit(self, **kwargs):
            raise AssertionError("live broker must not be called in paper mode")

        def place_market_order(self, **kwargs):
            raise AssertionError("live broker must not be called in paper mode")

    om = OrderManager(mode="paper", ledger_dir=tmp_path / "om", default_ltp=110.0)
    oid = om.punch_ato(symbol="NIFTY X", qty=65, side="BUY", security_id="1", reason="test")
    assert oid
    # ATO path uses OM when attached
    class Ato:
        order_manager = om
        broker = BoomBroker()
        log = __import__("logging").getLogger("t")

        def _operator_settings(self):
            return {}

    from modules.ato_protection import ATOProtection

    oid2 = ATOProtection._place_ato_aggressive_limit(
        Ato(), symbol="NIFTY X", qty=65, side="BUY", product="MARGIN"
    )
    assert oid2

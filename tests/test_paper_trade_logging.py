"""Paper / live trade lane log prefix tests."""

from __future__ import annotations

import logging
import unittest
from io import StringIO

from core.paper_trade_logging import (
    PAPER_PREFIX,
    TradeLaneFormatter,
    apply_message_prefix,
    get_trade_lane,
    set_trade_lane,
)
from core import money_audit


class TestPaperTradeLogging(unittest.TestCase):
    def tearDown(self) -> None:
        set_trade_lane("unknown")

    def test_prefix_helpers(self) -> None:
        set_trade_lane("paper")
        self.assertEqual(get_trade_lane(), "paper")
        self.assertTrue(apply_message_prefix("hello").startswith(PAPER_PREFIX))
        set_trade_lane("live")
        self.assertIn("[LIVE TRADE]", apply_message_prefix("hello"))

    def test_formatter_injects_paper(self) -> None:
        set_trade_lane("paper")
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(TradeLaneFormatter("%(levelname)s %(message)s"))
        log = logging.getLogger("test.paper.lane")
        log.handlers.clear()
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False
        log.info("punch begin")
        out = buf.getvalue()
        self.assertIn(PAPER_PREFIX, out)
        self.assertIn("punch begin", out)

    def test_money_audit_paper_prefix(self) -> None:
        set_trade_lane("paper")
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(TradeLaneFormatter("%(levelname)s %(message)s"))
        money_audit.logger.handlers.clear()
        money_audit.logger.addHandler(handler)
        money_audit.logger.setLevel(logging.INFO)
        money_audit.logger.propagate = False
        money_audit.audit("unit.paper.probe", mode="paper", symbol="NIFTY", qty=65)
        out = buf.getvalue()
        self.assertIn(PAPER_PREFIX, out)
        self.assertEqual(out.count(PAPER_PREFIX), 1)
        self.assertIn("unit.paper.probe", out)


if __name__ == "__main__":
    unittest.main()

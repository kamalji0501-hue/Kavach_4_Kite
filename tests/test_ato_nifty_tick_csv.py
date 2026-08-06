"""Tests for ATO+NIFTY tick CSV writer."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.ato_nifty_tick_csv import AtoNiftyTickCsvWriter, CSV_COLUMNS

_IST = ZoneInfo("Asia/Kolkata")


def test_csv_register_and_ticks(tmp_path: Path) -> None:
    w = AtoNiftyTickCsvWriter(csv_dir=tmp_path / "ato_tick_csv", mirror_dir=tmp_path / "mirror")
    path = w.set_registration(
        ce_symbol="NIFTY 06 AUG 25000 CALL",
        ce_strike=25000,
        ce_mode="AUTO",
        pe_symbol="NIFTY 06 AUG 24500 PUT",
        pe_strike=24500,
        pe_mode="CUSTOM",
        nifty_ltp=24750.5,
    )
    assert path.exists()
    w.on_nifty_ltp(datetime.now(_IST), 24751.0, source="nifty_ws")
    w.on_option_quotes(
        datetime.now(_IST),
        {"ce_protect": 120.5, "pe_protect": 95.25},
        source="option_poll",
    )
    w.flush()
    text = path.read_text(encoding="utf-8")
    rows = list(csv.DictReader(text.splitlines()))
    assert rows
    assert list(rows[0].keys()) == list(CSV_COLUMNS)
    assert any(r["source"] == "register" for r in rows)
    assert any(r["ce_ato_mode"] == "AUTO" for r in rows)
    assert any(r["pe_ato_mode"] == "CUSTOM" for r in rows)
    assert any(r["ce_ato_ltp"] == "120.50" for r in rows)
    assert any(r["pe_ato_ltp"] == "95.25" for r in rows)
    assert any(r["nifty_ltp"] == "24751.00" for r in rows)
    # mirror also written
    mirrors = list((tmp_path / "mirror").glob("*.csv"))
    assert mirrors
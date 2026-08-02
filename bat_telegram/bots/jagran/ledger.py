"""Read incident ledger files for JAGRAN /recent and EOD digest."""

from __future__ import annotations

import csv
import zoneinfo
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.batman_mode import incidents_root

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def _ledger_dir() -> Path:
    return incidents_root()


def ledger_csv_path(for_date: date | None = None) -> Path:
    d = for_date or datetime.now(_IST).date()
    return _ledger_dir() / f"incident_ledger_{d.strftime('%Y%m%d')}.csv"


def read_ledger_rows(for_date: date | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
    path = ledger_csv_path(for_date)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(dict(row))
    if limit > 0 and len(rows) > limit:
        return rows[-limit:]
    return rows


def summarize_day(for_date: date | None = None) -> dict[str, Any]:
    rows = read_ledger_rows(for_date, limit=0)
    triggered = [
        r
        for r in rows
        if r.get("event_type") == "incident" and r.get("status_label") == "TRIGGERED"
    ]
    still_failing = [
        r
        for r in rows
        if r.get("event_type") == "incident" and r.get("status_label") == "STILL FAILING"
    ]
    recovered = [r for r in rows if r.get("event_type") == "recovery"]
    suppressed = [r for r in rows if r.get("status_label") == "SUPPRESSED_NOTIFICATION"]

    by_source: dict[str, int] = {}
    for r in rows:
        if r.get("event_type") != "incident":
            continue
        if r.get("status_label") == "SUPPRESSED_NOTIFICATION":
            continue
        src = str(r.get("source", "?"))
        by_source[src] = by_source.get(src, 0) + 1

    open_ids = {
        str(r.get("incident_id", ""))
        for r in rows
        if r.get("event_type") == "incident"
        and r.get("status_label") in ("TRIGGERED", "STILL FAILING")
    }
    recovered_ids = {str(r.get("incident_id", "")) for r in recovered}
    still_open = sorted(open_ids - recovered_ids)

    return {
        "row_count": len(rows),
        "triggered": len(triggered),
        "still_failing_events": len(still_failing),
        "recovered": len(recovered),
        "suppressed": len(suppressed),
        "by_source": by_source,
        "open_incident_ids": still_open,
        "last_row": rows[-1] if rows else None,
    }

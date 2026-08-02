#!/usr/bin/env python3
"""Incident Management System CLI — knowledge registry + runtime tracker bridge."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.incident_knowledge import (  # noqa: E402
    build_dashboard,
    export_markdown_docs,
    find_by_id,
    load_registry,
    merge_seed_incidents,
    registry_path,
    search_similar,
    seed_registry_if_empty,
)
from core.incident_excel_export import default_xlsx_path, export_incident_registry_xlsx  # noqa: E402
from core.incident_tracker import close_incident, list_open_incidents  # noqa: E402


def cmd_seed(_args: argparse.Namespace) -> int:
    count = seed_registry_if_empty()
    if count:
        print(f"Seeded {count} incidents -> {registry_path()}")
    else:
        merged = merge_seed_incidents()
        if merged:
            print(f"Merged {merged} new seed incidents -> {registry_path()}")
        else:
            print(f"Registry up to date: {registry_path()}")
    export_markdown_docs()
    xlsx = export_incident_registry_xlsx()
    print("Exported REGISTRY.md + records/*.md")
    print(f"Exported Excel: {xlsx}")
    return 0


def cmd_dashboard(_args: argparse.Namespace) -> int:
    seed_registry_if_empty()
    dash = build_dashboard()
    print(json.dumps(dash, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    seed_registry_if_empty()
    items = load_registry()
    if args.open_only:
        items = [i for i in items if i.lifecycle != "closed"]
    for rec in sorted(items, key=lambda x: x.incident_id):
        status = "CLOSED" if rec.lifecycle == "closed" else rec.lifecycle.upper()
        print(f"{rec.incident_id:18} [{rec.severity:8}] {status:12} {rec.title[:70]}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    seed_registry_if_empty()
    rec = find_by_id(args.incident_id)
    if rec is None:
        print(f"Unknown incident: {args.incident_id}")
        return 1
    from core.incident_knowledge import render_incident_markdown

    print(render_incident_markdown(rec))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    seed_registry_if_empty()
    hits = search_similar(args.query, limit=args.limit)
    if not hits:
        print("No similar incidents found.")
        return 0
    for rec, score in hits:
        print(f"  {score:.0%}  {rec.incident_id}  {rec.title}  [{rec.lifecycle}]")
    return 0


def cmd_export(_args: argparse.Namespace) -> int:
    seed_registry_if_empty()
    reg_md, records_dir = export_markdown_docs()
    xlsx = export_incident_registry_xlsx()
    print(f"Wrote {reg_md}")
    print(f"Wrote {len(list(records_dir.glob('*.md')))} files under {records_dir}")
    print(f"Wrote Excel: {xlsx}")
    return 0


def cmd_export_excel(_args: argparse.Namespace) -> int:
    seed_registry_if_empty()
    xlsx = export_incident_registry_xlsx()
    print(f"Wrote Excel: {xlsx}")
    print(f"Archive: data/analytics/incidents/incident_registry_*.xlsx")
    return 0


def cmd_close_historical(_args: argparse.Namespace) -> int:
    """Close stale runtime open incidents from pre-stabilization sessions."""
    notes = {
        "drishti::log_error": (
            "Historical Jun-20 log errors — superseded by 2026-06-25 stabilization "
            "(INC-2026-018 diagnose_robot, INC-2026-022 feed recovery)"
        ),
        "jagran::log_critical": (
            "Historical Jun-12–20 critical alerts — no recurrence after stabilization sprint"
        ),
        "jagran::log_error": (
            "Historical Jun-12–20 errors — INC-2026-021 JAGRAN timeout resolved with feed fix"
        ),
        "start_all::phase1_start_all_failed": (
            "Historical launcher failures Jun-12–20 — lifecycle preflight fixes in place"
        ),
        "stop_all::phase1_stop_all_failed": (
            "Historical stop-all failures Jun-12–20 — resolved by ensure_bot_stopped preflight"
        ),
    }
    closed = 0
    for row in list_open_incidents():
        rid = row["incident_id"]
        note = notes.get(rid, "Closed after stabilization sprint — no active recurrence")
        if close_incident(incident_id=rid, note=note):
            print(f"Closed runtime {rid}")
            closed += 1
    if not closed:
        print("No open runtime incidents to close.")
    return 0


def cmd_sync_runtime(_args: argparse.Namespace) -> int:
    """Close runtime open incidents that match closed knowledge registry entries."""
    seed_registry_if_empty()
    closed = {r.incident_id: r for r in load_registry() if r.lifecycle == "closed"}
    runtime_open = list_open_incidents()
    closed_count = 0
    for row in runtime_open:
        rid = row["incident_id"]
        for rec in closed.values():
            if rid in rec.runtime_incident_ids:
                note = f"Closed via knowledge registry {rec.incident_id}: {rec.title}"
                if close_incident(incident_id=rid, note=note):
                    print(f"Closed runtime {rid} <- {rec.incident_id}")
                    closed_count += 1
    if not closed_count:
        print("No runtime incidents matched closed knowledge entries.")
    return 0


def cmd_report(_args: argparse.Namespace) -> int:
    seed_registry_if_empty()
    items = load_registry()
    dash = build_dashboard()
    print("=== Incident Management Report ===\n")
    print(f"Total: {dash['total']}  Open: {dash['open']}  Closed: {dash['closed']}")
    print(f"Critical: {dash['critical']}  High: {dash['high']}  Regression-linked: {dash['regression_count']}\n")
    print("Open knowledge incidents:")
    for rec in items:
        if rec.lifecycle != "closed":
            print(f"  {rec.incident_id}: {rec.title}")
    if dash["open"] == 0:
        print("  (none)")
    print("\nRuntime open incidents:")
    for row in list_open_incidents():
        print(f"  {row['incident_id']} repeat={row['repeat_count']}")
    if not list_open_incidents():
        print("  (none)")
    print("\nTop modules:")
    for mod, count in dash["top_modules"][:5]:
        print(f"  {mod}: {count}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Batman Incident Management System")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="Initialize registry from STAB + historical seed").set_defaults(
        func=cmd_seed
    )
    sub.add_parser("dashboard", help="JSON dashboard metrics").set_defaults(func=cmd_dashboard)
    sub.add_parser("export", help="Regenerate REGISTRY.md, records/*.md, and Excel").set_defaults(
        func=cmd_export
    )
    sub.add_parser("export-excel", help="Regenerate incident_registry.xlsx only").set_defaults(
        func=cmd_export_excel
    )
    sub.add_parser("close-historical", help="Close stale runtime open incidents").set_defaults(
        func=cmd_close_historical
    )
    sub.add_parser("sync-runtime", help="Close runtime incidents linked to closed knowledge records").set_defaults(
        func=cmd_sync_runtime
    )
    sub.add_parser("report", help="Human summary for stabilization sessions").set_defaults(func=cmd_report)

    p_list = sub.add_parser("list", help="List knowledge incidents")
    p_list.add_argument("--open-only", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show one incident (markdown)")
    p_show.add_argument("incident_id")
    p_show.set_defaults(func=cmd_show)

    p_search = sub.add_parser("search", help="Find similar past incidents")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=5)
    p_search.set_defaults(func=cmd_search)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Permanent incident knowledge base — complements runtime ``core/incident_tracker.py``.

Runtime tracker: automatic ERROR+ capture → daily CSV per domain.
Knowledge registry: structured RCA, fix history, validation evidence, lessons learned.

Registry file: ``docs/incidents/registry.json`` (version-controlled).
"""

from __future__ import annotations

import json
import re
import zoneinfo
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = _ROOT / "docs" / "incidents" / "registry.json"

VALID_LIFECYCLE = (
    "new",
    "under_investigation",
    "root_cause_identified",
    "fix_implemented",
    "testing",
    "regression_testing",
    "stress_testing",
    "verified",
    "closed",
)

VALID_SEVERITY = ("critical", "high", "medium", "low", "info")
VALID_PRIORITY = ("p0", "p1", "p2", "p3")


class IncidentCategory(StrEnum):
    ROBOT = "robot"
    INFRASTRUCTURE = "infrastructure"
    BROKER = "broker"
    MARKET_DATA = "market_data"
    CONFIGURATION = "configuration"
    RUNTIME = "runtime"
    TESTING = "testing"
    DOCUMENTATION = "documentation"


@dataclass
class IncidentRecord:
    """Full incident template — single source of truth per engineering incident."""

    incident_id: str
    title: str
    category: str
    subsystem: str = ""
    robot_affected: str = ""
    date_first_observed: str = ""
    date_resolved: str = ""
    lifecycle: str = "new"
    severity: str = "medium"
    priority: str = "p2"
    environment: str = "uat"
    frequency: str = "once"
    symptoms: str = ""
    business_impact: str = ""
    technical_impact: str = ""
    trading_impact: str = ""
    root_cause: str = ""
    contributing_factors: list[str] = field(default_factory=list)
    investigation: str = ""
    files_modules: list[str] = field(default_factory=list)
    logs_referenced: list[str] = field(default_factory=list)
    fix_implemented: str = ""
    fix_rationale: str = ""
    regression_risk: str = ""
    validation_performed: list[str] = field(default_factory=list)
    stress_testing: list[str] = field(default_factory=list)
    validation_cycles: int = 0
    remaining_risks: list[str] = field(default_factory=list)
    related_incidents: list[str] = field(default_factory=list)
    runtime_incident_ids: list[str] = field(default_factory=list)
    preventive_measures: list[str] = field(default_factory=list)
    lessons_learned: list[str] = field(default_factory=list)
    future_recommendations: list[str] = field(default_factory=list)
    owner: str = "agent"
    last_updated: str = ""
    legacy_stab_id: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> IncidentRecord:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in raw.items() if k in known}
        return cls(**filtered)


def _now_iso() -> str:
    return datetime.now(_IST).isoformat()


def registry_path(path: Path | None = None) -> Path:
    return path or DEFAULT_REGISTRY_PATH


def load_registry(path: Path | None = None) -> list[IncidentRecord]:
    p = registry_path(path)
    if not p.is_file():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("incidents"), list):
        return []
    out: list[IncidentRecord] = []
    for item in raw["incidents"]:
        if isinstance(item, dict):
            out.append(IncidentRecord.from_dict(item))
    return out


def save_registry(incidents: list[IncidentRecord], path: Path | None = None) -> Path:
    p = registry_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "last_updated": _now_iso(),
        "incidents": [i.to_dict() for i in sorted(incidents, key=lambda x: x.incident_id)],
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def find_by_id(incident_id: str, incidents: list[IncidentRecord] | None = None) -> IncidentRecord | None:
    items = incidents if incidents is not None else load_registry()
    key = incident_id.strip().upper()
    for rec in items:
        if rec.incident_id.upper() == key:
            return rec
    return None


def upsert_incident(record: IncidentRecord, path: Path | None = None) -> IncidentRecord:
    items = load_registry(path)
    record.last_updated = _now_iso()
    replaced = False
    for idx, existing in enumerate(items):
        if existing.incident_id.upper() == record.incident_id.upper():
            items[idx] = record
            replaced = True
            break
    if not replaced:
        items.append(record)
    save_registry(items, path)
    return record


def search_similar(
    text: str,
    *,
    incidents: list[IncidentRecord] | None = None,
    limit: int = 5,
) -> list[tuple[IncidentRecord, float]]:
    """Return incidents ranked by token overlap (duplicate / regression detection)."""
    items = incidents if incidents is not None else load_registry()
    query_tokens = _tokenize(text)
    if not query_tokens:
        return []
    scored: list[tuple[IncidentRecord, float]] = []
    for rec in items:
        blob = " ".join(
            [
                rec.title,
                rec.symptoms,
                rec.root_cause,
                rec.fix_implemented,
                " ".join(rec.files_modules),
                " ".join(rec.tags),
            ]
        )
        rec_tokens = _tokenize(blob)
        if not rec_tokens:
            continue
        overlap = len(query_tokens & rec_tokens) / max(len(query_tokens), 1)
        if overlap >= 0.15:
            scored.append((rec, overlap))
    scored.sort(key=lambda x: -x[1])
    return scored[:limit]


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", text.lower()) if t not in _STOPWORDS}


_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "was",
        "were",
        "not",
        "has",
        "have",
        "had",
        "are",
        "into",
        "when",
        "then",
        "than",
        "via",
        "bot",
        "batman",
    }
)


def build_dashboard(incidents: list[IncidentRecord] | None = None) -> dict[str, Any]:
    items = incidents if incidents is not None else load_registry()
    open_status = {s for s in VALID_LIFECYCLE if s != "closed"}
    open_list = [i for i in items if i.lifecycle in open_status]
    closed_list = [i for i in items if i.lifecycle == "closed"]
    by_category: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_robot: dict[str, int] = {}
    regression: list[IncidentRecord] = []
    recurring_root_causes: dict[str, int] = {}
    module_hits: dict[str, int] = {}

    for rec in items:
        by_category[rec.category] = by_category.get(rec.category, 0) + 1
        by_severity[rec.severity] = by_severity.get(rec.severity, 0) + 1
        if rec.robot_affected:
            by_robot[rec.robot_affected] = by_robot.get(rec.robot_affected, 0) + 1
        if rec.related_incidents or "regression" in rec.tags:
            regression.append(rec)
        if rec.root_cause:
            key = rec.root_cause[:120]
            recurring_root_causes[key] = recurring_root_causes.get(key, 0) + 1
        for mod in rec.files_modules:
            module_hits[mod] = module_hits.get(mod, 0) + 1

    top_modules = sorted(module_hits.items(), key=lambda x: -x[1])[:8]
    top_causes = sorted(recurring_root_causes.items(), key=lambda x: -x[1])[:8]

    return {
        "generated_at": _now_iso(),
        "total": len(items),
        "open": len(open_list),
        "closed": len(closed_list),
        "critical": sum(1 for i in items if i.severity == "critical"),
        "high": sum(1 for i in items if i.severity == "high"),
        "medium": sum(1 for i in items if i.severity == "medium"),
        "low": sum(1 for i in items if i.severity == "low"),
        "by_category": by_category,
        "by_severity": by_severity,
        "by_robot": by_robot,
        "regression_count": len(regression),
        "open_incidents": [i.incident_id for i in open_list],
        "top_modules": top_modules,
        "top_root_causes": top_causes,
    }


def render_registry_markdown(
    incidents: list[IncidentRecord] | None = None,
    *,
    dashboard: dict[str, Any] | None = None,
) -> str:
    items = incidents if incidents is not None else load_registry()
    dash = dashboard or build_dashboard(items)
    lines = [
        "# Incident Registry Dashboard",
        "",
        f"*Auto-generated: {dash['generated_at']}*",
        "",
        "## Summary metrics",
        "",
        "| Metric | Count |",
        "|--------|------:|",
        f"| Total incidents | {dash['total']} |",
        f"| Open | {dash['open']} |",
        f"| Closed | {dash['closed']} |",
        f"| Critical | {dash['critical']} |",
        f"| High | {dash['high']} |",
        f"| Medium | {dash['medium']} |",
        f"| Low | {dash['low']} |",
        f"| Regression-linked | {dash['regression_count']} |",
        "",
        "## By category",
        "",
        "| Category | Count |",
        "|----------|------:|",
    ]
    for cat, count in sorted(dash["by_category"].items()):
        lines.append(f"| {cat} | {count} |")
    lines.extend(["", "## By robot", "", "| Robot | Count |", "|-------|------:|"])
    for robot, count in sorted(dash["by_robot"].items()):
        lines.append(f"| {robot} | {count} |")
    lines.extend(
        [
            "",
            "## Top unstable modules",
            "",
        ]
    )
    for mod, count in dash["top_modules"]:
        lines.append(f"- `{mod}` — {count} incident(s)")
    lines.extend(["", "## Open incidents", ""])
    open_items = [i for i in items if i.lifecycle != "closed"]
    if not open_items:
        lines.append("*None — all tracked incidents closed.*")
    else:
        lines.extend(["| ID | Title | Severity | Lifecycle |", "|----|-------|----------|-----------|"])
        for rec in sorted(open_items, key=lambda x: x.incident_id):
            lines.append(
                f"| {rec.incident_id} | {rec.title[:60]} | {rec.severity} | {rec.lifecycle} |"
            )
    lines.extend(["", "## All incidents (index)", "", "| ID | Title | Category | Status | First seen |", "|----|-------|----------|--------|------------|"])
    for rec in sorted(items, key=lambda x: x.incident_id):
        status = "closed" if rec.lifecycle == "closed" else rec.lifecycle
        lines.append(
            f"| [{rec.incident_id}](records/{rec.incident_id}.md) | {rec.title[:50]} | {rec.category} | {status} | {rec.date_first_observed} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_incident_markdown(rec: IncidentRecord) -> str:
    def _list(title: str, items: list[str]) -> list[str]:
        if not items:
            return []
        out = [f"## {title}", ""]
        out.extend(f"- {x}" for x in items)
        out.append("")
        return out

    lines = [
        f"# {rec.incident_id} — {rec.title}",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Category | {rec.category} |",
        f"| Subsystem | {rec.subsystem} |",
        f"| Robot | {rec.robot_affected or '—'} |",
        f"| Lifecycle | {rec.lifecycle} |",
        f"| Severity | {rec.severity} |",
        f"| Priority | {rec.priority} |",
        f"| Environment | {rec.environment} |",
        f"| First observed | {rec.date_first_observed} |",
        f"| Resolved | {rec.date_resolved or '—'} |",
        f"| Owner | {rec.owner} |",
        f"| Last updated | {rec.last_updated} |",
    ]
    if rec.legacy_stab_id:
        lines.append(f"| Legacy STAB | {rec.legacy_stab_id} |")
    lines.extend(["", "## Symptoms", "", rec.symptoms or "—", ""])
    if rec.business_impact:
        lines.extend(["## Business impact", "", rec.business_impact, ""])
    if rec.technical_impact:
        lines.extend(["## Technical impact", "", rec.technical_impact, ""])
    if rec.trading_impact:
        lines.extend(["## Trading impact", "", rec.trading_impact, ""])
    lines.extend(["## Root cause", "", rec.root_cause or "—", ""])
    lines.extend(_list("Contributing factors", rec.contributing_factors))
    if rec.investigation:
        lines.extend(["## Investigation", "", rec.investigation, ""])
    lines.extend(_list("Files / modules", rec.files_modules))
    lines.extend(_list("Logs referenced", rec.logs_referenced))
    if rec.fix_implemented:
        lines.extend(["## Fix implemented", "", rec.fix_implemented, ""])
    if rec.fix_rationale:
        lines.extend(["## Why this fix works", "", rec.fix_rationale, ""])
    if rec.regression_risk:
        lines.extend(["## Regression risk", "", rec.regression_risk, ""])
    lines.extend(_list("Validation performed", rec.validation_performed))
    lines.extend(_list("Stress testing", rec.stress_testing))
    if rec.validation_cycles:
        lines.extend(["## Validation cycles", "", str(rec.validation_cycles), ""])
    lines.extend(_list("Remaining risks", rec.remaining_risks))
    lines.extend(_list("Related incidents", rec.related_incidents))
    lines.extend(_list("Runtime incident IDs", rec.runtime_incident_ids))
    lines.extend(_list("Preventive measures", rec.preventive_measures))
    lines.extend(_list("Lessons learned", rec.lessons_learned))
    lines.extend(_list("Future recommendations", rec.future_recommendations))
    return "\n".join(lines)


def export_markdown_docs(path: Path | None = None) -> tuple[Path, Path]:
    """Write REGISTRY.md and per-incident records/*.md."""
    items = load_registry(path)
    base = registry_path(path).parent
    records_dir = base / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    registry_md = base / "REGISTRY.md"
    registry_md.write_text(render_registry_markdown(items), encoding="utf-8")
    for rec in items:
        (records_dir / f"{rec.incident_id}.md").write_text(
            render_incident_markdown(rec), encoding="utf-8"
        )
    return registry_md, records_dir


def seed_registry_if_empty(path: Path | None = None) -> int:
    """Populate registry from STAB sprint + 2026-06-25 fixes when file missing."""
    p = registry_path(path)
    if p.is_file() and load_registry(p):
        return 0
    from core.incident_seed import build_seed_incidents

    incidents = build_seed_incidents()
    save_registry(incidents, p)
    export_markdown_docs(p)
    return len(incidents)


def merge_seed_incidents(path: Path | None = None) -> int:
    """Add seed incidents missing from an existing registry (idempotent)."""
    existing_ids = {r.incident_id.upper() for r in load_registry(path)}
    from core.incident_seed import build_seed_incidents

    merged = 0
    for rec in build_seed_incidents():
        if rec.incident_id.upper() not in existing_ids:
            upsert_incident(rec, path)
            merged += 1
    if merged:
        export_markdown_docs(path)
    return merged

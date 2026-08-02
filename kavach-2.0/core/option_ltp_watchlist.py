"""Resolve registered IC legs + ATO protect symbols into Dhan securityIds."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.batman_mode import deployments_dir, state_path, workspace_root

logger = logging.getLogger("batman.option_ltp_watchlist")

_ROLE_ORDER = ("pe_buy", "pe_sell", "ce_buy", "ce_sell")
_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


@dataclass(frozen=True)
class OptionWatchItem:
    role: str
    security_id: int
    symbol: str
    strike: int | None = None
    option_type: str | None = None


@dataclass
class OptionWatchlist:
    items: list[OptionWatchItem]
    source: str
    refreshed_at: float

    @property
    def security_ids(self) -> list[int]:
        return [i.security_id for i in self.items]

    def role_by_security_id(self) -> dict[int, str]:
        return {i.security_id: i.role for i in self.items}


def _parse_expiry(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    # ISO
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    # "04 Aug 2026" / "28 Jul 2026"
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})$", text)
    if m:
        day_i = int(m.group(1))
        mon = _MONTHS.get(m.group(2).upper()[:3])
        year = int(m.group(3))
        if mon:
            return date(year, mon, day_i)
    return None


def _leg_security_id(leg: dict[str, Any]) -> int | None:
    for key in ("instrument_token", "securityId", "security_id", "SecurityId"):
        raw = leg.get(key)
        if raw is None or raw == "":
            continue
        try:
            sid = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if sid > 0:
            return sid
    return None


def _find_active_deployment(root: Path | None = None) -> Path | None:
    dep_dir = deployments_dir(root)
    if not dep_dir.is_dir():
        return None
    files = sorted(
        dep_dir.glob("batman_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("watchlist: failed reading %s: %s", path, exc)
        return {}
    return raw if isinstance(raw, dict) else {}


def _positions_and_ato_from_sources(root: Path | None = None) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Prefer active deployment file; fall back to batman_state.json."""
    dep = _find_active_deployment(root)
    if dep is not None:
        data = _load_json(dep)
        positions = data.get("positions") if isinstance(data.get("positions"), dict) else {}
        ato = data.get("ato") if isinstance(data.get("ato"), dict) else {}
        if any(isinstance(positions.get(r), dict) for r in _ROLE_ORDER) or ato:
            return positions, ato, f"deployment:{dep.name}"

    state_file = state_path(root)
    if state_file.is_file():
        data = _load_json(state_file)
        positions = data.get("positions") if isinstance(data.get("positions"), dict) else {}
        nested = data.get("ato") if isinstance(data.get("ato"), dict) else {}
        # Also accept flat keys written by StateManager dumps.
        ato = dict(nested)
        for key, val in data.items():
            if str(key).startswith("ato.") and key[4:] not in ato:
                ato[key[4:]] = val
        if any(isinstance(positions.get(r), dict) for r in _ROLE_ORDER) or ato:
            return positions, ato, f"state:{state_file.name}"

    return {}, {}, "none"


def _resolve_protect_id(
    *,
    strike: int,
    option_type: str,
    expiry: date,
) -> int | None:
    try:
        from backtest_engine.resolver.instrument_master import resolve_nifty_option

        inst = resolve_nifty_option(
            strike=int(strike),
            option_type=str(option_type),
            expiry_date=expiry,
        )
        return int(inst.security_id)
    except Exception as exc:
        logger.warning(
            "watchlist: protect resolve failed %s %s %s: %s",
            strike,
            option_type,
            expiry,
            exc,
        )
        return None


def build_option_watchlist(root: Path | None = None) -> OptionWatchlist:
    """Build role→securityId list for registered legs + ATO protect."""
    ws = root or workspace_root()
    positions, ato, source = _positions_and_ato_from_sources(ws)
    items: list[OptionWatchItem] = []
    seen_ids: set[int] = set()

    expiry: date | None = None
    for role in _ROLE_ORDER:
        leg = positions.get(role)
        if not isinstance(leg, dict):
            continue
        sid = _leg_security_id(leg)
        if sid is None:
            continue
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        if expiry is None:
            expiry = _parse_expiry(leg.get("expiry") or leg.get("expiry_date"))
        items.append(
            OptionWatchItem(
                role=role,
                security_id=sid,
                symbol=str(leg.get("symbol") or ""),
                strike=int(leg["strike"]) if leg.get("strike") is not None else None,
                option_type=str(leg.get("opt_type") or leg.get("option_type") or "").upper()
                or None,
            )
        )

    # Protect legs — resolve via instrument master when token missing.
    for side in ("pe", "ce"):
        role = f"{side}_protect"
        sym = ato.get(f"{side}_protect_symbol")
        strike_raw = ato.get(f"{side}_protect_strike")
        if not sym and strike_raw is None:
            continue
        try:
            strike = int(strike_raw) if strike_raw is not None else None
        except (TypeError, ValueError):
            strike = None
        opt = "PE" if side == "pe" else "CE"
        sid: int | None = None
        if strike is not None and expiry is not None:
            sid = _resolve_protect_id(strike=strike, option_type=opt, expiry=expiry)
        if sid is None:
            # Try parse strike from symbol like NIFTY-Jul2026-24250-CE
            if strike is None and isinstance(sym, str):
                m = re.search(r"-(\d{4,6})-(CE|PE)$", sym.upper())
                if m:
                    strike = int(m.group(1))
                    opt = m.group(2)
            if strike is not None and expiry is not None:
                sid = _resolve_protect_id(strike=strike, option_type=opt, expiry=expiry)
        if sid is None or sid in seen_ids:
            continue
        seen_ids.add(sid)
        items.append(
            OptionWatchItem(
                role=role,
                security_id=sid,
                symbol=str(sym or ""),
                strike=strike,
                option_type=opt,
            )
        )

    return OptionWatchlist(items=items, source=source, refreshed_at=time.time())


class CachedOptionWatchlist:
    """Refresh deployment/state resolution periodically (not every poll)."""

    def __init__(self, *, root: Path | None = None, ttl_seconds: float = 60.0) -> None:
        self._root = root
        self._ttl = float(ttl_seconds)
        self._cached: OptionWatchlist | None = None

    def get(self) -> OptionWatchlist:
        now = time.time()
        if self._cached is not None and (now - self._cached.refreshed_at) < self._ttl:
            return self._cached
        self._cached = build_option_watchlist(self._root)
        return self._cached

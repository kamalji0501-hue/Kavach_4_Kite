"""Map broker position symbols to Batman / ATO leg type labels for the desk UI."""

from __future__ import annotations

from typing import Any

# Lower priority number wins when one symbol matches multiple roles.
_ROLE_LABELS: list[tuple[str, str, int]] = [
    ("pe_sell", "PE Sell", 10),
    ("ce_sell", "CE Sell", 10),
    ("pe_buy", "PE Core Buy", 20),
    ("ce_buy", "CE Core Buy", 20),
    ("pe_margin_hedge", "PE M-Hedge", 30),
    ("ce_margin_hedge", "CE M-Hedge", 30),
    ("pe_dyn_hedge", "PE Dyn Hedge", 40),
    ("ce_dyn_hedge", "CE Dyn Hedge", 40),
]


def _norm_sym(raw: Any) -> str:
    return str(raw or "").strip().upper()


def _state_get(state: Any, key: str, default: Any = None) -> Any:
    if state is None:
        return default
    try:
        if hasattr(state, "get"):
            return state.get(key, default)
    except Exception:
        pass
    if isinstance(state, dict):
        return state.get(key, default)
    return default


def build_symbol_type_map(state: Any) -> dict[str, str]:
    """symbol(upper) -> display label from registered positions + ATO protect."""
    scored: dict[str, tuple[int, str]] = {}

    def _put(sym: str, label: str, priority: int) -> None:
        if not sym:
            return
        cur = scored.get(sym)
        if cur is None or priority < cur[0]:
            scored[sym] = (priority, label)

    for role, label, priority in _ROLE_LABELS:
        leg = _state_get(state, f"positions.{role}")
        if isinstance(leg, dict):
            _put(_norm_sym(leg.get("symbol")), label, priority)

    # ATO protect: lower priority than Batman legs if same symbol somehow overlaps.
    _put(_norm_sym(_state_get(state, "ato.ce_protect_symbol")), "CE ATO", 50)
    _put(_norm_sym(_state_get(state, "ato.pe_protect_symbol")), "PE ATO", 50)

    return {sym: label for sym, (_prio, label) in scored.items()}


def annotate_positions_with_types(
    positions: list[dict[str, Any]] | None,
    state: Any,
) -> list[dict[str, Any]]:
    """Return shallow-copied rows with ``type`` set (Extra if unmatched)."""
    rows = list(positions or [])
    mapping = build_symbol_type_map(state)
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        sym = _norm_sym(item.get("symbol"))
        item["type"] = mapping.get(sym, "Extra")
        out.append(item)
    return out

"""SARANSH cold path — read ATO JSONL feed, render Telegram + XLSX."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from core.ato_cycle_feed import read_cycle_state
from core.batman_mode import is_uat
from core.saransh_paths import ato_cycle_feed_path, saransh_analytics_dir
from core.saransh_session_sync import read_session_manifest

logger = logging.getLogger(__name__)
_IST = ZoneInfo("Asia/Kolkata")
_TELEGRAM_CHUNK = 3800


@dataclass(frozen=True)
class CompletedCycle:
    side: str
    sell_strike: int
    buy_nifty_ltp: float
    sell_nifty_ltp: float
    point_impact: float
    lots: float
    timestamp_ist: str
    protect_strike: int = 0
    buy_option_premium: float = 0.0
    sell_option_premium: float = 0.0
    premium_pnl: float = 0.0
    buy_timestamp_ist: str = ""
    sell_timestamp_ist: str = ""

    @property
    def premium_diff(self) -> float:
        """ATO premium P&L in points: sell price − buy price of the protect leg."""
        return round(self.sell_option_premium - self.buy_option_premium, 2)


def _parse_feed_date(ts: str) -> date | None:
    raw = (ts or "").replace(" IST", "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def _format_time_ist(ts: str) -> str:
    """HH:MM from an IST timestamp string."""
    if " " in ts:
        return ts.split(" ")[1][:5]
    return ""


def load_today_completed_cycles(*, root: Path | None = None) -> list[CompletedCycle]:
    path = ato_cycle_feed_path(root)
    if not path.is_file():
        return []
    today = datetime.now(_IST).date()
    pending_buys: dict[str, list[str]] = {"CE": [], "PE": []}
    cycles: list[CompletedCycle] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event = row.get("event")
                if not str(row.get("deployment_file") or "").strip():
                    continue
                side = str(row.get("side") or "?").upper()
                if event == "ato_buy":
                    buy_ts = str(row.get("timestamp_ist") or "")
                    if _parse_feed_date(buy_ts) == today:
                        pending_buys.setdefault(side, []).append(buy_ts)
                    continue
                if event != "cycle_complete":
                    continue
                sell_ts = str(row.get("timestamp_ist") or "")
                if _parse_feed_date(sell_ts) != today:
                    continue
                buy_ts = str(row.get("buy_timestamp_ist") or "")
                if not buy_ts:
                    queue = pending_buys.get(side, [])
                    if queue:
                        buy_ts = queue.pop(0)
                cycles.append(
                    CompletedCycle(
                        side=side,
                        sell_strike=int(row.get("sell_strike") or 0),
                        buy_nifty_ltp=float(row.get("buy_nifty_ltp") or 0),
                        sell_nifty_ltp=float(row.get("sell_nifty_ltp") or 0),
                        point_impact=float(row.get("point_impact") or 0),
                        lots=float(row.get("lots") or 0),
                        timestamp_ist=sell_ts,
                        protect_strike=int(row.get("protect_strike") or 0),
                        buy_option_premium=float(row.get("buy_option_premium") or 0),
                        sell_option_premium=float(row.get("sell_option_premium") or 0),
                        premium_pnl=float(row.get("premium_pnl") or 0),
                        buy_timestamp_ist=buy_ts,
                        sell_timestamp_ist=sell_ts,
                    )
                )
    except OSError as exc:
        logger.warning("SARANSH feed read failed: %s", exc)
    return cycles


def load_deployment_protect_strikes(*, root: Path | None = None) -> dict[str, int | None]:
    """ATO protect strikes per side from the active deployment (fallback source).

    The cycle feed carries ``protect_strike`` for new cycles; for older rows or
    live holdings without it, we resolve from the registered deployment's ATO
    block (``pe_protect_strike`` / ``ce_protect_strike``).
    """
    from core.saransh_paths import deployment_dir

    out: dict[str, int | None] = {"CE": None, "PE": None}
    try:
        files = sorted(deployment_dir(root).glob("batman_*.json"))
    except Exception:
        return out
    if not files:
        return out
    try:
        with open(files[-1], encoding="utf-8") as fh:
            dep = json.load(fh)
    except Exception as exc:
        logger.warning("SARANSH deployment protect-strike read failed: %s", exc)
        return out
    ato = (dep.get("ato") or {}) if isinstance(dep, dict) else {}
    for side, key in (("CE", "ce_protect_strike"), ("PE", "pe_protect_strike")):
        val = ato.get(key)
        try:
            out[side] = int(val) if val is not None else None
        except (TypeError, ValueError):
            out[side] = None
    return out


def _resolve_ato_strike(
    side: str,
    feed_value: int | None,
    fallback: dict[str, int | None],
) -> str:
    if feed_value:
        return str(feed_value)
    dep_value = fallback.get(side.upper())
    return str(dep_value) if dep_value else "—"


def load_live_ato_status(*, root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Live per-side ATO status from the shared ``batman_state.json``.

    This is the SAME source KAVACH2's ATO Status card reads
    (``ato.ce_triggered`` / ``ato.ce_ato_active``), so SARANSH agrees with
    KAVACH2 even for custom-economy-profile breaches where the protect leg is
    pre-bought and no algo buy (hence no cycle-feed row) is recorded.
    """
    from core.batman_mode import state_path

    out: dict[str, dict[str, Any]] = {
        "CE": {"triggered": False, "active": False, "protect_strike": None},
        "PE": {"triggered": False, "active": False, "protect_strike": None},
    }
    try:
        with open(state_path(root), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("SARANSH live ATO state read failed: %s", exc)
        return out
    ato = data.get("ato") if isinstance(data, dict) else None
    if not isinstance(ato, dict):
        return out
    for side, prefix in (("CE", "ce"), ("PE", "pe")):
        strike_raw = ato.get(f"{prefix}_protect_strike")
        try:
            strike = int(strike_raw) if strike_raw is not None else None
        except (TypeError, ValueError):
            strike = None
        out[side] = {
            "triggered": bool(ato.get(f"{prefix}_triggered")),
            "active": bool(ato.get(f"{prefix}_ato_active")),
            "protect_strike": strike,
        }
    return out


def _live_status_line(
    side: str,
    live: dict[str, dict[str, Any]],
    fallback: dict[str, int | None],
    cycle_leg: dict[str, Any] | None = None,
) -> str:
    """Per-side ATO line driven by live KAVACH state (matches KAVACH2 card)."""
    info = live.get(side) or {}
    triggered = bool(info.get("triggered"))
    active = bool(info.get("active"))
    if triggered or active:
        strike = _resolve_ato_strike(side, info.get("protect_strike"), fallback)
        state_word = "Holding ATO" if active else "ATO Triggered"
        since = ""
        if cycle_leg and cycle_leg.get("holding_since_ist"):
            raw = cycle_leg["holding_since_ist"]
            if isinstance(raw, str) and " " in raw:
                raw = raw.split(" ")[1][:5]
            since = f" since {_he(raw)}"
        return f"🔴 <b>{side}:</b> {state_word} — protect <b>{_he(strike)}</b>{since}"
    return f"🟢 <b>{side}:</b> Not Holding ATO"


def _he(text: Any) -> str:
    """Minimal HTML escape for Telegram HTML parse mode."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _is_real_holding(leg: dict[str, Any]) -> bool:
    """A live ATO holding must belong to a real deployment (guards test data)."""
    return bool(leg.get("holding")) and bool(str(leg.get("deployment_file") or "").strip())


def _holding_line(side: str, leg: dict[str, Any], fallback: dict[str, int | None]) -> str | None:
    if not _is_real_holding(leg):
        return None
    since = leg.get("holding_since_ist") or "?"
    if isinstance(since, str) and " " in since:
        since = since.split(" ")[1][:5]
    ato_strike = _resolve_ato_strike(side, leg.get("protect_strike"), fallback)
    sell_strike = leg.get("sell_strike") or "?"
    return (
        f"🟡 <b>{side}:</b> holding ATO <b>{_he(ato_strike)}</b> "
        f"since {_he(since)} <i>(sell {_he(sell_strike)})</i>"
    )


def _format_impact(value: float) -> str:
    if value > 0:
        return f"+{value:.1f}"
    return f"{value:.1f}"


def _net_impact_html(net: float) -> str:
    icon = "🟢" if net >= 0 else "🔴"
    return f"{icon} <b>Net Point Impact:</b> <code>{net:+.2f}</code>"


def render_ato_cycle_messages(
    *,
    root: Path | None = None,
    orders_today: int | None = None,
    orders_alltime: int | None = None,
) -> list[str]:
    """HTML ATO-cycle card; ATO (protect) strikes, multi-message if needed."""
    state = read_cycle_state(root=root)
    cycles = load_today_completed_cycles(root=root)
    manifest = read_session_manifest(root=root) or {}
    fallback = load_deployment_protect_strikes(root=root)

    session = _he(str(manifest.get("status", "idle")).capitalize())
    session_id = _he(manifest.get("session_id", "—"))
    header_lines: list[str] = [
        "🔄 <b>ATO Cycle</b>",
        f"<b>Session:</b> {session} · <code>{session_id}</code>",
        "",
        f"📊 <b>Round Trips Today:</b> {len(cycles)}",
    ]
    if orders_today is not None:
        header_lines.append(f"🧾 <b>Orders</b> — <b>Today:</b> {orders_today}")

    header_lines.append("")
    live = load_live_ato_status(root=root)
    header_lines.append(_live_status_line("CE", live, fallback, state.get("ce") or {}))
    header_lines.append("")
    header_lines.append(_live_status_line("PE", live, fallback, state.get("pe") or {}))

    # Net impact = sum of ATO premium P&L (sell price − buy price of the protect
    # option), derived from the guarded cycles — not the raw state file.
    net = round(sum(c.premium_diff for c in cycles), 2)

    if not cycles:
        header_lines.append("")
        header_lines.append("<i>No completed cycles today.</i>")
        header_lines.append(_net_impact_html(net))
        return ["\n".join(header_lines)]

    # Monospaced table: Entry/Exit are ATO buy/sell times; Buy/Sell are protect
    # option premiums; Impact is premium difference (sell − buy).
    table_header = (
        f"{'Side':<5}{'ATO':<7}{'Entry':<7}{'Buy':<8}{'Exit':<7}{'Sell':<8}{'Impact':<8}"
    )
    table_rows: list[str] = []
    for c in cycles:
        entry_bit = _format_time_ist(c.buy_timestamp_ist)
        exit_bit = _format_time_ist(c.sell_timestamp_ist or c.timestamp_ist)
        ato = _resolve_ato_strike(c.side, c.protect_strike, fallback)
        table_rows.append(
            f"{c.side:<5}{ato:<7}{entry_bit:<7}{c.buy_option_premium:<8.2f}"
            f"{exit_bit:<7}{c.sell_option_premium:<8.2f}{c.premium_diff:<+8.2f}"
        )

    header = "\n".join(header_lines)
    footer = _net_impact_html(net)

    def _wrap(rows: list[str]) -> str:
        body = "\n".join([table_header, *rows])
        return f"{header}\n\n<pre>{_he(body)}</pre>\n{footer}"

    full = _wrap(table_rows)
    if len(full) <= _TELEGRAM_CHUNK:
        return [full]

    # Split table rows across messages if the day was very busy.
    chunks: list[str] = []
    current: list[str] = []
    for row in table_rows:
        candidate = _wrap([*current, row])
        if current and len(candidate) > _TELEGRAM_CHUNK:
            chunks.append(_wrap(current))
            current = [row]
        else:
            current.append(row)
    if current:
        chunks.append(_wrap(current))
    return chunks


def uat_pnl_disclaimer(*, root: Path | None = None) -> str:
    if is_uat(root):
        return (
            "\n\nUAT shadow PnL — system calculated; may not match Sensibull screenshot."
        )
    return ""


def write_session_xlsx(
    *,
    root: Path | None = None,
    cycles: list[CompletedCycle] | None = None,
    summary_payload: dict[str, Any] | None = None,
) -> Path | None:
    """Heavy XLSX — SARANSH only (Q16)."""
    try:
        import pandas as pd
    except ImportError:
        logger.warning("pandas unavailable — XLSX skipped")
        return None

    base = saransh_analytics_dir(root)
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(_IST).strftime("%Y%m%d")
    out = base / f"summary_{ts}.xlsx"
    cycles = cycles if cycles is not None else load_today_completed_cycles(root=root)
    manifest = read_session_manifest(root=root) or {}
    state = read_cycle_state(root=root)

    cycle_rows = [
        {
            "side": c.side,
            "protect_strike": c.protect_strike,
            "entry_time_ist": c.buy_timestamp_ist,
            "buy_option_premium": c.buy_option_premium,
            "exit_time_ist": c.sell_timestamp_ist or c.timestamp_ist,
            "sell_option_premium": c.sell_option_premium,
            "premium_impact": c.premium_diff,
            "sell_strike": c.sell_strike,
            "buy_nifty_ltp": c.buy_nifty_ltp,
            "sell_nifty_ltp": c.sell_nifty_ltp,
            "point_impact": c.point_impact,
            "lots": c.lots,
        }
        for c in cycles
    ]
    try:
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            pd.DataFrame(cycle_rows).to_excel(writer, sheet_name="Cycles", index=False)
            pd.DataFrame([manifest]).to_excel(writer, sheet_name="Session", index=False)
            pd.DataFrame([state]).to_excel(writer, sheet_name="LiveState", index=False)
            if summary_payload:
                flat = {k: str(v) for k, v in summary_payload.items() if not isinstance(v, dict)}
                pd.DataFrame([flat]).to_excel(writer, sheet_name="DailySummary", index=False)
        return out
    except Exception as exc:
        logger.warning("SARANSH XLSX write failed: %s", exc)
        return None

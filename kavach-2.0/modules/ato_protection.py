"""
Batman v3 — ATO (Adjustment To Original) Protection Module.

Monitors NIFTY spot against the deployed iron-condor sell strikes.

Breach logic  — ATO entry fires the moment NIFTY TOUCHES the sell strike:
  • CE breach  : spot ≥ ce_sell_strike
                 → BUY N lots at CE protect strike (ce_sell_strike + 50)
  • PE breach  : spot ≤ pe_sell_strike
                 → BUY N lots at PE protect strike (pe_sell_strike − 50)

Where N = abs(positions.ce_buy.qty) = buy_lots × lot_size.
ATO qty always matches the deployed buy leg (1:2 ratio is preserved).

Retracement logic  — retrace_points buffer applied ONLY on the EXIT side:
  • CE retrace : ATO CE active AND spot ≤ ce_sell_strike - retrace_points
                 → SELL N lots at CE protect strike
                 → ce_triggered reset to False
  • PE retrace : ATO PE active AND spot ≥ pe_sell_strike + retrace_points
                 → SELL N lots at PE protect strike
                 → pe_triggered reset to False

The asymmetric buffer design:
  entry fires  the moment spot TOUCHES the sell strike (no delay)
  exit  fires  only when spot pulls back retrace_points inside the strike
This prevents whipsaw ATO exit/re-entry without delaying ATO entry protection.

ATO protect symbols are resolved at /deploy wizard time
(deploy_wizard.py) and stored in the deployment file at
  data/deployments/batman_*.json
  (fields: ato.ce_protect_symbol / ato.ce_protect_strike / ato.pe_protect_symbol / ato.pe_protect_strike)
"""

from __future__ import annotations

import csv
import glob
import io
import json
import logging
import pathlib
import shutil
import threading
from decimal import Decimal
from typing import Any, Literal, cast

from core import utils
from core.ato_book_validation import lots_fulfilled, net_qty_for_symbol
from core.ato_cycle_feed import record_ato_buy, record_ato_cycle_complete
from core.ato_idempotency import (
    ato_order_key,
    clear_ato_order,
    clear_side_cycle_keys,
    get_existing_ato_order,
    record_ato_order,
)
from core.ato_manual_leg_sync import ManualLegSyncResult, evaluate_side_manual_sync
from core.ato_operator_config import ato_operator_settings, soft_cap_should_warn
from core.ato_position_book import read_positions_with_retry
from core.ato_side_state import halt_side, is_side_halted, pause_all_ato
from core.batman_mode import deployments_dir, workspace_root
from core.buffer_config import normalize_buffer_field
from core.deployment_lock import DeploymentLockBusy, deployment_session
from core.event_bus import Event
from core.module_base import ModuleBase
from core.nifty_ltp_feed import consumer_max_age_for_trading, resolve_nifty_ltp_from_cache
from core.positions import build_ato_protect_symbol
from core.saransh_paths import ato_analytics_dir, legacy_telemetry_csv_path

logger = logging.getLogger(__name__)
_CSV_IO_LOCK = threading.Lock()

_ROOT = workspace_root()
_PARAMS_PATH = _ROOT / "telegram" / "bots" / "kavach2" / "params.json"
_SIDE_BATMAN_ROLES = {"CE": ("ce_buy", "ce_sell"), "PE": ("pe_buy", "pe_sell")}
_TELEMETRY_FILE = legacy_telemetry_csv_path(_ROOT)
_TELEMETRY_HEADERS = [
    "timestamp_ist",
    "deployment_file",
    "side",
    "action",
    "trigger_reason",
    "nifty_ltp_at_execution",
    "option_premium",
    "sell_strike",
    "trigger_level_used",
    "protect_strike",
    "protect_symbol",
    "order_id",
    "qty",
    "poll_interval_seconds_used",
]

_ATO_LEDGER_FILE = ato_analytics_dir(_ROOT) / "ato_trade_ledger.csv"
_ATO_LEDGER_SNAPSHOT_DIR = ato_analytics_dir(_ROOT) / "snapshots"


def apply_ato_analytics_paths(root: pathlib.Path | None = None) -> None:
    """Point ATO telemetry/ledger at data/{mode}/analytics/ato/ (OQ-P1-20)."""
    global _ROOT, _TELEMETRY_FILE, _ATO_LEDGER_FILE, _ATO_LEDGER_SNAPSHOT_DIR
    base = root or workspace_root()
    _ROOT = base
    _TELEMETRY_FILE = legacy_telemetry_csv_path(base)
    ato_dir = ato_analytics_dir(base)
    _ATO_LEDGER_FILE = ato_dir / "ato_trade_ledger.csv"
    _ATO_LEDGER_SNAPSHOT_DIR = ato_dir / "snapshots"


_ATO_LEDGER_HEADERS = [
    "date_ist",
    "timestamp_ist",
    "deployment_file",
    "side",
    "cycle_index",
    "entry_source",
    "buy_timestamp_ist",
    "buy_order_id",
    "buy_nifty_ltp",
    "buy_option_premium",
    "sell_timestamp_ist",
    "sell_order_id",
    "sell_nifty_ltp",
    "sell_option_premium",
    "sell_strike",
    "entry_trigger_level",
    "exit_trigger_level",
    "entry_buffer_points",
    "retrace_points",
    "protect_strike",
    "protect_symbol",
    "qty",
    "lots",
    "points_lost",
    "points_lost_x_lots",
    "premium_pnl",
    "premium_pnl_rupees",
    "poll_interval_seconds_used",
]


def _serialize_csv_row(row: dict[str, Any], headers: list[str]) -> str:
    """Serialize a row exactly as DictWriter would write it for duplicate checks."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers)
    writer.writerow(row)
    return buf.getvalue().strip("\r\n")


def _parse_protect_strike_opt(symbol: str) -> tuple[int, str]:
    """Extract (strike, CE|PE) from Batman or display option symbols."""
    import re

    sym = str(symbol or "").strip()
    m = re.search(r"-(\d{4,5})-(CE|PE)$", sym, re.I)
    if m:
        return int(m.group(1)), m.group(2).upper()
    m = re.search(r"(\d{4,5})\s*(CE|PE|CALL|PUT)\b", sym, re.I)
    if m:
        opt = m.group(2).upper()
        if opt == "CALL":
            opt = "CE"
        elif opt == "PUT":
            opt = "PE"
        return int(m.group(1)), opt
    return 0, ""


def _fmt_premium(value: float | None) -> str:
    if value is None:
        return ""
    return f"{float(value):.2f}"


def _migrate_csv_headers(path: pathlib.Path, headers: list[str]) -> None:
    """Rewrite CSV if columns were extended (keeps old row values)."""
    if not path.exists() or path.stat().st_size == 0:
        return
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        old_fields = list(reader.fieldnames or [])
        if old_fields == headers:
            return
        rows = list(reader)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({h: row.get(h, "") for h in headers})


def _last_non_empty_line(path: pathlib.Path) -> str:
    """Return the last non-empty line from a text file, or empty string if none."""
    if not path.exists() or path.stat().st_size == 0:
        return ""
    with open(path, encoding="utf-8", newline="") as fh:
        for line in reversed(fh.read().splitlines()):
            if line.strip():
                return line.strip()
    return ""


class ATOProtection(ModuleBase):
    name = "ato_protection"

    def _run(self) -> None:
        cfg_ato = self.config.get("ato", {})
        poll_interval = self._effective_poll_interval(cfg_ato)

        self.log.info("ATO Protection started — polling every %ss", poll_interval)

        # Seed retrace_points from config if state doesn't already have a value
        # (first run or after a state reset).  Live changes via /ato override this.
        if self.state.get("ato.retrace_points") is None:
            default_pts = cfg_ato.get("default_retrace_points", 5)
            self.state.set("ato.retrace_points", default_pts)
            self.log.info("ATO retrace_points initialised from config: %d", default_pts)

        # ── Auto-restore from previous deployment file ────────────────────────
        # On VPS restart, load the most recent batman_*.json and validate that
        # the 4 iron-condor legs are still open at the broker.
        # If ALL positions are confirmed → resume monitoring automatically.
        # If ANY leg is missing         → publish mismatch event and wait.
        dep = self._load_deployment_file()
        if dep is not None:
            confirmed, missing = self._validate_broker_positions(dep)
            positions = dep.get("positions", {})
            ato = dep.get("ato", {})
            if not missing:  # all 4 legs confirmed at broker
                self.events.publish(
                    Event.DEPLOYMENT_RESTORED,
                    {
                        "file": self.state.get("deployment.file"),
                        "registered_at": dep.get("registered_at", ""),
                        "positions": positions,
                        "ato": ato,
                        "retrace_points": dep.get("retrace_points", 0),
                        "confirmed": confirmed,
                    },
                )
                self.log.info(
                    "ATO restore: all %d positions validated — resuming monitoring",
                    len(confirmed),
                )
            else:
                self.log.warning(
                    "ATO restore: %d position(s) missing at broker — %s",
                    len(missing),
                    [m.get("symbol") for m in missing],
                )
                # Clear the state we just set so the gate below will wait
                self.state.set("deployment.confirmed", False)
                self.events.publish(
                    Event.DEPLOYMENT_RESTORE_MISMATCH,
                    {
                        "file": self.state.get("deployment.file"),
                        "confirmed": confirmed,
                        "missing": missing,
                    },
                )

        # ── Deployment confirmation gate ──────────────────────────────────────
        # ATO monitoring must not start until the user has confirmed Batman
        # is deployed and the 4 legs are loaded into state via /confirm_deploy.
        self.log.info("ATO Protection: waiting for deployment confirmation …")
        while not self.state.get("deployment.confirmed", False):
            if self._sleep(5):
                return
            # After Batman Complete, stay idle but keep watching for a new Register.
            # (Previously this nested forever until process stop — missed mid-session redeploy.)
            if self.state.get("deployment.batman_complete", False):
                self.log.info(
                    "ATO Protection: batman_complete=True — idling until next deploy "
                    "(re-check every 5s)"
                )
                continue
        self.log.info("ATO Protection: deployment confirmed — starting monitoring")
        self._wait_for_monitoring_start()

        # Per-session ATO cycle counters (instance vars — reset each time module starts)
        self._ce_cycles: int = 0
        self._pe_cycles: int = 0
        self._ce_breach_only_count: int = 0
        self._pe_breach_only_count: int = 0
        self._ce_soft_cap_last_exposure: int = -1
        self._pe_soft_cap_last_exposure: int = -1
        self._ce_qty_mismatch_halted: bool = False
        self._pe_qty_mismatch_halted: bool = False
        self._ce_manual_exit_halted: bool = False
        self._pe_manual_exit_halted: bool = False
        self._book_unreadable_paused: bool = False
        self._book_recovery_notified: bool = False
        self._consecutive_ltp_failures: int = 0
        self._ltp_failure_alerted: bool = False

        self._startup_scan()

        while not self._stop_event.is_set():
            try:
                from core.ato_monitoring_schedule import (
                    ato_session_open_for_breach,
                    is_past_monitoring_start,
                )

                # Live: NSE cash hours. UAT: also allow when DRISHTI uat_replay is fresh.
                if not ato_session_open_for_breach():
                    if self._sleep(30):
                        return
                    continue

                self.state.refresh_algo_flags_from_disk()
                if not self.state.get("deployment.confirmed", False):
                    if self._sleep(self._effective_poll_interval(cfg_ato)):
                        return
                    continue
                if self.state.get("algo.paused", False):
                    if self._sleep(self._effective_poll_interval(cfg_ato)):
                        return
                    continue

                if not is_past_monitoring_start():
                    if self._sleep(self._effective_poll_interval(cfg_ato)):
                        return
                    continue

                self._check_breach()

            except Exception as exc:
                self.log.error("ATO check error: %s", exc)

            poll_interval = self._effective_poll_interval(cfg_ato)
            if self._sleep(poll_interval):
                return

    def _wait_for_monitoring_start(self) -> None:
        """Idle until 09:25 IST session start, or immediately if UAT replay is live."""
        import time as time_mod

        from core.ato_monitoring_schedule import (
            ato_session_open_for_breach,
            is_past_monitoring_start,
            is_uat_replay_feed_active,
            monitoring_start_hhmm,
        )

        start_label = monitoring_start_hhmm()
        self.log.info(
            "ATO Protection: armed — monitoring scheduled for %s IST "
            "(UAT replay may unlock off-hours)",
            start_label,
        )
        last_log = 0.0
        while not self._stop_event.is_set():
            if is_past_monitoring_start():
                if is_uat_replay_feed_active():
                    self.log.info(
                        "ATO Protection: UAT replay feed active — starting breach checks now"
                    )
                else:
                    self.log.info(
                        "ATO Protection: monitoring start time reached (%s IST)",
                        start_label,
                    )
                return
            if not ato_session_open_for_breach():
                if self._sleep(30):
                    return
                continue
            now_mono = time_mod.monotonic()
            if now_mono - last_log >= 60.0:
                self.log.info(
                    "ATO Protection: running OK — waiting for monitoring start (%s IST)",
                    start_label,
                )
                last_log = now_mono
            if self._sleep(10):
                return

    def _effective_poll_interval(self, cfg_ato: dict[str, Any]) -> int:
        state_poll = self.state.get("ato.poll_interval_seconds")
        if isinstance(state_poll, int) and state_poll > 0:
            return state_poll
        return int(cfg_ato.get("poll_interval_seconds", 2))

    def _resolve_nifty_spot(self) -> Decimal:
        """Read DRISHTI shared cache only — never call Dhan from ATO."""
        max_age = consumer_max_age_for_trading()
        spot = resolve_nifty_ltp_from_cache(max_age_seconds=max_age)
        self._consecutive_ltp_failures = 0
        return Decimal(str(spot))

    def _maybe_alert_ltp_failures(self, cfg_ato: dict[str, Any]) -> None:
        threshold = int(cfg_ato.get("ltp_failure_alert_threshold", 5))
        failures = getattr(self, "_consecutive_ltp_failures", 0)
        if failures < threshold:
            return
        if not getattr(self, "_ltp_failure_alerted", False):
            self._ltp_failure_alerted = True
            self.log.error(
                "ATO: %d consecutive LTP cache failures — DRISHTI feed required (no Dhan poll from KAVACH)",
                failures,
            )
            self.events.publish(
                Event.MODULE_ERROR,
                {
                    "module": self.name,
                    "scenario": "module_error",
                    "failures": failures,
                    "error": "NIFTY LTP cache stale or missing — check DRISHTI / nifty_ltp_cache.json",
                },
            )
        pause_after = int(cfg_ato.get("ltp_failure_pause_after", threshold))
        if failures >= pause_after and not self.state.get("algo.paused", False):
            self.state.set("algo.paused", True)
            self.state.set("algo.pause_reason", "nifty_ltp_cache_stale")
            self.log.warning(
                "ATO: pausing algo after %d stale cache reads — restart DRISHTI or wait for cache",
                failures,
            )

    def _operator_settings(self) -> dict[str, Any]:
        """Operator tunables from params.json (docs/KAVACH_ATO_OPERATOR_RULES.md)."""
        cached = getattr(self, "_cached_operator_settings", None)
        if cached is not None:
            return cached
        params: dict[str, Any] = {}
        try:
            with open(_PARAMS_PATH, encoding="utf-8") as fh:
                params = json.load(fh)
        except Exception:
            params = {}
        overlay = self.config.get("ato_operator")
        if isinstance(overlay, dict):
            merged = dict(params.get("ato_operator") or {})
            merged.update(overlay)
            params["ato_operator"] = merged
        self._cached_operator_settings = ato_operator_settings(params)
        return self._cached_operator_settings

    def _place_ato_aggressive_limit(
        self,
        *,
        symbol: str,
        qty: int,
        side: str,
        product: str,
    ) -> str:
        """ATO protect entry/exit — SEBI-safe marketable LIMIT (not MARKET)."""
        op = self._operator_settings()
        place = getattr(self.broker, "place_aggressive_limit", None)
        if callable(place):
            return str(
                place(
                    symbol=symbol,
                    qty=qty,
                    side=side,
                    buffer_pct=float(op.get("limit_buffer_pct", 10.0)),
                    tick_size=float(op.get("limit_tick_size", 0.05)),
                    chase_timeout_sec=float(op.get("limit_chase_timeout_sec", 45.0)),
                    chase_interval_sec=float(op.get("limit_chase_interval_sec", 5.0)),
                    trade_type=product,
                )
            )
        # Legacy test doubles without place_aggressive_limit.
        return str(
            self.broker.place_market_order(
                symbol=symbol,
                qty=qty,
                side=side,
                trade_type=product,
            )
        )

    def _manual_protect_adopt_enabled(self) -> bool:
        """Q81/26A adopt path — operator can disable via config/settings.json → ato."""
        return bool(self.config.get("ato", {}).get("manual_protect_adopt_enabled", True))

    def _side_prefix(self, side: str) -> str:
        return "ce" if str(side).upper() == "CE" else "pe"

    def _increment_breach_only_count(self, side: str) -> int:
        prefix = self._side_prefix(side)
        attr = f"_{prefix}_breach_only_count"
        new_val = getattr(self, attr, 0) + 1
        setattr(self, attr, new_val)
        return new_val

    def _maybe_soft_cap_warn(self, side: str, spot: float) -> None:
        """Warn operator on choppy session — never auto-stop ATO (operator rules §6)."""
        op = self._operator_settings()
        prefix = self._side_prefix(side)
        cycles = getattr(self, f"_{prefix}_cycles", 0)
        breach_only = getattr(self, f"_{prefix}_breach_only_count", 0)
        if not soft_cap_should_warn(
            cycle_count=cycles,
            breach_only_count=breach_only,
            settings=op,
        ):
            return
        if op.get("monitor_breach_counts_toward_soft_cap", True):
            exposure = max(cycles, breach_only)
        else:
            exposure = cycles
        last_attr = f"_{prefix}_soft_cap_last_exposure"
        if getattr(self, last_attr, -1) == exposure:
            return
        setattr(self, last_attr, exposure)
        first = int(op.get("soft_cap_first_warn_cycles", 3))
        self.log.warning(
            "%s ATO soft cap — exposure %d (cycles=%d breach_only=%d) spot=%.1f",
            side,
            exposure,
            cycles,
            breach_only,
            spot,
        )
        self.events.publish(
            Event.ATO_MAX_CYCLES_REACHED,
            {
                "side": side.upper(),
                "cycles": cycles,
                "breach_only_count": breach_only,
                "exposure": exposure,
                "soft_cap": True,
                "soft_cap_first": first,
                "spot": spot,
            },
        )

    def _execute_protect_buy(
        self,
        *,
        side: str,
        symbol: str,
        ato_qty: int,
        product: str,
        idem_key: str,
    ) -> str | None:
        """Place BUY with book validation + retries; halt side when exhausted."""
        op = self._operator_settings()
        max_retries = int(op.get("order_retry_max", 3))
        lot_size = int(op.get("lot_size", 65))
        tag = side.upper()

        existing = get_existing_ato_order(self.state, idem_key)
        if existing:
            return str(existing)

        net = net_qty_for_symbol(self.broker, symbol)
        if net is not None and lots_fulfilled(net, ato_qty, lot_size):
            self.log.info("%s ATO book already shows fill for %s (qty=%d)", tag, symbol, net)
            return "BOOK_FILLED"

        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                order_id = self._place_ato_aggressive_limit(
                    symbol=symbol,
                    qty=ato_qty,
                    side="BUY",
                    product=product,
                )
                record_ato_order(self.state, idem_key, str(order_id))
                net_after = net_qty_for_symbol(self.broker, symbol)
                if net_after is None or lots_fulfilled(net_after, ato_qty, lot_size):
                    return str(order_id)
                self.log.warning(
                    "%s ATO buy attempt %d — book qty %s != expected %d",
                    tag,
                    attempt,
                    net_after,
                    ato_qty,
                )
            except Exception as exc:
                last_exc = exc
                net_retry = net_qty_for_symbol(self.broker, symbol)
                if net_retry is not None and lots_fulfilled(net_retry, ato_qty, lot_size):
                    return "BOOK_FILLED"
                self.log.warning("%s ATO buy attempt %d failed: %s", tag, attempt, exc)

        halt_side(self.state, tag, reason="order_retry_exhausted")
        error_text = str(last_exc) if last_exc else f"book qty mismatch for {symbol}"
        error_lower = error_text.lower()
        self.events.publish(
            Event.MODULE_ERROR,
            {
                "module": self.name,
                "scenario": (
                    "margin_shortfall"
                    if "margin" in error_lower or "insufficient" in error_lower
                    else "order_rejection"
                ),
                "severity": "major",
                "category": (
                    "margin"
                    if "margin" in error_lower or "insufficient" in error_lower
                    else "order"
                ),
                "title": f"{tag} ATO protection order failed after retries",
                "error_message": error_text,
                "side": tag,
                "next_action": "Review broker order book; resume side after fix or Batman Complete.",
            },
        )
        return None

    def _side_settings(self, side: str, sell_strike: int) -> dict[str, Any]:
        legacy_retrace = normalize_buffer_field(self.state.get("ato.retrace_points", 5))
        entry_buffer = normalize_buffer_field(
            self.state.get(f"ato.{side.lower()}_entry_buffer_points", 0)
        )
        retrace_points = normalize_buffer_field(
            self.state.get(f"ato.{side.lower()}_retrace_points", legacy_retrace)
        )
        strike = Decimal(sell_strike)
        if side == "CE":
            trigger_level = strike + entry_buffer
            exit_level = strike - retrace_points
            # Negative entry can place exit above trigger → enter-then-immediate-exit risk.
            if exit_level >= trigger_level:
                self.log.warning(
                    "ATO hysteresis warn CE: sell=%s entry_buf=%s exit_buf=%s "
                    "→ trigger=%s exit=%s (exit ≥ trigger; may whipsaw)",
                    sell_strike,
                    entry_buffer,
                    retrace_points,
                    trigger_level,
                    exit_level,
                )
        else:
            trigger_level = strike - entry_buffer
            exit_level = strike + retrace_points
            if exit_level <= trigger_level:
                self.log.warning(
                    "ATO hysteresis warn PE: sell=%s entry_buf=%s exit_buf=%s "
                    "→ trigger=%s exit=%s (exit ≤ trigger; may whipsaw)",
                    sell_strike,
                    entry_buffer,
                    retrace_points,
                    trigger_level,
                    exit_level,
                )
        return {
            "entry_buffer": entry_buffer,
            "retrace_points": retrace_points,
            "trigger_level": trigger_level,
            "exit_level": exit_level,
        }

    def _update_reentry_clearance(
        self, side: str, spot: float, settings: dict[str, Any] | None
    ) -> None:
        """Arm re-entry only after spot leaves the entry/breach zone.

        Prevents enter→exit→enter loops when exit sits inside the entry band
        (e.g. PE entry=-10 / exit=-5 → trigger 24160, exit 24145).
        """
        if settings is None:
            return
        key = f"ato.{side.lower()}_awaiting_clearance"
        if not self.state.get(key, False):
            return
        trigger = float(settings["trigger_level"])
        cleared = (spot > trigger) if side == "PE" else (spot < trigger)
        if not cleared:
            return
        self.state.set(key, False)
        self.log.info(
            "%s ATO clearance — spot %s left trigger %s; re-entry armed",
            side,
            spot,
            settings["trigger_level"],
        )

    def _mark_awaiting_clearance_after_exit(
        self, side: str, spot: float, settings: dict[str, Any]
    ) -> None:
        """After exit, block re-entry while spot is still in the breach zone."""
        trigger = float(settings["trigger_level"])
        still_in_zone = (spot <= trigger) if side == "PE" else (spot >= trigger)
        key = f"ato.{side.lower()}_awaiting_clearance"
        self.state.set(key, still_in_zone)
        if still_in_zone:
            self.log.warning(
                "%s ATO exit while still in breach zone (spot=%s trigger=%s) — "
                "blocking re-entry until spot clears trigger",
                side,
                spot,
                settings["trigger_level"],
            )

    def _append_telemetry_row(
        self,
        *,
        side: str,
        action: str,
        trigger_reason: str,
        spot: float,
        sell_strike: int,
        trigger_level_used: int,
        protect_strike: int,
        protect_symbol: str,
        order_id: str,
        qty: int,
        option_premium: float | None = None,
    ) -> None:
        if option_premium is None:
            option_premium = self._resolve_option_premium(
                protect_symbol, order_id, spot=float(spot)
            )
        row = {
            "timestamp_ist": utils.now_ist().strftime("%Y-%m-%d %H:%M:%S IST"),
            "deployment_file": pathlib.Path(str(self.state.get("deployment.file", ""))).name,
            "side": side,
            "action": action,
            "trigger_reason": trigger_reason,
            "nifty_ltp_at_execution": f"{spot:.2f}",
            "option_premium": _fmt_premium(option_premium),
            "sell_strike": sell_strike,
            "trigger_level_used": trigger_level_used,
            "protect_strike": protect_strike,
            "protect_symbol": protect_symbol,
            "order_id": order_id,
            "qty": qty,
            "poll_interval_seconds_used": self._effective_poll_interval(self.config.get("ato", {})),
        }
        try:
            _TELEMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
            file_exists = _TELEMETRY_FILE.exists()
            if file_exists:
                _migrate_csv_headers(_TELEMETRY_FILE, _TELEMETRY_HEADERS)

            serialized = _serialize_csv_row(row, _TELEMETRY_HEADERS)
            if file_exists and _last_non_empty_line(_TELEMETRY_FILE) == serialized:
                self.log.debug("ATO telemetry dedup: skipping duplicate row")
                return

            with _CSV_IO_LOCK:
                with open(_TELEMETRY_FILE, "a", encoding="utf-8", newline="") as fh:
                    writer = csv.DictWriter(fh, fieldnames=_TELEMETRY_HEADERS)
                    if not file_exists:
                        writer.writeheader()
                    writer.writerow(row)
        except Exception as exc:
            self.log.warning("ATO telemetry append soft-failed: %s", exc)

    def _fill_price_from_order(self, order_id: str | None) -> float | None:
        if not order_id or order_id == "BOOK_FILLED":
            return None
        orders = getattr(self.broker, "_orders", None)
        if isinstance(orders, list):
            for o in orders:
                if str(o.get("order_id")) != str(order_id):
                    continue
                for key in ("avg_price", "avgPrice", "price", "tradedPrice"):
                    raw = o.get(key)
                    if raw is None or raw == "":
                        continue
                    try:
                        value = float(raw)
                    except (TypeError, ValueError):
                        continue
                    if value > 0:
                        return value
        get_book = getattr(self.broker, "get_orderbook", None)
        if not callable(get_book):
            return None
        try:
            book = get_book()
        except Exception:
            return None
        if book is None:
            return None
        try:
            rows = book.to_dict("records") if hasattr(book, "to_dict") else list(book)
        except Exception:
            return None
        for row in rows:
            rid = row.get("order_id") or row.get("orderId")
            if str(rid) != str(order_id):
                continue
            for key in ("avg_price", "avgPrice", "averagePrice", "price"):
                raw = row.get(key)
                if raw is None or raw == "":
                    continue
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    return value
        return None

    def _resolve_option_premium(
        self, symbol: str | None, order_id: str | None = None, *, spot: float | None = None
    ) -> float | None:
        """Live/UAT option premium: prefer order fill, else market quote LTP.

        In UAT, if both fail, use a reporting-only fallback so SARANSH Buy/Sell
        columns are never blank (does not change order placement).
        """
        fill = self._fill_price_from_order(order_id)
        if fill is not None:
            return fill
        if not symbol:
            return None
        strike, opt = _parse_protect_strike_opt(symbol)
        if not strike or not opt:
            return None
        getter = getattr(self.broker, "get_nifty_option_ltps", None)
        if callable(getter):
            try:
                expiry = None
                try:
                    from core.nifty_option_expiry import fixture_expiry_date
                    from core.uat_positions import load_positions_fixture

                    expiry = fixture_expiry_date(load_positions_fixture(_ROOT))
                except Exception:
                    expiry = None
                prices = getter([(strike, opt)], expiry_date=expiry)
                raw = prices.get((strike, opt)) if isinstance(prices, dict) else None
                if raw is not None:
                    value = float(raw)
                    if value > 0:
                        return value
            except Exception as exc:
                self.log.debug("Option premium quote failed for %s: %s", symbol, exc)

        # UAT shadow: never leave SARANSH Buy/Sell empty when quotes are unavailable.
        try:
            from core.batman_mode import is_uat

            if is_uat(_ROOT):
                from backtest_engine.shadow.order_ledger import _uat_fallback_premium

                px = float(spot) if spot and spot > 0 else None
                if px is None:
                    get_spot = getattr(self.broker, "get_nifty_ltp", None)
                    if callable(get_spot):
                        try:
                            px = float(get_spot())
                        except Exception:
                            px = None
                estimated = _uat_fallback_premium(symbol, spot=px)
                self.log.warning(
                    "ATO premium unresolved for %s — UAT fallback %.2f for SARANSH",
                    symbol,
                    estimated,
                )
                return estimated
        except Exception as exc:
            self.log.debug("UAT premium fallback failed: %s", exc)
        return None

    def _ensure_ledger_state(self) -> None:
        if not hasattr(self, "_open_ato_entries"):
            self._open_ato_entries: dict[str, dict[str, Any] | None] = {"CE": None, "PE": None}

    def _remember_entry(
        self,
        *,
        side: str,
        spot: float,
        order_id: str,
        qty: int,
        sell_strike: int,
        trigger_level: int,
        protect_strike: int,
        protect_symbol: str,
        entry_buffer: int,
        retrace_points: int,
        entry_source: str,
    ) -> None:
        self._ensure_ledger_state()
        buy_ts = utils.now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
        buy_premium = self._resolve_option_premium(
            protect_symbol, order_id, spot=float(spot)
        )
        self._open_ato_entries[side] = {
            "buy_timestamp_ist": buy_ts,
            "buy_order_id": order_id,
            "buy_nifty_ltp": float(spot),
            "buy_option_premium": buy_premium,
            "qty": int(qty),
            "sell_strike": int(sell_strike),
            "entry_trigger_level": int(trigger_level),
            "protect_strike": int(protect_strike),
            "protect_symbol": str(protect_symbol),
            "entry_buffer_points": int(entry_buffer),
            "retrace_points": int(retrace_points),
            "entry_source": entry_source,
        }
        prefix = side.lower()
        self.state.set(f"ato.{prefix}_entry_option_premium", buy_premium, save=False)
        lot_size = int(self.config.get("strategy.lot_size", 65))
        lots = float(qty) / float(lot_size) if lot_size > 0 else 0.0
        try:
            record_ato_buy(
                side=side,
                sell_strike=int(sell_strike),
                buy_nifty_ltp=float(spot),
                lots=round(lots, 2),
                timestamp_ist=buy_ts,
                deployment_file=pathlib.Path(str(self.state.get("deployment.file", ""))).name,
                root=_ROOT,
                buy_option_premium=buy_premium,
                protect_strike=int(protect_strike),
            )
        except Exception as exc:
            self.log.warning("ATO cycle feed buy soft-failed: %s", exc)

    def _append_trade_ledger_row(self, row: dict[str, Any]) -> None:
        try:
            _ATO_LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
            file_exists = _ATO_LEDGER_FILE.exists()
            if file_exists:
                _migrate_csv_headers(_ATO_LEDGER_FILE, _ATO_LEDGER_HEADERS)

            serialized = _serialize_csv_row(row, _ATO_LEDGER_HEADERS)
            if file_exists and _last_non_empty_line(_ATO_LEDGER_FILE) == serialized:
                self.log.debug("ATO consolidated ledger dedup: skipping duplicate row")
                return

            with _CSV_IO_LOCK:
                with open(_ATO_LEDGER_FILE, "a", encoding="utf-8", newline="") as fh:
                    writer = csv.DictWriter(fh, fieldnames=_ATO_LEDGER_HEADERS)
                    if not file_exists:
                        writer.writeheader()
                    writer.writerow(row)
        except Exception as exc:
            self.log.warning("ATO consolidated ledger append soft-failed: %s", exc)

    def _write_ledger_snapshot_copy(self) -> None:
        """Write lock-safe snapshot copies so users can open reports while algo runs."""
        if not _ATO_LEDGER_FILE.exists():
            return

        ts = utils.now_ist().strftime("%Y%m%d_%H%M%S")
        _ATO_LEDGER_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        csv_snapshot = _ATO_LEDGER_SNAPSHOT_DIR / f"ato_trade_ledger_snapshot_{ts}.csv"

        try:
            shutil.copy2(_ATO_LEDGER_FILE, csv_snapshot)
        except Exception as exc:
            self.log.warning("ATO snapshot CSV copy soft-failed: %s", exc)
            return

        xlsx_snapshot = _ATO_LEDGER_SNAPSHOT_DIR / f"ato_trade_ledger_snapshot_{ts}.xlsx"
        try:
            import pandas as pd

            ledger_df = pd.read_csv(_ATO_LEDGER_FILE)
            with pd.ExcelWriter(xlsx_snapshot, engine="openpyxl") as writer:
                ledger_df.to_excel(writer, sheet_name="Ledger", index=False)
                if not ledger_df.empty and "date_ist" in ledger_df.columns:
                    agg: dict[str, Any] = {
                        "cycles": ("side", "count"),
                        "points_lost": ("points_lost", "sum"),
                        "points_lost_x_lots": ("points_lost_x_lots", "sum"),
                    }
                    if "premium_pnl" in ledger_df.columns:
                        agg["premium_pnl"] = ("premium_pnl", "sum")
                    if "premium_pnl_rupees" in ledger_df.columns:
                        agg["premium_pnl_rupees"] = ("premium_pnl_rupees", "sum")
                    daily = (
                        ledger_df.groupby("date_ist", as_index=False)
                        .agg(**{k: v for k, v in agg.items()})
                        .sort_values("date_ist")
                    )
                    daily.to_excel(writer, sheet_name="DailySummary", index=False)
        except Exception as exc:
            self.log.warning("ATO snapshot XLSX export soft-failed: %s", exc)

    def _record_trade_cycle(
        self,
        *,
        side: str,
        spot: float,
        order_id: str,
        sell_strike: int,
        settings: dict[str, int],
        protect_symbol: str,
        protect_strike: int,
        qty: int,
    ) -> None:
        self._ensure_ledger_state()
        entry = self._open_ato_entries.get(side)

        entry_spot = float(entry.get("buy_nifty_ltp", spot)) if entry else float(spot)
        if side == "CE":
            points_lost = max(0.0, entry_spot - float(spot))
        else:
            points_lost = max(0.0, float(spot) - entry_spot)

        lot_size = int(self.config.get("strategy.lot_size", 65))
        lots = float(qty) / float(lot_size) if lot_size > 0 else 0.0

        buy_premium = None
        if entry and entry.get("buy_option_premium") is not None:
            try:
                buy_premium = float(entry["buy_option_premium"])
            except (TypeError, ValueError):
                buy_premium = None
        if buy_premium is None:
            stored = self.state.get(f"ato.{side.lower()}_entry_option_premium")
            if stored is not None and stored != "":
                try:
                    buy_premium = float(stored)
                except (TypeError, ValueError):
                    buy_premium = None
        if buy_premium is None and entry:
            buy_premium = self._resolve_option_premium(
                str(entry.get("protect_symbol") or protect_symbol),
                str(entry.get("buy_order_id") or ""),
                spot=float(entry.get("buy_nifty_ltp") or spot),
            )

        sell_premium = self._resolve_option_premium(
            protect_symbol, order_id, spot=float(spot)
        )
        premium_pnl = None
        premium_pnl_rupees = None
        if buy_premium is not None and sell_premium is not None:
            # Long protect: BUY then SELL → premium P&L = exit − entry.
            premium_pnl = float(sell_premium) - float(buy_premium)
            premium_pnl_rupees = premium_pnl * float(qty)

        row = {
            "date_ist": utils.now_ist().strftime("%Y-%m-%d"),
            "timestamp_ist": utils.now_ist().strftime("%Y-%m-%d %H:%M:%S IST"),
            "deployment_file": pathlib.Path(str(self.state.get("deployment.file", ""))).name,
            "side": side,
            "cycle_index": (
                getattr(self, "_ce_cycles", 0) if side == "CE" else getattr(self, "_pe_cycles", 0)
            ),
            "entry_source": (entry or {}).get("entry_source", "unknown"),
            "buy_timestamp_ist": (entry or {}).get("buy_timestamp_ist", ""),
            "buy_order_id": (entry or {}).get("buy_order_id", ""),
            "buy_nifty_ltp": f"{entry_spot:.2f}",
            "buy_option_premium": _fmt_premium(buy_premium),
            "sell_timestamp_ist": utils.now_ist().strftime("%Y-%m-%d %H:%M:%S IST"),
            "sell_order_id": order_id,
            "sell_nifty_ltp": f"{spot:.2f}",
            "sell_option_premium": _fmt_premium(sell_premium),
            "sell_strike": int(sell_strike),
            "entry_trigger_level": int(
                (entry or {}).get("entry_trigger_level", settings["trigger_level"])
            ),
            "exit_trigger_level": int(settings["exit_level"]),
            "entry_buffer_points": int(
                (entry or {}).get("entry_buffer_points", settings["entry_buffer"])
            ),
            "retrace_points": int((entry or {}).get("retrace_points", settings["retrace_points"])),
            "protect_strike": int((entry or {}).get("protect_strike", protect_strike)),
            "protect_symbol": (entry or {}).get("protect_symbol", protect_symbol),
            "qty": int(qty),
            "lots": f"{lots:.2f}",
            "points_lost": f"{points_lost:.2f}",
            "points_lost_x_lots": f"{points_lost * lots:.2f}",
            "premium_pnl": _fmt_premium(premium_pnl),
            "premium_pnl_rupees": _fmt_premium(premium_pnl_rupees),
            "poll_interval_seconds_used": self._effective_poll_interval(self.config.get("ato", {})),
        }
        self._append_trade_ledger_row(row)
        self._write_ledger_snapshot_copy()
        try:
            record_ato_cycle_complete(
                side=side,
                sell_strike=int(sell_strike),
                buy_nifty_ltp=entry_spot,
                sell_nifty_ltp=float(spot),
                lots=round(lots, 2),
                timestamp_ist=row["sell_timestamp_ist"],
                deployment_file=row["deployment_file"],
                root=_ROOT,
                buy_option_premium=buy_premium,
                sell_option_premium=sell_premium,
                premium_pnl=premium_pnl,
                premium_pnl_rupees=premium_pnl_rupees,
                protect_strike=int((entry or {}).get("protect_strike", protect_strike)),
            )
        except Exception as exc:
            self.log.warning("ATO cycle feed complete soft-failed: %s", exc)
        self.state.set(f"ato.{side.lower()}_entry_option_premium", None, save=False)
        self._open_ato_entries[side] = None

    # ── Deployment file restore (P3) ─────────────────────────────────────────

    def _load_deployment_file(self) -> dict | None:
        """Find and load the most recent batman_*.json from mode deployments dir.

        Populates state with positions + ATO config so the module can resume
        as if /register had just been successfully completed.
        Returns the parsed deployment dict, or None if no file found.
        """
        deploy_root = deployments_dir()
        pattern = str(deploy_root / "batman_*.json")
        files = sorted(glob.glob(pattern))
        if not files:
            self.log.info("ATO restore: no deployment file found in %s/", deploy_root)
            return None

        latest = files[-1]
        try:
            with open(latest, encoding="utf-8") as f:
                dep = json.load(f)
        except Exception as exc:
            self.log.error("ATO restore: failed to read %s — %s", latest, exc)
            return None

        positions = dep.get("positions", {})
        ato = dep.get("ato", {})

        # Load registered leg positions into state
        for role, leg in positions.items():
            if leg:
                self.state.set(f"positions.{role}", leg)

        # Load ATO config into state
        if ato.get("ce_protect_symbol"):
            self.state.set("ato.ce_protect_symbol", ato["ce_protect_symbol"])
            self.state.set("ato.ce_protect_strike", ato["ce_protect_strike"])
        if ato.get("pe_protect_symbol"):
            self.state.set("ato.pe_protect_symbol", ato["pe_protect_symbol"])
            self.state.set("ato.pe_protect_strike", ato["pe_protect_strike"])
        if dep.get("retrace_points") is not None:
            self.state.set("ato.retrace_points", dep["retrace_points"])
        self.state.set("ato.manage_sides", dep.get("ato_manage_sides", "both"))
        self.state.set(
            "ato.ce_entry_buffer_points",
            normalize_buffer_field(
                ato.get("ce_entry_buffer", ato.get("ce_entry_buffer_points", 0))
            ),
        )
        self.state.set(
            "ato.pe_entry_buffer_points",
            normalize_buffer_field(
                ato.get("pe_entry_buffer", ato.get("pe_entry_buffer_points", 0))
            ),
        )
        self.state.set(
            "ato.ce_retrace_points",
            normalize_buffer_field(
                ato.get(
                    "ce_retrace_buffer", ato.get("ce_retrace_points", dep.get("retrace_points", 5))
                )
            ),
        )
        self.state.set(
            "ato.pe_retrace_points",
            normalize_buffer_field(
                ato.get(
                    "pe_retrace_buffer", ato.get("pe_retrace_points", dep.get("retrace_points", 5))
                )
            ),
        )
        self.state.set("ato.poll_interval_seconds", ato.get("poll_interval_seconds"))

        self.state.set("deployment.confirmed", True)
        self.state.set("deployment.file", latest)
        self.log.info("ATO restore: loaded deployment from %s", latest)
        return cast(dict[str, Any], dep)

    def _validate_broker_positions(
        self, dep: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Compare deployment file positions against live broker positions.

        Returns:
            confirmed — list of leg dicts that are confirmed open at broker
            missing   — list of leg dicts that are NOT found at broker
        """
        try:
            broker_df = self.broker.get_positions()
        except Exception as exc:
            self.log.error("ATO restore: broker position fetch failed — %s", exc)
            missing_legs = list(cast(dict[str, Any], dep.get("positions", {})).values())
            return [], cast(list[dict[str, Any]], missing_legs)

        broker_symbols: set[str] = set()
        if broker_df is not None and not broker_df.empty:
            for _, row in broker_df.iterrows():
                sym = row.get("tradingSymbol") or row.get("tradingsymbol", "")
                if sym:
                    broker_symbols.add(sym)

        confirmed: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        for role, leg in dep.get("positions", {}).items():
            if not leg:
                continue
            sym = leg.get("symbol", "")
            entry = {"role": role, **leg}
            (confirmed if sym in broker_symbols else missing).append(entry)
        return confirmed, missing

    def _check_managed_qty_mismatch(self) -> None:
        """Halt CE/PE independently when broker qty is below managed Batman legs."""
        if not self.state.get("deployment.confirmed", False):
            return
        try:
            broker_df = self.broker.get_positions()
        except Exception as exc:
            self.log.warning("Managed qty check skipped — broker error: %s", exc)
            return

        sym_qty: dict[str, int] = {}
        if broker_df is not None and not broker_df.empty:
            for _, row in broker_df.iterrows():
                sym = row.get("tradingSymbol") or row.get("tradingsymbol", "")
                if sym:
                    sym_qty[sym] = abs(int(row.get("netQty", 0) or 0))

        for side in ("CE", "PE"):
            prefix = side.lower()
            if getattr(self, f"_{prefix}_qty_mismatch_halted", False):
                continue
            if is_side_halted(self.state, side):
                continue
            mismatches: list[str] = []
            for role in _SIDE_BATMAN_ROLES[side]:
                leg = self.state.get(f"positions.{role}")
                if not leg:
                    continue
                leg_d = cast(dict[str, Any], leg)
                sym = str(leg_d.get("symbol", ""))
                managed = abs(int(leg_d.get("qty", 0)))
                broker_qty = sym_qty.get(sym, 0)
                if broker_qty < managed:
                    mismatches.append(f"{sym}: broker={broker_qty} managed={managed}")

            if not mismatches:
                continue

            self.log.error("%s managed qty mismatch — halting side: %s", side, mismatches)
            halt_side(self.state, side, reason="batman_qty_drift")
            setattr(self, f"_{prefix}_qty_mismatch_halted", True)
            self.events.publish(
                Event.DEPLOYMENT_RESTORE_MISMATCH,
                {
                    "reason": "managed_qty_mismatch",
                    "side": side,
                    "details": mismatches,
                    "next_action": "Batman Complete → re-register after fixing broker positions.",
                },
            )

    # ── Startup scan ─────────────────────────────────────────────────────────

    def _startup_scan(self) -> None:
        """Run ONCE at module start, before the main monitoring loop.

        Handles the pre-algo gap scenario (typically the 09:15–09:20 window)
        where the user may have manually BUY'd the ATO leg before the algo
        started.

        Two outcomes per side when the range is breached at startup:
          1. Manual ATO already placed at broker → *adopt* it: set state flags,
             do NOT place a new order, let normal retracement logic take over.
          2. Range is breached but no position exists at broker → *auto-place*
             ATO via the normal _place_ce/pe_protection() path.

        Also cleans stale ATO state flags that may have survived from a prior
        session (e.g. the process crashed after an ATO entry but before the
        retrace exit completed).

        Config keys (settings.json → ato):
          startup_scan_enabled   – set to false to skip entirely (default: true)
          pre_algo_window_start  – informational only; logged for audit trail
          pre_algo_window_end    – informational only
        """
        cfg_ato = self.config.get("ato", {})
        if not cfg_ato.get("startup_scan_enabled", True):
            self.log.info("ATO startup scan disabled via config — skipping")
            return

        ce_sell = self.state.get("positions.ce_sell")
        pe_sell = self.state.get("positions.pe_sell")
        if not ce_sell and not pe_sell:
            self.log.info("ATO startup scan: no registered sell legs in state — skipping")
            return

        ce_strike = int(cast(dict[str, Any], ce_sell).get("strike", 0)) if ce_sell else 0
        pe_strike = int(cast(dict[str, Any], pe_sell).get("strike", 0)) if pe_sell else 0
        ce_protect_symbol = self.state.get("ato.ce_protect_symbol")
        pe_protect_symbol = self.state.get("ato.pe_protect_symbol")

        try:
            spot = float(self._resolve_nifty_spot())
        except Exception as exc:
            self.log.error(
                "ATO startup scan: NIFTY LTP fetch failed (%s) — "
                "skipping scan; normal monitoring will proceed",
                exc,
            )
            return

        expected_ce_qty = self._ato_qty("ce_buy") if ce_sell else 0
        expected_pe_qty = self._ato_qty("pe_buy") if pe_sell else 0
        window_start = cfg_ato.get("pre_algo_window_start", "09:15")
        window_end = cfg_ato.get("pre_algo_window_end", "09:20")

        self.log.info(
            "ATO startup scan — spot=%.1f | CE_sell=%d | PE_sell=%d | "
            "expected_ato_qty=%d | pre-algo window=%s–%s",
            spot,
            ce_strike,
            pe_strike,
            expected_ce_qty,
            window_start,
            window_end,
        )

        # ── Step 1: Stale-state cleanup ──────────────────────────────────────
        # If state flags say ATO is active but the broker shows no open position,
        # the flag survived a crash or incomplete retrace exit — reset it so the
        # breach detection below can evaluate cleanly.
        ce_triggered = self.state.get("ato.ce_triggered", False)
        pe_triggered = self.state.get("ato.pe_triggered", False)

        if ce_triggered and ce_protect_symbol:
            if self._position_qty(ce_protect_symbol) == 0:
                self.log.warning(
                    "ATO startup scan: CE triggered=True in state but no broker "
                    "position found for %s — resetting stale flag",
                    ce_protect_symbol,
                )
                self.state.set("ato.ce_triggered", False)
                self.state.set("ato.ce_ato_active", False)
                ce_triggered = False

        if pe_triggered and pe_protect_symbol:
            if self._position_qty(pe_protect_symbol) == 0:
                self.log.warning(
                    "ATO startup scan: PE triggered=True in state but no broker "
                    "position found for %s — resetting stale flag",
                    pe_protect_symbol,
                )
                self.state.set("ato.pe_triggered", False)
                self.state.set("ato.pe_ato_active", False)
                pe_triggered = False

        # ── Step 2: Breach detection → adopt manual ATO or auto-place ────
        manage_sides = self.state.get("ato.manage_sides", "both")
        ce_settings = self._side_settings("CE", ce_strike) if ce_sell else None
        pe_settings = self._side_settings("PE", pe_strike) if pe_sell else None
        if ce_settings is not None:
            self.log.info(
                "ATO levels CE: sell=%d entry_buf=%s retrace=%s → trigger=%s exit=%s",
                ce_strike,
                ce_settings["entry_buffer"],
                ce_settings["retrace_points"],
                ce_settings["trigger_level"],
                ce_settings["exit_level"],
            )
        if pe_settings is not None:
            self.log.info(
                "ATO levels PE: sell=%d entry_buf=%s retrace=%s → trigger=%s exit=%s",
                pe_strike,
                pe_settings["entry_buffer"],
                pe_settings["retrace_points"],
                pe_settings["trigger_level"],
                pe_settings["exit_level"],
            )
        ce_breached = (
            bool(ce_strike)
            and ce_settings is not None
            and spot >= float(ce_settings["trigger_level"])
            and manage_sides in ("ce", "both")
        )
        pe_breached = (
            bool(pe_strike)
            and pe_settings is not None
            and spot <= float(pe_settings["trigger_level"])
            and manage_sides in ("pe", "both")
        )

        if ce_breached and not ce_triggered:
            self.log.warning(
                "ATO startup scan: CE BREACHED — spot=%.1f ≥ CE trigger=%d",
                spot,
                ce_settings["trigger_level"],
            )
            broker_ce_qty = self._position_qty(ce_protect_symbol) if ce_protect_symbol else 0
            if broker_ce_qty > 0:
                # Always recover registered protect inventory (algo fill or operator).
                self._adopt_manual_ato(
                    "CE", ce_protect_symbol, broker_ce_qty, expected_ce_qty, spot
                )
            else:
                self.log.warning(
                    "ATO startup scan: No CE ATO found at broker — "
                    "auto-placing CE protection"
                )
                self._place_ce_protection(ce_strike, spot, ce_settings)

        if pe_breached and not pe_triggered:
            if self.state.get("ato.pe_awaiting_clearance", False):
                self.log.info(
                    "ATO startup scan: PE breached but awaiting clearance — skip auto-place"
                )
            else:
                self.log.warning(
                    "ATO startup scan: PE BREACHED — spot=%.1f ≤ PE trigger=%d",
                    spot,
                    pe_settings["trigger_level"],
                )
                broker_pe_qty = self._position_qty(pe_protect_symbol) if pe_protect_symbol else 0
                if broker_pe_qty > 0:
                    # Always recover registered protect inventory (algo fill or operator).
                    self._adopt_manual_ato(
                        "PE", pe_protect_symbol, broker_pe_qty, expected_pe_qty, spot
                    )
                else:
                    self.log.warning(
                        "ATO startup scan: No PE ATO found at broker — "
                        "auto-placing PE protection"
                    )
                    self._place_pe_protection(pe_strike, spot, pe_settings)

        # ── Step 3: Publish summary event ─────────────────────────────────────
        self.events.publish(
            Event.ATO_STARTUP_SCAN_DONE,
            {
                "spot": spot,
                "ce_strike": ce_strike,
                "pe_strike": pe_strike,
                "ce_breached": ce_breached,
                "pe_breached": pe_breached,
                "ce_ato_active": self.state.get("ato.ce_ato_active", False),
                "pe_ato_active": self.state.get("ato.pe_ato_active", False),
            },
        )
        self.log.info(
            "ATO startup scan complete — CE_breached=%s PE_breached=%s | "
            "CE_active=%s PE_active=%s",
            ce_breached,
            pe_breached,
            self.state.get("ato.ce_ato_active", False),
            self.state.get("ato.pe_ato_active", False),
        )

    def _adopt_manual_ato(
        self,
        side: str,
        symbol: str,
        broker_qty: int,
        expected_qty: int,
        spot: float,
    ) -> None:
        """Adopt a manually-placed ATO position found at the broker on startup.

        Sets triggered/active state flags WITHOUT placing a new order. This
        hands the position over to the normal retracement exit logic.

        If broker_qty doesn't match expected_qty a prominent warning is logged
        and ATO_STARTUP_QTY_MISMATCH is published for Telegram alerting, but
        the position is still adopted — never place a duplicate order on top of
        an existing one, regardless of qty.
        """
        qty_match = broker_qty == expected_qty
        self.log.info(
            "ATO startup scan: adopting manual %s ATO — symbol=%s "
            "broker_qty=%d expected_qty=%d %s",
            side,
            symbol,
            broker_qty,
            expected_qty,
            "(qty ✅)" if qty_match else "(⚠ qty mismatch)",
        )

        if side == "CE":
            self.state.set("ato.ce_triggered", True)
            self.state.set("ato.ce_ato_active", True)
            self._set_registered_exit_qty("CE", expected_qty)
            self._ce_cycles = getattr(self, "_ce_cycles", 0) + 1
            protect_strike = self.state.get("ato.ce_protect_strike")
            self.events.publish(
                Event.ATO_CE_TRIGGERED,
                {
                    "symbol": symbol,
                    "qty": broker_qty,
                    "spot": spot,
                    "order_id": "MANUAL_PRE_ALGO",
                    "ato_strike": protect_strike,
                    "adopted": True,
                },
            )
        else:  # PE
            self.state.set("ato.pe_triggered", True)
            self.state.set("ato.pe_ato_active", True)
            self._set_registered_exit_qty("PE", expected_qty)
            self._pe_cycles = getattr(self, "_pe_cycles", 0) + 1
            protect_strike = self.state.get("ato.pe_protect_strike")
            self.events.publish(
                Event.ATO_PE_TRIGGERED,
                {
                    "symbol": symbol,
                    "qty": broker_qty,
                    "spot": spot,
                    "order_id": "MANUAL_PRE_ALGO",
                    "ato_strike": protect_strike,
                    "adopted": True,
                },
            )

        sell_leg = self.state.get(
            "positions.ce_sell" if side == "CE" else "positions.pe_sell", {"strike": 0}
        )
        sell_strike = int(cast(dict[str, Any], sell_leg).get("strike", 0) or 0)
        settings = (
            self._side_settings(side, sell_strike)
            if sell_strike
            else {
                "entry_buffer": 0,
                "retrace_points": int(self.state.get("ato.retrace_points", 5)),
                "trigger_level": sell_strike,
                "exit_level": sell_strike,
            }
        )
        self._remember_entry(
            side=side,
            spot=spot,
            order_id="MANUAL_PRE_ALGO",
            qty=broker_qty,
            sell_strike=sell_strike,
            trigger_level=int(settings["trigger_level"]),
            protect_strike=int(protect_strike or 0),
            protect_symbol=symbol,
            entry_buffer=int(settings["entry_buffer"]),
            retrace_points=int(settings["retrace_points"]),
            entry_source="manual_adopted_startup",
        )

        if not qty_match:
            self.log.warning(
                "⚠ ATO QTY MISMATCH on %s side — broker=%d, expected=%d. "
                "ATO adopted but retracement exit will use expected qty (%d). "
                "Please verify position at broker manually.",
                side,
                broker_qty,
                expected_qty,
                expected_qty,
            )
            self.events.publish(
                Event.ATO_STARTUP_QTY_MISMATCH,
                {
                    "side": side,
                    "symbol": symbol,
                    "broker_qty": broker_qty,
                    "expected_qty": expected_qty,
                    "spot": spot,
                },
            )

    def _load_broker_positions_df(self) -> Any:
        """Return broker positions dataframe (legacy helper)."""
        try:
            return self.broker.get_positions()
        except Exception as exc:
            self.log.warning("Broker position book unreadable: %s", exc)
            return None

    def _read_symbol_qty_with_retry(self) -> tuple[dict[str, int] | None, bool]:
        """Q62 — retry position book read; return qty map and transient-failure flag."""
        op = self._operator_settings()
        max_retries = int(op.get("order_retry_max", 3))
        return read_positions_with_retry(self.broker, max_retries=max_retries)

    def _handle_unreadable_position_book(self) -> None:
        """Q33/Q62 — pause all ATO when broker book still unreadable after retries."""
        if getattr(self, "_book_unreadable_paused", False):
            return
        self._book_unreadable_paused = True
        pause_all_ato(self.state, reason="position_book_unreadable")
        self.log.error("ATO: position book unreadable after retries — pausing ALL ATO monitoring")
        self.events.publish(
            Event.DEPLOYMENT_RESTORE_MISMATCH,
            {
                "reason": "position_book_unreadable",
                "next_action": "Check Dhan portal and broker API; Resume when book is readable.",
            },
        )
        self.events.publish(
            Event.MODULE_ERROR,
            {
                "module": self.name,
                "scenario": "position_book_unreadable",
                "severity": "critical",
                "category": "positions",
                "title": "ATO position book unreadable",
                "error_message": "get_positions failed after retries during ATO poll",
                "next_action": "Fix broker connectivity; Resume ATO when positions load.",
            },
        )

    def _handle_position_book_recovered(self) -> None:
        """Q62 — transient book failure recovered within retry window."""
        if getattr(self, "_book_recovery_notified", False):
            return
        self._book_recovery_notified = True
        self.log.warning("ATO: position book was unreadable but recovered on retry")
        self.events.publish(
            Event.DEPLOYMENT_RESTORE_MISMATCH,
            {
                "reason": "position_book_recovered",
                "severity": "info",
                "next_action": "Monitoring continues — no operator action required.",
            },
        )

    def _apply_resume_reevaluate_flags(self) -> None:
        """Q55 — clear instance guards after operator /resume."""
        if not self.state.get("ato.resume_reevaluate", False):
            return
        self.state.set("ato.resume_reevaluate", False, save=False)
        for prefix in ("ce", "pe"):
            setattr(self, f"_{prefix}_manual_exit_halted", False)
        self._book_unreadable_paused = False
        self._book_recovery_notified = False

    def _registered_exit_qty(self, side: str, buy_leg_key: str) -> int:
        """Q60 — retrace SELL always uses registered ATO qty, not broker adopt qty."""
        prefix = self._side_prefix(side)
        stored = self.state.get(f"ato.{prefix}_exit_qty")
        if stored is not None:
            return int(stored)
        return self._ato_qty(buy_leg_key)

    def _set_registered_exit_qty(self, side: str, qty: int) -> None:
        prefix = self._side_prefix(side)
        self.state.set(f"ato.{prefix}_exit_qty", int(qty), save=False)

    def _sync_manual_legs_on_poll(self, spot: float, sym_qty: dict[str, int]) -> None:
        """§7 mid-session manual protect sync (26A, 26D, 31). Q50: ignore stray legs."""
        manage_sides = self.state.get("ato.manage_sides", "both")
        ce_sell = self.state.get("positions.ce_sell")
        pe_sell = self.state.get("positions.pe_sell")

        side_specs: list[tuple[str, Any, str, str, str]] = []
        if ce_sell and manage_sides in ("ce", "both"):
            side_specs.append(("CE", ce_sell, "ce_buy", "ato.ce_protect_symbol", "ce"))
        if pe_sell and manage_sides in ("pe", "both"):
            side_specs.append(("PE", pe_sell, "pe_buy", "ato.pe_protect_symbol", "pe"))

        for side, _sell, buy_key, symbol_key, prefix in side_specs:
            if getattr(self, f"_{prefix}_manual_exit_halted", False):
                continue
            if is_side_halted(self.state, side):
                continue

            sell_strike = int(cast(dict[str, Any], _sell).get("strike", 0))
            symbol, _strike = self._resolve_protect_symbol(
                side,
                symbol_key,
                f"ato.{prefix}_protect_strike",
                f"positions.{prefix}_sell",
                sell_strike,
            )
            if not symbol:
                continue

            expected_qty = self._ato_qty(buy_key)
            triggered = bool(self.state.get(f"ato.{prefix}_triggered", False))
            ato_active = bool(self.state.get(f"ato.{prefix}_ato_active", False))
            broker_qty = sym_qty.get(symbol, 0)
            seen_attr = f"_{prefix}_protect_seen_at_broker"
            if broker_qty > 0:
                setattr(self, seen_attr, True)
            protect_seen = bool(getattr(self, seen_attr, False))
            lot_size = int(self._operator_settings().get("lot_size", 65))

            result = evaluate_side_manual_sync(
                side=cast(Literal["CE", "PE"], side),
                protect_symbol=symbol,
                expected_qty=expected_qty,
                triggered=triggered,
                ato_active=ato_active,
                broker_qty=broker_qty,
                side_halted=False,
                protect_seen_at_broker=protect_seen,
                lot_size=lot_size,
                manual_protect_adopt_enabled=self._manual_protect_adopt_enabled(),
            )
            if result is None:
                continue
            self._apply_manual_leg_sync(result, spot)

    def _apply_manual_leg_sync(self, result: ManualLegSyncResult, spot: float) -> None:
        side = result.side
        prefix = self._side_prefix(side)

        if result.action == "adopt_idle":
            if not self._manual_protect_adopt_enabled():
                self.log.warning(
                    "%s manual protect adopt skipped (disabled) — %s broker_qty=%d",
                    side,
                    result.symbol,
                    result.broker_qty,
                )
                return
            self.log.warning(
                "%s manual protect adopted mid-session — %s broker_qty=%d expected=%d",
                side,
                result.symbol,
                result.broker_qty,
                result.expected_qty,
            )
            self._adopt_manual_ato(
                side,
                result.symbol,
                result.broker_qty,
                result.expected_qty,
                spot,
            )
            self.events.publish(
                Event.DEPLOYMENT_RESTORE_MISMATCH,
                {
                    "reason": "manual_protect_adopted",
                    "side": side,
                    "symbol": result.symbol,
                    "broker_qty": result.broker_qty,
                    "expected_qty": result.expected_qty,
                    "next_action": "Exit-only on retrace — no second BUY on this side.",
                },
            )
            return

        if result.action in ("pause_full_exit", "pause_partial_exit"):
            setattr(self, f"_{prefix}_manual_exit_halted", True)
            reason = (
                "manual_protect_full_exit"
                if result.action == "pause_full_exit"
                else "manual_protect_partial_exit"
            )
            self.log.error(
                "%s manual protect intervention — halting side (%s) %s broker=%d expected=%d",
                side,
                reason,
                result.symbol,
                result.broker_qty,
                result.expected_qty,
            )
            halt_side(self.state, side, reason=reason)
            self.events.publish(
                Event.DEPLOYMENT_RESTORE_MISMATCH,
                {
                    "reason": reason,
                    "side": side,
                    "symbol": result.symbol,
                    "broker_qty": result.broker_qty,
                    "expected_qty": result.expected_qty,
                    "next_action": "Resume side after fixing broker book, or Batman Complete.",
                },
            )

    # ── Per-tick breach check ─────────────────────────────────────────────────

    def _resolve_protect_symbol(
        self,
        side: str,
        symbol_key: str,
        strike_key: str,
        sell_leg_key: str,
        sell_strike: int,
    ) -> tuple[str | None, int]:
        """Return protect symbol/strike from state, deriving from sell leg if missing."""
        strike_offset = int(self.config.get("ato.strike_offset", 50))
        if side == "CE":
            default_strike = sell_strike + strike_offset
        else:
            default_strike = sell_strike - strike_offset
        protect_strike = int(self.state.get(strike_key, default_strike) or default_strike)
        symbol = self.state.get(symbol_key)
        if symbol:
            return str(symbol), protect_strike

        sell_leg = self.state.get(sell_leg_key)
        if not sell_leg:
            return None, protect_strike

        sell_symbol = cast(dict[str, Any], sell_leg).get("symbol")
        if not sell_symbol:
            return None, protect_strike

        derived = build_ato_protect_symbol(str(sell_symbol), protect_strike, side)
        self.state.set(symbol_key, derived, save=False)
        self.state.set(strike_key, protect_strike, save=False)
        self.log.info("ATO: derived %s protect symbol %s from %s", side, derived, sell_leg_key)
        return derived, protect_strike

    def _check_breach(self) -> None:
        """Compare NIFTY spot with sell strikes; enter or exit ATO protection."""
        if not self.state.get("deployment.confirmed", False):
            return

        ce_sell = self.state.get("positions.ce_sell")
        pe_sell = self.state.get("positions.pe_sell")
        if not ce_sell and not pe_sell:
            return  # no positions deployed yet

        try:
            spot = self._resolve_nifty_spot()
        except Exception as exc:
            self.log.warning("ATO breach check skipped — LTP unavailable: %s", exc)
            self._consecutive_ltp_failures = getattr(self, "_consecutive_ltp_failures", 0) + 1
            self._maybe_alert_ltp_failures(self.config.get("ato", {}))
            return

        self._apply_resume_reevaluate_flags()

        sym_qty, had_book_failure = self._read_symbol_qty_with_retry()
        if sym_qty is None:
            self._handle_unreadable_position_book()
            return
        if had_book_failure:
            self._handle_position_book_recovered()

        self._check_managed_qty_mismatch()

        manage_sides = self.state.get("ato.manage_sides", "both")

        ce_strike = int(cast(dict[str, Any], ce_sell).get("strike", 0)) if ce_sell else 0
        pe_strike = int(cast(dict[str, Any], pe_sell).get("strike", 0)) if pe_sell else 0
        ce_triggered = self.state.get("ato.ce_triggered", False)
        pe_triggered = self.state.get("ato.pe_triggered", False)
        ce_ato_active = self.state.get("ato.ce_ato_active", False)
        pe_ato_active = self.state.get("ato.pe_ato_active", False)
        ce_settings = self._side_settings("CE", ce_strike) if ce_sell else None
        pe_settings = self._side_settings("PE", pe_strike) if pe_sell else None
        self._update_reentry_clearance("CE", float(spot), ce_settings)
        self._update_reentry_clearance("PE", float(spot), pe_settings)

        ce_protect_sym, _ = (
            self._resolve_protect_symbol(
                "CE",
                "ato.ce_protect_symbol",
                "ato.ce_protect_strike",
                "positions.ce_sell",
                ce_strike,
            )
            if ce_sell
            else (None, 0)
        )
        pe_protect_sym, _ = (
            self._resolve_protect_symbol(
                "PE",
                "ato.pe_protect_symbol",
                "ato.pe_protect_strike",
                "positions.pe_sell",
                pe_strike,
            )
            if pe_sell
            else (None, 0)
        )
        ce_book_qty = sym_qty.get(str(ce_protect_sym or ""), 0) if ce_protect_sym else 0
        pe_book_qty = sym_qty.get(str(pe_protect_sym or ""), 0) if pe_protect_sym else 0

        # ── CE side ──────────────────────────────────────────
        if (
            ce_sell
            and manage_sides in ("ce", "both")
            and ce_settings
            and not is_side_halted(self.state, "CE")
        ):
            ce_breach = bool(ce_strike and spot >= ce_settings["trigger_level"])
            # Only a long protect blocks entry (short ledger phantoms must not).
            ce_has_long_protect = ce_book_qty > 0
            if (
                ce_breach
                and not ce_has_long_protect
                and not self.state.get("ato.ce_awaiting_clearance", False)
                and (not ce_triggered or (ce_triggered and not ce_ato_active))
            ):
                trigger_reason = (
                    "buffer_trigger_hit"
                    if ce_settings["entry_buffer"] != 0
                    else "sell_strike_breached"
                )
                label = "Q32C re-entry" if ce_triggered else "breach"
                self.log.warning(
                    "⚠ CE %s — Spot %s ≥ CE trigger %s → entering ATO",
                    label,
                    spot,
                    ce_settings["trigger_level"],
                )
                self._place_ce_protection(ce_strike, float(spot), ce_settings, trigger_reason)
            elif ce_breach and ce_has_long_protect and not ce_ato_active:
                self.log.info(
                    "CE breach skipped — long protect already in book qty=%s (%s)",
                    ce_book_qty,
                    ce_protect_sym,
                )
            elif ce_ato_active and ce_strike and spot <= ce_settings["exit_level"]:
                self.log.info(
                    "↩ CE RETRACE — Spot %s ≤ CE retrace exit %s → exiting ATO",
                    spot,
                    ce_settings["exit_level"],
                )
                self._exit_ce_ato(float(spot), ce_strike, ce_settings)

        # ── PE side ──────────────────────────────────────────
        if (
            pe_sell
            and manage_sides in ("pe", "both")
            and pe_settings
            and not is_side_halted(self.state, "PE")
        ):
            pe_breach = bool(pe_strike and spot <= pe_settings["trigger_level"])
            pe_has_long_protect = pe_book_qty > 0
            if (
                pe_breach
                and not pe_has_long_protect
                and not self.state.get("ato.pe_awaiting_clearance", False)
                and (not pe_triggered or (pe_triggered and not pe_ato_active))
            ):
                trigger_reason = (
                    "buffer_trigger_hit"
                    if pe_settings["entry_buffer"] != 0
                    else "sell_strike_breached"
                )
                label = "Q32C re-entry" if pe_triggered else "breach"
                self.log.warning(
                    "⚠ PE %s — Spot %s ≤ PE trigger %s → entering ATO",
                    label,
                    spot,
                    pe_settings["trigger_level"],
                )
                self._place_pe_protection(pe_strike, float(spot), pe_settings, trigger_reason)
            elif pe_breach and pe_has_long_protect and not pe_ato_active:
                self.log.info(
                    "PE breach skipped — long protect already in book qty=%s (%s)",
                    pe_book_qty,
                    pe_protect_sym,
                )
            elif pe_ato_active and pe_strike and spot >= pe_settings["exit_level"]:
                self.log.info(
                    "↩ PE RETRACE — Spot %s ≥ PE retrace exit %s → exiting ATO",
                    spot,
                    pe_settings["exit_level"],
                )
                self._exit_pe_ato(float(spot), pe_strike, pe_settings)

        # Re-read book after any entry/exit this tick — stale pre-trade qty must not
        # trip manual_protect_full_exit (ato_active + protect_seen + qty 0).
        fresh_qty, _fresh_fail = self._read_symbol_qty_with_retry()
        if fresh_qty is not None:
            sym_qty = fresh_qty

        self._sync_manual_legs_on_poll(float(spot), sym_qty)

    def _ato_qty(self, buy_leg_key: str) -> int:
        """Return ATO qty from the deployed buy leg in state.

        Falls back to buy_lots × lot_size from config if state is not yet
        populated (e.g. during tests that don’t set positions).
        """
        side = "pe" if buy_leg_key.startswith("pe") else "ce"
        scope = self.state.get("deployment.registration_scope") or {}
        ato_lots = scope.get(f"{side}_ato_lots")
        if ato_lots is not None:
            lot_size = int(scope.get("lot_size", self.config.get("strategy.lot_size", 65)))
            return int(ato_lots) * lot_size
        leg = self.state.get(f"positions.{buy_leg_key}")
        if leg:
            return int(abs(cast(dict[str, Any], leg).get("qty", 0)))
        buy_lots = self.config.get("strategy.buy_lots", 1)
        lot_size = self.config.get("strategy.lot_size", 65)
        return int(buy_lots) * int(lot_size)

    def _skip_ato_entry_if_zero_qty(
        self,
        side: str,
        buy_leg_key: str,
        *,
        spot: float,
        sell_strike: int,
        settings: dict[str, Any],
        trigger_reason: str,
    ) -> bool:
        """When ATO lots=0, mark triggered without placing an order. Returns True if skipped."""
        if self._ato_qty(buy_leg_key) > 0:
            return False
        tag = side.upper()
        self.log.info(
            "%s ATO skipped — configured ATO lots is 0 (monitor-only on breach)",
            tag,
        )
        prefix = self._side_prefix(side)
        self.state.set(f"ato.{prefix}_triggered", True)
        breach_count = self._increment_breach_only_count(tag)
        protect_strike = int(self.state.get(f"ato.{prefix}_protect_strike", 0) or 0)
        self.events.publish(
            Event.ATO_MONITOR_BREACH,
            {
                "side": tag,
                "spot": spot,
                "sell_strike": sell_strike,
                "protect_strike": protect_strike,
                "trigger_reason": trigger_reason,
                "trigger_level": settings.get("trigger_level"),
                "monitor_only": True,
                "breach_only_count": breach_count,
            },
        )
        self._maybe_soft_cap_warn(tag, spot)
        return True

    def _position_qty(self, symbol: str) -> int:
        """Return net qty currently held for *symbol* at the broker (0 if none or error).

        Used for idempotency: if a prior ATO order went through but an exception
        prevented state from being updated, this detects the live position so we
        don't place a duplicate order on the next poll tick.
        """
        try:
            positions = self.broker.get_positions()
            if positions is None or positions.empty:
                return 0
            for _, row in positions.iterrows():
                sym = row.get("tradingSymbol") or row.get("tradingsymbol", "")
                if sym == symbol:
                    return int(row.get("netQty", 0) or row.get("buyQty", 0) - row.get("sellQty", 0))
        except Exception as exc:
            self.log.warning("Position check failed for %s: %s", symbol, exc)
        return 0

    # ── ATO entry ────────────────────────────────────────────

    def _place_ce_protection(
        self,
        ce_strike: int,
        spot: float,
        settings: dict[str, int] | None = None,
        trigger_reason: str | None = None,
    ) -> None:
        """BUY N lots at CE protect strike (ce_sell_strike + 50).

        N = qty of the deployed CE buy leg, ensuring the 1:2 ratio
        between buy and sell legs is preserved in the ATO as well.
        """
        if not self.state.get("deployment.confirmed", False):
            self.log.info("CE ATO skipped — deployment no longer confirmed")
            return
        if is_side_halted(self.state, "CE"):
            return

        try:
            with deployment_session("ato_ce_entry", timeout=5.0):
                self._place_ce_protection_locked(ce_strike, spot, settings, trigger_reason)
        except DeploymentLockBusy:
            self.log.info("CE ATO deferred — deployment lock busy")
        return

    def _place_ce_protection_locked(
        self,
        ce_strike: int,
        spot: float,
        settings: dict[str, int] | None = None,
        trigger_reason: str | None = None,
    ) -> None:
        symbol, protect_strike = self._resolve_protect_symbol(
            "CE",
            "ato.ce_protect_symbol",
            "ato.ce_protect_strike",
            "positions.ce_sell",
            ce_strike,
        )
        settings = settings or self._side_settings("CE", ce_strike)
        trigger_reason = trigger_reason or (
            "buffer_trigger_hit" if settings["entry_buffer"] != 0 else "sell_strike_breached"
        )
        if self._skip_ato_entry_if_zero_qty(
            "CE",
            "ce_buy",
            spot=spot,
            sell_strike=ce_strike,
            settings=settings,
            trigger_reason=trigger_reason,
        ):
            return
        ato_qty = self._ato_qty("ce_buy")
        product = self.config.get("strategy.product_type", "MARGIN")

        if not symbol:
            self.log.error(
                "CE protect symbol not in state — was the iron condor deployed? "
                "Cannot place ATO protection."
            )
            return

        # Idempotency: if a live position already exists for this symbol, a prior order
        # went through despite an exception — update state and skip re-ordering to
        # avoid doubling the position and breaking the 1:2 buy/sell ratio.
        if self._position_qty(symbol) > 0:
            self.log.warning(
                "CE ATO idempotency — existing position found for %s; "
                "marking ce_triggered=True, skipping new order",
                symbol,
            )
            self.state.set("ato.ce_triggered", True)
            self.state.set("ato.ce_ato_active", True)
            self._set_registered_exit_qty("CE", ato_qty)
            return

        idem_key = ato_order_key("CE", "BUY", symbol)
        existing_id = get_existing_ato_order(self.state, idem_key)
        if existing_id:
            if self._position_qty(symbol) > 0:
                self.log.info(
                    "CE ATO idempotency — key %s already has order %s (live book)",
                    idem_key,
                    existing_id,
                )
                self.state.set("ato.ce_triggered", True)
                self.state.set("ato.ce_order_id", existing_id)
                self.state.set("ato.ce_ato_active", True)
                self._set_registered_exit_qty("CE", ato_qty)
                return
            self.log.warning(
                "CE ATO stale idempotency — key %s order %s but book qty 0; clearing for re-entry",
                idem_key,
                existing_id,
            )
            clear_ato_order(self.state, idem_key)

        # New cycle entry — allow a fresh SELL exit key after prior retrace.
        clear_ato_order(self.state, ato_order_key("CE", "SELL", symbol))

        order_id = self._execute_protect_buy(
            side="CE",
            symbol=str(symbol),
            ato_qty=ato_qty,
            product=product,
            idem_key=idem_key,
        )
        if not order_id:
            return

        self.state.set("ato.ce_triggered", True)
        if order_id != "BOOK_FILLED":
            self.state.set("ato.ce_order_id", order_id)
        self.state.set("ato.ce_ato_active", True)
        self._set_registered_exit_qty("CE", ato_qty)
        self.state.set("ato.ce_ato_exit_order_id", None, save=False)
        self._ce_cycles = getattr(self, "_ce_cycles", 0) + 1
        self._maybe_soft_cap_warn("CE", spot)
        self.log.info(
            "✅ CE ATO placed: BUY %d × %s (strike %d) → %s [cycle %d]",
            ato_qty,
            symbol,
            protect_strike,
            order_id,
            self._ce_cycles,
        )
        self.events.publish(
            Event.ATO_CE_TRIGGERED,
            {
                "symbol": symbol,
                "qty": ato_qty,
                "spot": spot,
                "order_id": order_id,
                "ato_strike": protect_strike,
                "trigger_reason": trigger_reason,
                "trigger_level": settings["trigger_level"],
            },
        )
        self._append_telemetry_row(
            side="CE",
            action="BUY entry",
            trigger_reason=trigger_reason,
            spot=spot,
            sell_strike=ce_strike,
            trigger_level_used=settings["trigger_level"],
            protect_strike=int(protect_strike),
            protect_symbol=str(symbol),
            order_id=str(order_id),
            qty=ato_qty,
        )
        self._remember_entry(
            side="CE",
            spot=spot,
            order_id=str(order_id),
            qty=ato_qty,
            sell_strike=ce_strike,
            trigger_level=settings["trigger_level"],
            protect_strike=int(protect_strike),
            protect_symbol=str(symbol),
            entry_buffer=settings["entry_buffer"],
            retrace_points=settings["retrace_points"],
            entry_source="auto",
        )

    def _place_pe_protection(
        self,
        pe_strike: int,
        spot: float,
        settings: dict[str, int] | None = None,
        trigger_reason: str | None = None,
    ) -> None:
        """BUY N lots at PE protect strike (pe_sell_strike − 50).

        N = qty of the deployed PE buy leg.
        """
        if not self.state.get("deployment.confirmed", False):
            self.log.info("PE ATO skipped — deployment no longer confirmed")
            return
        if is_side_halted(self.state, "PE"):
            return

        try:
            with deployment_session("ato_pe_entry", timeout=5.0):
                self._place_pe_protection_locked(pe_strike, spot, settings, trigger_reason)
        except DeploymentLockBusy:
            self.log.info("PE ATO deferred — deployment lock busy")
        return

    def _place_pe_protection_locked(
        self,
        pe_strike: int,
        spot: float,
        settings: dict[str, int] | None = None,
        trigger_reason: str | None = None,
    ) -> None:
        symbol, protect_strike = self._resolve_protect_symbol(
            "PE",
            "ato.pe_protect_symbol",
            "ato.pe_protect_strike",
            "positions.pe_sell",
            pe_strike,
        )
        settings = settings or self._side_settings("PE", pe_strike)
        trigger_reason = trigger_reason or (
            "buffer_trigger_hit" if settings["entry_buffer"] != 0 else "sell_strike_breached"
        )
        if self._skip_ato_entry_if_zero_qty(
            "PE",
            "pe_buy",
            spot=spot,
            sell_strike=pe_strike,
            settings=settings,
            trigger_reason=trigger_reason,
        ):
            return
        ato_qty = self._ato_qty("pe_buy")
        product = self.config.get("strategy.product_type", "MARGIN")

        if not symbol:
            self.log.error(
                "PE protect symbol not in state — was the iron condor deployed? "
                "Cannot place ATO protection."
            )
            return

        # Idempotency: same guard as CE side — skip if position already live at broker.
        if self._position_qty(symbol) > 0:
            self.log.warning(
                "PE ATO idempotency — existing position found for %s; "
                "marking pe_triggered=True, skipping new order",
                symbol,
            )
            self.state.set("ato.pe_triggered", True)
            self.state.set("ato.pe_ato_active", True)
            self._set_registered_exit_qty("PE", ato_qty)
            return

        idem_key = ato_order_key("PE", "BUY", symbol)
        existing_id = get_existing_ato_order(self.state, idem_key)
        if existing_id:
            if self._position_qty(symbol) > 0:
                self.log.info(
                    "PE ATO idempotency — key %s already has order %s (live book)",
                    idem_key,
                    existing_id,
                )
                self.state.set("ato.pe_triggered", True)
                self.state.set("ato.pe_order_id", existing_id)
                self.state.set("ato.pe_ato_active", True)
                self._set_registered_exit_qty("PE", ato_qty)
                return
            self.log.warning(
                "PE ATO stale idempotency — key %s order %s but book qty 0; clearing for re-entry",
                idem_key,
                existing_id,
            )
            clear_ato_order(self.state, idem_key)

        # New cycle entry — allow a fresh SELL exit key after prior retrace.
        clear_ato_order(self.state, ato_order_key("PE", "SELL", symbol))

        order_id = self._execute_protect_buy(
            side="PE",
            symbol=str(symbol),
            ato_qty=ato_qty,
            product=product,
            idem_key=idem_key,
        )
        if not order_id:
            return

        self.state.set("ato.pe_triggered", True)
        if order_id != "BOOK_FILLED":
            self.state.set("ato.pe_order_id", order_id)
        self.state.set("ato.pe_ato_active", True)
        self._set_registered_exit_qty("PE", ato_qty)
        self.state.set("ato.pe_ato_exit_order_id", None, save=False)
        self._pe_cycles = getattr(self, "_pe_cycles", 0) + 1
        self._maybe_soft_cap_warn("PE", spot)
        self.log.info(
            "✅ PE ATO placed: BUY %d × %s (strike %d) → %s [cycle %d]",
            ato_qty,
            symbol,
            protect_strike,
            order_id,
            self._pe_cycles,
        )
        self.events.publish(
            Event.ATO_PE_TRIGGERED,
            {
                "symbol": symbol,
                "qty": ato_qty,
                "spot": spot,
                "order_id": order_id,
                "ato_strike": protect_strike,
                "trigger_reason": trigger_reason,
                "trigger_level": settings["trigger_level"],
            },
        )
        self._append_telemetry_row(
            side="PE",
            action="BUY entry",
            trigger_reason=trigger_reason,
            spot=spot,
            sell_strike=pe_strike,
            trigger_level_used=settings["trigger_level"],
            protect_strike=int(protect_strike),
            protect_symbol=str(symbol),
            order_id=str(order_id),
            qty=ato_qty,
        )
        self._remember_entry(
            side="PE",
            spot=spot,
            order_id=str(order_id),
            qty=ato_qty,
            sell_strike=pe_strike,
            trigger_level=settings["trigger_level"],
            protect_strike=int(protect_strike),
            protect_symbol=str(symbol),
            entry_buffer=settings["entry_buffer"],
            retrace_points=settings["retrace_points"],
            entry_source="auto",
        )

    # ── ATO retracement exit ──────────────────────────────────

    def _exit_ce_ato(
        self, spot: float, ce_strike: int, settings: dict[str, int] | None = None
    ) -> None:
        """SELL N lots at CE protect strike on retracement.

        Resets ce_triggered to False so the breach can re-fire if
        the market moves outside the range again.
        """
        symbol = self.state.get("ato.ce_protect_symbol")
        ato_qty = self._registered_exit_qty("CE", "ce_buy")
        product = self.config.get("strategy.product_type", "MARGIN")
        settings = settings or self._side_settings("CE", ce_strike)

        if not symbol:
            return

        idem_key = ato_order_key("CE", "SELL", symbol)
        existing_id = get_existing_ato_order(self.state, idem_key)
        if existing_id:
            self._ce_protect_seen_at_broker = False
            self.state.set("ato.ce_ato_active", False)
            self.state.set("ato.ce_triggered", False)
            self.state.set("ato.ce_ato_exit_order_id", existing_id)
            self._mark_awaiting_clearance_after_exit("CE", spot, settings)
            return

        try:
            order_id = self._place_ato_aggressive_limit(
                symbol=symbol,
                qty=ato_qty,
                side="SELL",
                product=product,
            )
            record_ato_order(self.state, idem_key, str(order_id))
            # Free BUY key so CE can re-enter if spot breaches again today.
            clear_ato_order(self.state, ato_order_key("CE", "BUY", symbol))
            # Algo exit — do not treat next empty-book poll as operator manual exit.
            self._ce_protect_seen_at_broker = False
            self.state.set("ato.ce_ato_active", False)
            self.state.set("ato.ce_triggered", False)  # reset — breach can re-fire after clearance
            self.state.set("ato.ce_ato_exit_order_id", order_id)
            self._mark_awaiting_clearance_after_exit("CE", spot, settings)
            self.log.info(
                "✅ CE ATO exited on retracement — Spot %.1f, SELL %d × %s → %s",
                spot,
                ato_qty,
                symbol,
                order_id,
            )
            self.events.publish(
                Event.ATO_CE_EXITED,
                {"symbol": symbol, "qty": ato_qty, "spot": spot, "order_id": order_id},
            )
            self._append_telemetry_row(
                side="CE",
                action="SELL exit",
                trigger_reason="retrace_exit",
                spot=spot,
                sell_strike=ce_strike,
                trigger_level_used=settings["exit_level"],
                protect_strike=int(self.state.get("ato.ce_protect_strike", 0) or 0),
                protect_symbol=str(symbol),
                order_id=str(order_id),
                qty=ato_qty,
            )
            self._record_trade_cycle(
                side="CE",
                spot=spot,
                order_id=str(order_id),
                sell_strike=ce_strike,
                settings=settings,
                protect_symbol=str(symbol),
                protect_strike=int(self.state.get("ato.ce_protect_strike", 0) or 0),
                qty=ato_qty,
            )
        except Exception as exc:
            self.log.error("❌ CE ATO exit order FAILED: %s", exc)
            self.events.publish(
                Event.MODULE_ERROR,
                {
                    "module": self.name,
                    "scenario": "order_rejection",
                    "severity": "major",
                    "category": "order",
                    "title": "CE ATO exit order failed",
                    "error_message": str(exc),
                    "next_action": "Review positions and broker order book immediately.",
                },
            )

    def _exit_pe_ato(
        self, spot: float, pe_strike: int, settings: dict[str, int] | None = None
    ) -> None:
        """SELL N lots at PE protect strike on retracement.

        Resets pe_triggered to False so the breach can re-fire.
        """
        symbol = self.state.get("ato.pe_protect_symbol")
        ato_qty = self._registered_exit_qty("PE", "pe_buy")
        product = self.config.get("strategy.product_type", "MARGIN")
        settings = settings or self._side_settings("PE", pe_strike)

        if not symbol:
            return

        idem_key = ato_order_key("PE", "SELL", symbol)
        existing_id = get_existing_ato_order(self.state, idem_key)
        if existing_id:
            self._pe_protect_seen_at_broker = False
            self.state.set("ato.pe_ato_active", False)
            self.state.set("ato.pe_triggered", False)
            self.state.set("ato.pe_ato_exit_order_id", existing_id)
            self._mark_awaiting_clearance_after_exit("PE", spot, settings)
            return

        try:
            order_id = self._place_ato_aggressive_limit(
                symbol=symbol,
                qty=ato_qty,
                side="SELL",
                product=product,
            )
            record_ato_order(self.state, idem_key, str(order_id))
            # Free BUY key so PE can re-enter if spot breaches again today.
            clear_ato_order(self.state, ato_order_key("PE", "BUY", symbol))
            # Algo exit — do not treat next empty-book poll as operator manual exit.
            self._pe_protect_seen_at_broker = False
            self.state.set("ato.pe_ato_active", False)
            self.state.set("ato.pe_triggered", False)  # reset — breach can re-fire after clearance
            self.state.set("ato.pe_ato_exit_order_id", order_id)
            self._mark_awaiting_clearance_after_exit("PE", spot, settings)
            self.log.info(
                "✅ PE ATO exited on retracement — Spot %.1f, SELL %d × %s → %s",
                spot,
                ato_qty,
                symbol,
                order_id,
            )
            self.events.publish(
                Event.ATO_PE_EXITED,
                {"symbol": symbol, "qty": ato_qty, "spot": spot, "order_id": order_id},
            )
            self._append_telemetry_row(
                side="PE",
                action="SELL exit",
                trigger_reason="retrace_exit",
                spot=spot,
                sell_strike=pe_strike,
                trigger_level_used=settings["exit_level"],
                protect_strike=int(self.state.get("ato.pe_protect_strike", 0) or 0),
                protect_symbol=str(symbol),
                order_id=str(order_id),
                qty=ato_qty,
            )
            self._record_trade_cycle(
                side="PE",
                spot=spot,
                order_id=str(order_id),
                sell_strike=pe_strike,
                settings=settings,
                protect_symbol=str(symbol),
                protect_strike=int(self.state.get("ato.pe_protect_strike", 0) or 0),
                qty=ato_qty,
            )
        except Exception as exc:
            self.log.error("❌ PE ATO exit order FAILED: %s", exc)
            self.events.publish(
                Event.MODULE_ERROR,
                {
                    "module": self.name,
                    "scenario": "order_rejection",
                    "severity": "major",
                    "category": "order",
                    "title": "PE ATO exit order failed",
                    "error_message": str(exc),
                    "next_action": "Review positions and broker order book immediately.",
                },
            )

    def set_retrace_points(self, points: int) -> None:
        """Update ATO retrace points at runtime (called from Telegram /ato handler).

        retrace_points is a symmetric buffer applied to BOTH entry and exit:
          • Entry: ATO fires when spot moves *outside* sell_strike ± retrace_points
                   (CE: spot ≥ ce_sell + retrace_points | PE: spot ≤ pe_sell − retrace_points)
          • Exit:  ATO exits when spot moves *back inside*  sell_strike ± retrace_points
                   (CE: spot ≤ ce_sell − retrace_points | PE: spot ≥ pe_sell + retrace_points)
        This prevents both premature ATO entry on a brief graze of the sell strike
        and whipsaw exit/re-entry in choppy conditions around it.
        """
        self.state.set("ato.retrace_points", points)
        self.log.info("ATO retrace points changed → %d", points)
        self.events.publish(Event.ATO_RETRACE_POINTS_CHANGED, {"retrace_points": points})

    # keep old name as alias so existing wiring doesn't break during transition
    def set_exit_points(self, points: int) -> None:  # noqa: D401
        """Deprecated alias for set_retrace_points — will be removed."""
        self.set_retrace_points(points)

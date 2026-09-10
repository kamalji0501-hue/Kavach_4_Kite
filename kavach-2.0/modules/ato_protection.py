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
import time
import pathlib
import shutil
import threading
from decimal import Decimal
from typing import Any, Literal, cast

from core import utils
from core.ato_book_validation import lots_fulfilled, net_qty_for_symbol, remainder_qty
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

try:
    from core.money_audit import audit, audit_span, new_correlation_id
except Exception:  # pragma: no cover
    def audit(*_a, **_k):  # type: ignore
        return None

    def new_correlation_id(prefix: str = "c") -> str:  # type: ignore
        return prefix

    from contextlib import contextmanager

    @contextmanager
    def audit_span(event, **fields):  # type: ignore
        yield dict(fields)

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
        self._last_replay_market_time = None
        self._ce_exit_streak: int = 0
        self._pe_exit_streak: int = 0
        self._cross_side_gap_warned: bool = False

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
                    self._maybe_run_pnl_exits(refresh_positions=True)
                    if self._sleep(self._effective_poll_interval(cfg_ato)):
                        return
                    continue

                if not is_past_monitoring_start():
                    if self._sleep(self._effective_poll_interval(cfg_ato)):
                        return
                    continue

                self._check_breach()
                self._maybe_run_pnl_exits()

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


    def _maybe_run_pnl_exits(self, *, refresh_positions: bool = False) -> None:
        """Safe Exit / Take Profit vs day PnL (same poll cadence)."""
        try:
            from core.pnl_exit_guard import check_and_maybe_fire

            st = self.state
            armed = bool(st.get("pnl_exit.safe_on") or st.get("pnl_exit.tp_on"))
            if refresh_positions and armed and self.broker is not None:
                try:
                    self.broker.get_positions()
                except Exception:
                    pass
            try:
                from core.day_pnl_cache import refresh_hybrid_day_pnl

                refresh_hybrid_day_pnl(broker=self.broker)
            except Exception:
                pass
            check_and_maybe_fire(broker=self.broker, state=self.state, events=self.events)
        except Exception as exc:
            self.log.warning("pnl_exit check soft-failed: %s", exc)

    def _effective_poll_interval(self, cfg_ato: dict[str, Any]) -> int:
        state_poll = self.state.get("ato.poll_interval_seconds")
        if isinstance(state_poll, int) and state_poll >= 0:
            return state_poll
        return int(cfg_ato.get("poll_interval_seconds", 2))

    def _resolve_nifty_spot(self) -> Decimal:
        """Read Feeder NIFTY cache (Datafeedbot sid 13). Never call Dhan from ATO."""
        max_age = consumer_max_age_for_trading()
        try:
            from core.feeder_ipc import peek_index_ltp

            live = peek_index_ltp(wait_seconds=0.4)
            if live and float(live) > 0:
                self._consecutive_ltp_failures = 0
                return Decimal(str(live))
        except Exception:
            pass
        spot = resolve_nifty_ltp_from_cache(max_age_seconds=max_age)
        self._consecutive_ltp_failures = 0
        return Decimal(str(spot))

    def _replay_market_time_from_cache(self):
        """UAT replay clock from DRISHTI cache, or None for live."""
        from datetime import datetime

        from core.nifty_ltp_feed import read_nifty_ltp_cache

        snap = read_nifty_ltp_cache()
        raw = getattr(snap, "replay_market_time", None) if snap is not None else None
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw))
        except (TypeError, ValueError):
            return None

    def _should_skip_for_replay_jump(self) -> bool:
        """Skip entry/exit when UAT replay leaps (loop reset / file seek).

        At 3x with 1-minute ticks, normal polls advance ~1–2 minutes of market
        time. A jump of several minutes (or hours on loop) is not a real
        retrace — it caused false CE exits (user saw 14:42/24260 on DRISHTI
        while ATO exited on post-loop 09:15/24187).
        """
        import time as time_mod

        now_mkt = self._replay_market_time_from_cache()
        last = getattr(self, "_last_replay_market_time", None)
        self._last_replay_market_time = now_mkt
        if now_mkt is None or last is None:
            return False
        delta = (now_mkt - last).total_seconds()
        abs_delta = abs(delta)
        max_jump = 180  # 3 minutes of market time
        if abs_delta <= max_jump:
            return False
        self._ce_exit_streak = 0
        self._pe_exit_streak = 0
        # Hold ATO frozen long enough that 2-poll exit confirm cannot fire on
        # the first morning ticks after an EOD→open loop.
        self._replay_resync_until = time_mod.monotonic() + 60.0
        # Backfill entry clock from pre-jump time so an already-open ATO
        # (no stamp yet) cannot exit on morning open after a loop rewind.
        if delta < 0 and last is not None:
            for side in ("ce", "pe"):
                if self.state.get(f"ato.{side}_ato_active") and not self.state.get(
                    f"ato.{side}_entry_replay_market_time"
                ):
                    self.state.set(
                        f"ato.{side}_entry_replay_market_time",
                        last.isoformat(),
                    )
        direction = "backward (loop)" if delta < 0 else "forward (seek)"
        self.log.warning(
            "ATO skip — UAT replay market time jumped %.0fs %s (%s → %s); "
            "freezing entry/exit for 60s wall-clock",
            abs_delta,
            direction,
            last.isoformat(timespec="seconds"),
            now_mkt.isoformat(timespec="seconds"),
        )
        return True

    def _in_replay_resync(self) -> bool:
        import time as time_mod

        until = float(getattr(self, "_replay_resync_until", 0.0) or 0.0)
        return time_mod.monotonic() < until

    def _record_side_entry_replay_time(self, side: str) -> None:
        """Stamp UAT replay clock when ATO opens — blocks exit after a loop reset."""
        mkt = self._replay_market_time_from_cache()
        key = f"ato.{side.lower()}_entry_replay_market_time"
        if mkt is None:
            self.state.set(key, None)
            return
        self.state.set(key, mkt.isoformat())

    def _exit_blocked_by_replay_loop(self, side: str) -> bool:
        """True when replay clock went backward vs this side's entry time.

        Example: CE entered at replay 14:10 / spot 24240; file loops to 09:15 /
        24166. Spot ≤ exit looks like a retrace, but market time rewound — not a
        real session retrace. User still sees last DRISHTI card (~14:42/24260).
        """
        raw = self.state.get(f"ato.{side.lower()}_entry_replay_market_time")
        if not raw:
            return False
        now_mkt = self._replay_market_time_from_cache()
        if now_mkt is None:
            return False
        from datetime import datetime

        try:
            entered = datetime.fromisoformat(str(raw))
        except (TypeError, ValueError):
            return False
        if now_mkt.tzinfo is None and entered.tzinfo is not None:
            now_mkt = now_mkt.replace(tzinfo=entered.tzinfo)
        if entered.tzinfo is None and now_mkt.tzinfo is not None:
            entered = entered.replace(tzinfo=now_mkt.tzinfo)
        if now_mkt >= entered:
            return False
        self.log.warning(
            "%s exit blocked — UAT replay rewound (%s → %s); "
            "not a real retrace vs entry clock. Holding ATO until replay "
            "passes entry time again.",
            side,
            entered.isoformat(timespec="seconds"),
            now_mkt.isoformat(timespec="seconds"),
        )
        return True

    def _apply_cross_side_level_gap(
        self,
        ce_settings: dict[str, Any] | None,
        pe_settings: dict[str, Any] | None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Warn when PE entry sits inside the CE exit band — never rewrite levels.

        Operator Buffer Manager / Register NIFTY levels are authoritative. Silently
        clamping PE entry (old ``ce_exit − 5`` rule) made ATO Status and the engine
        fire at a different level than Buffer Manager showed.
        """
        if not ce_settings or not pe_settings:
            return ce_settings, pe_settings
        gap = Decimal("5")
        ce_exit = Decimal(str(ce_settings["exit_level"]))
        pe_trig = Decimal(str(pe_settings["trigger_level"]))
        if pe_trig > ce_exit - gap and not getattr(self, "_cross_side_gap_warned", False):
            self._cross_side_gap_warned = True
            self.log.warning(
                "ATO cross-side note — PE entry %s is within %s pts of CE exit %s; "
                "keeping operator levels (Buffer Manager is source of truth). "
                "Widen CE exit or lower PE entry in Buffer Manager if undesired.",
                pe_trig,
                gap,
                ce_exit,
            )
        return ce_settings, pe_settings

    def _exit_confirm_polls(self) -> int:
        cfg_ato = self.config.get("ato", {}) if isinstance(self.config, dict) else {}
        try:
            return max(1, int(cfg_ato.get("exit_confirm_polls", 2)))
        except (TypeError, ValueError):
            return 2

    def _maybe_alert_ltp_failures(self, cfg_ato: dict[str, Any]) -> None:
        threshold = int(cfg_ato.get("ltp_failure_alert_threshold", 5))
        failures = getattr(self, "_consecutive_ltp_failures", 0)
        if failures < threshold:
            return
        if not getattr(self, "_ltp_failure_alerted", False):
            self._ltp_failure_alerted = True
            try:
                from core.ato_readiness_notify import tick as _ato_ready_tick
                _ato_ready_tick()
            except Exception:
                pass
            self.log.error(
                "ATO: %d consecutive LTP cache failures — Feeder/Datafeedbot feed required (no Dhan poll from KAVACH)",
                failures,
            )
            self.events.publish(
                Event.MODULE_ERROR,
                {
                    "module": self.name,
                    "scenario": "module_error",
                    "failures": failures,
                    "error": "NIFTY LTP cache stale or missing — check Datafeedbot / nifty_ltp_cache.json",
                },
            )
        pause_after = int(cfg_ato.get("ltp_failure_pause_after", threshold))
        if failures >= pause_after and not self.state.get("algo.paused", False):
            self.state.set("algo.paused", True)
            self.state.set("algo.pause_reason", "nifty_ltp_cache_stale")
            self.log.warning(
                "ATO: pausing algo after %d stale cache reads — restart Datafeedbot or wait for cache",
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
        """ATO protect entry/exit — SEBI-safe marketable LIMIT (not MARKET).

        If ``self.order_manager`` is attached, punch via backend Place Order
        workflow immediately (no Telegram questions). Otherwise keep legacy
        broker.place_aggressive_limit / place_market_order path.
        """
        corr = new_correlation_id("ato")
        om = getattr(self, "order_manager", None)
        try:
            mode = getattr(om, "mode", None) if om is not None else None
            audit(
                "ato.order_sink.decision",
                corr=corr,
                via="order_manager" if om is not None else "legacy_broker",
                om_mode=mode,
                symbol=str(symbol),
                qty=int(qty),
                side=str(side),
                product=str(product),
            )
            self.log.info(
                "ATO order sink via=%s om_mode=%s symbol=%s side=%s qty=%s corr=%s",
                "order_manager" if om is not None else "legacy_broker",
                mode,
                symbol,
                side,
                qty,
                corr,
            )
        except Exception:
            pass
        audit(
            "ato.place_aggressive.request",
            corr=corr,
            symbol=str(symbol),
            qty=int(qty),
            side=str(side),
            product=str(product),
            via="order_manager" if om is not None else "legacy_broker",
        )
        if om is not None:
            with audit_span(
                "ato.place_aggressive.om",
                corr=corr,
                symbol=str(symbol),
                qty=int(qty),
                side=str(side),
                product=str(product),
            ) as span:
                opt_ltp = None
                try:
                    opt_ltp = self._resolve_option_premium(symbol, "", spot=0.0)
                except Exception:
                    opt_ltp = None
                oid = str(
                    om.punch_ato(
                        symbol=symbol,
                        qty=int(qty),
                        side=side,
                        product=product,
                        reason="ato_protect",
                        ltp=opt_ltp,
                    )
                )
                if str(side).upper() == "BUY" and opt_ltp:
                    try:
                        from core.ato_exec import buy_trigger_limit

                        trig, lim = buy_trigger_limit(float(opt_ltp))
                        tag = "ce" if "CE" in str(symbol).upper() or "CALL" in str(symbol).upper() else "pe"
                        self.state.set(f"ato.{tag}_buy_trigger", trig, save=False)
                        self.state.set(f"ato.{tag}_buy_limit", lim, save=False)
                        self.state.set(f"ato.{tag}_buy_oid", oid, save=False)
                        self.state.set(f"ato.{tag}_buy_qty", int(qty), save=False)
                    except Exception:
                        pass
                span["order_id"] = oid
                self.log.info(
                    "ATO punch via OrderManager symbol=%s side=%s qty=%s product=%s id=%s corr=%s",
                    symbol,
                    side,
                    qty,
                    product,
                    oid,
                    corr,
                )
                return oid
        op = self._operator_settings()
        place = getattr(self.broker, "place_aggressive_limit", None)
        if callable(place):
            with audit_span(
                "ato.place_aggressive.broker_limit",
                corr=corr,
                symbol=str(symbol),
                qty=int(qty),
                side=str(side),
                product=str(product),
                buffer_pct=float(op.get("limit_buffer_pct", 10.0)),
                chase_timeout_sec=float(op.get("limit_chase_timeout_sec", 45.0)),
            ) as span:
                oid = str(
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
                span["order_id"] = oid
                self.log.info(
                    "ATO punch via broker.place_aggressive_limit symbol=%s side=%s qty=%s id=%s corr=%s",
                    symbol,
                    side,
                    qty,
                    oid,
                    corr,
                )
                return oid
        # Legacy test doubles without place_aggressive_limit.
        with audit_span(
            "ato.place_aggressive.broker_market_legacy",
            corr=corr,
            symbol=str(symbol),
            qty=int(qty),
            side=str(side),
            product=str(product),
        ) as span:
            oid = str(
                self.broker.place_market_order(
                    symbol=symbol,
                    qty=qty,
                    side=side,
                    trade_type=product,
                )
            )
            span["order_id"] = oid
            self.log.warning(
                "ATO punch via LEGACY place_market_order symbol=%s side=%s qty=%s id=%s corr=%s",
                symbol,
                side,
                qty,
                oid,
                corr,
            )
            return oid

    def _maybe_exit_dyn_hedge(self, side: str) -> None:
        """Exit remaining 35% dynamic hedge whenever ATO fires on this side.

        Conditions: toggle ON and live broker qty > 0. Does not re-buy the hedge.
        """
        from datetime import date

        side_u = str(side).upper()
        prefix = "pe" if side_u == "PE" else "ce"
        if not bool(self.state.get("dyn_hedge.exit_enabled", False)):
            self.log.info(
                "35%% dynamic hedge skip side=%s — exit_enabled=False "
                "(enable via KAVACH 2.0 menu 🛡 or re-Register with dyn legs)",
                side_u,
            )
            return
        exited_key = f"dyn_hedge.{prefix}_exited_date"
        leg = self.state.get(f"positions.{prefix}_dyn_hedge")
        if not isinstance(leg, dict):
            self.log.info(
                "35%% dynamic hedge skip side=%s — no positions.%s_dyn_hedge leg",
                side_u,
                prefix,
            )
            return
        symbol = str(leg.get("symbol") or "").strip()
        try:
            registered_qty = abs(int(leg.get("qty") or 0))
        except (TypeError, ValueError):
            registered_qty = 0
        if not symbol:
            self.log.info("35%% dynamic hedge skip side=%s — blank symbol", side_u)
            return
        try:
            live_qty = max(0, int(self._position_qty(symbol) or 0))
        except Exception:
            live_qty = 0
        if live_qty <= 0:
            self.log.info(
                "35%% dynamic hedge skip side=%s — live qty=0 for %s",
                side_u,
                symbol,
            )
            return
        qty = live_qty if registered_qty <= 0 else min(live_qty, registered_qty)
        product = self.config.get("strategy.product_type", "MARGIN")
        try:
            order_id = self._place_ato_aggressive_limit(
                symbol=symbol,
                qty=qty,
                side="SELL",
                product=product,
            )
        except Exception as exc:
            self.log.error(
                "35%% dynamic hedge exit FAILED side=%s symbol=%s qty=%d: %s",
                side_u,
                symbol,
                qty,
                exc,
            )
            return
        self.state.set(exited_key, date.today().isoformat())
        self.log.info(
            "35%% dynamic hedge exited: side=%s symbol=%s qty=%d order=%s",
            side_u,
            symbol,
            qty,
            order_id,
        )
        try:
            self.events.publish(
                Event.DYN_HEDGE_EXITED,
                {
                    "symbol": symbol,
                    "qty": qty,
                    "order_id": order_id,
                    "reason": "dyn_hedge_ato",
                    "side": side_u,
                },
            )
        except Exception as exc:
            self.log.warning("dyn hedge exit notify publish failed: %s", exc)

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
        try:
            from core.desk_alerts import emit_desk_alert

            emit_desk_alert(
                severity="orange",
                category="ATO size cap",
                alert=f"{str(side).upper()} ATO hit its size cap — order still went through.",
                log=(
                    f"{side} ATO soft cap — exposure {exposure} "
                    f"(cycles={cycles} breach_only={breach_only}) spot={spot:.1f}"
                ),
                side=str(side).upper(),
            )
        except Exception:
            pass
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

    
    def _ato_order_status(self, order_id: str) -> str | None:
        """Best-effort Kite order status (OPEN/COMPLETE/…)."""
        oid = str(order_id or "").strip()
        if not oid:
            return None
        try:
            book = self.broker.get_orderbook()
        except Exception:
            return None
        try:
            if hasattr(book, "empty") and book.empty:
                return None
            if hasattr(book, "iterrows"):
                for _, row in book.iterrows():
                    rid = str(row.get("order_id") or row.get("orderId") or "")
                    if rid == oid:
                        return str(row.get("status") or "").strip().upper() or None
            elif isinstance(book, list):
                for row in book:
                    rid = str(row.get("order_id") or row.get("orderId") or "")
                    if rid == oid:
                        return str(row.get("status") or "").strip().upper() or None
        except Exception:
            return None
        return None

    def _wait_protect_fill(
        self,
        *,
        symbol: str,
        ato_qty: int,
        lot_size: int,
        order_id: str | None,
        wait_s: float,
        polls: int,
    ) -> int | None:
        """Poll book (and order status) briefly so fill lag does not trigger another BUY."""
        import time as _time
        from core.ato_book_validation import lots_fulfilled, net_qty_for_symbol

        last = net_qty_for_symbol(self.broker, symbol)
        n = max(1, int(polls))
        delay = max(0.05, float(wait_s) / n)
        for _ in range(n):
            if last is not None and lots_fulfilled(last, ato_qty, lot_size):
                return int(last)
            if order_id:
                st = self._ato_order_status(str(order_id))
                if st in ("REJECTED", "CANCELLED", "CANCELED"):
                    return last if last is not None else 0
            _time.sleep(delay)
            last = net_qty_for_symbol(self.broker, symbol)
        return last

    def _execute_protect_buy(
        self,
        *,
        side: str,
        symbol: str,
        ato_qty: int,
        product: str,
        idem_key: str,
    ) -> str | None:
        """Place BUY with book validation + top-up retries; halt side when exhausted.

        Never re-buys full size when the book already has enough (or too much).
        Fill-lag: wait/poll before treating a shortfall as another place.
        """
        from core.ato_book_validation import (
            lots_fulfilled,
            net_qty_for_symbol,
            remainder_qty,
        )

        op = self._operator_settings()
        max_retries = int(op.get("order_retry_max", 3))
        lot_size = int(op.get("lot_size", 65))
        tag = side.upper()
        fill_wait_s = float(op.get("order_fill_wait_seconds", 1.5))
        fill_polls = int(op.get("order_fill_polls", 4))

        from core.zerodha_instruments import nifty_expiry_key

        sell_leg_key = "positions.pe_sell" if tag == "PE" else "positions.ce_sell"
        sell_leg = self.state.get(sell_leg_key) if self.state else None
        sell_symbol = ""
        if isinstance(sell_leg, dict):
            sell_symbol = str(sell_leg.get("symbol") or "")
        want_exp = nifty_expiry_key(sell_symbol)
        got_exp = nifty_expiry_key(symbol)
        if want_exp and got_exp and want_exp != got_exp:
            self.log.error(
                "%s ATO buy blocked — protect %s expiry %s != Batman sell %s (%s)",
                tag,
                symbol,
                got_exp,
                sell_symbol,
                want_exp,
            )
            halt_side(self.state, tag, reason="protect_expiry_mismatch")
            return None

        existing = get_existing_ato_order(self.state, idem_key)
        if existing:
            # Still open? Wait for fill; do not punch another full BUY.
            net_ex = net_qty_for_symbol(self.broker, symbol)
            if net_ex is not None and lots_fulfilled(net_ex, ato_qty, lot_size):
                self.log.info(
                    "%s ATO idempotency — order %s already filled in book qty=%s",
                    tag,
                    existing,
                    net_ex,
                )
                return str(existing)
            status = self._ato_order_status(str(existing))
            if status in ("OPEN", "TRIGGER PENDING", "AMO REQ RECEIVED", "PUT ORDER REQ RECEIVED"):
                self.log.info(
                    "%s ATO idempotency — order %s still %s; waiting, no second BUY",
                    tag,
                    existing,
                    status,
                )
                filled = self._wait_protect_fill(
                    symbol=symbol,
                    ato_qty=ato_qty,
                    lot_size=lot_size,
                    order_id=str(existing),
                    wait_s=fill_wait_s,
                    polls=fill_polls,
                )
                if filled is not None and lots_fulfilled(filled, ato_qty, lot_size):
                    return str(existing)
                # Still short/open — return existing id; do not place another.
                return str(existing)
            if status in ("COMPLETE", "FILLED"):
                return str(existing)

        net = net_qty_for_symbol(self.broker, symbol)
        if net is not None and lots_fulfilled(net, ato_qty, lot_size):
            if int(net) > int(ato_qty):
                self.log.warning(
                    "%s ATO book overfill qty=%s expected=%s on %s — no further BUY",
                    tag,
                    net,
                    ato_qty,
                    symbol,
                )
            else:
                self.log.info("%s ATO book already shows fill for %s (qty=%d)", tag, symbol, net)
            return "BOOK_FILLED"

        last_exc: Exception | None = None
        last_order_id: str | None = None
        for attempt in range(1, max_retries + 1):
            try:
                net_before = net_qty_for_symbol(self.broker, symbol)
                if net_before is not None and lots_fulfilled(net_before, ato_qty, lot_size):
                    if int(net_before) > int(ato_qty):
                        self.log.warning(
                            "%s ATO overfill before attempt %d qty=%s — stop",
                            tag,
                            attempt,
                            net_before,
                        )
                    return last_order_id or "BOOK_FILLED"

                need = (
                    remainder_qty(int(net_before or 0), ato_qty, lot_size)
                    if net_before is not None
                    else int(ato_qty)
                )
                if need <= 0:
                    return last_order_id or "BOOK_FILLED"

                # If a prior attempt order is still working, do not place again.
                if last_order_id:
                    st = self._ato_order_status(str(last_order_id))
                    if st in ("OPEN", "TRIGGER PENDING", "AMO REQ RECEIVED", "PUT ORDER REQ RECEIVED"):
                        self.log.info(
                            "%s ATO buy attempt %d — prior order %s still %s; wait not rebuy",
                            tag,
                            attempt,
                            last_order_id,
                            st,
                        )
                        filled = self._wait_protect_fill(
                            symbol=symbol,
                            ato_qty=ato_qty,
                            lot_size=lot_size,
                            order_id=str(last_order_id),
                            wait_s=fill_wait_s,
                            polls=fill_polls,
                        )
                        if filled is not None and lots_fulfilled(filled, ato_qty, lot_size):
                            return str(last_order_id)
                        continue

                order_id = self._place_ato_aggressive_limit(
                    symbol=symbol,
                    qty=int(need),
                    side="BUY",
                    product=product,
                )
                last_order_id = str(order_id)
                record_ato_order(self.state, idem_key, str(order_id))
                sent = str(getattr(self.broker, "_last_order_tradingsymbol", "") or symbol)
                sent_exp = nifty_expiry_key(sent)
                req_exp = nifty_expiry_key(symbol)
                if req_exp and sent_exp and req_exp != sent_exp:
                    self.log.error(
                        "%s ATO punched %s but requested %s — halt, no retry",
                        tag,
                        sent,
                        symbol,
                    )
                    halt_side(self.state, tag, reason="punched_wrong_expiry")
                    return None

                filled = self._wait_protect_fill(
                    symbol=symbol,
                    ato_qty=ato_qty,
                    lot_size=lot_size,
                    order_id=str(order_id),
                    wait_s=fill_wait_s,
                    polls=fill_polls,
                )
                net_after = filled if filled is not None else net_qty_for_symbol(self.broker, symbol)
                net_sent = (
                    net_qty_for_symbol(self.broker, sent)
                    if sent and sent != symbol
                    else net_after
                )
                if (
                    sent
                    and sent != symbol
                    and net_after is not None
                    and int(net_after or 0) == 0
                    and net_sent is not None
                    and int(net_sent or 0) != 0
                ):
                    self.log.error(
                        "%s ATO fill landed on %s qty=%s, not %s — halt, no retry",
                        tag,
                        sent,
                        net_sent,
                        symbol,
                    )
                    halt_side(self.state, tag, reason="fill_wrong_contract")
                    return None
                if net_after is None or lots_fulfilled(net_after, ato_qty, lot_size):
                    if net_after is not None and int(net_after) > int(ato_qty):
                        self.log.warning(
                            "%s ATO book overfill after buy qty=%s expected=%s — no further BUY",
                            tag,
                            net_after,
                            ato_qty,
                        )
                    return str(order_id)
                self.log.warning(
                    "%s ATO buy attempt %d — book qty %s still short of %d on %s (placed %s)",
                    tag,
                    attempt,
                    net_after,
                    ato_qty,
                    symbol,
                    need,
                )
            except Exception as exc:
                last_exc = exc
                net_retry = net_qty_for_symbol(self.broker, symbol)
                if net_retry is not None and lots_fulfilled(net_retry, ato_qty, lot_size):
                    return "BOOK_FILLED"
                self.log.warning("%s ATO buy attempt %d failed: %s", tag, attempt, exc)

        if last_exc and "needs option ltp" in str(last_exc).lower():
            self.log.error(
                "%s ATO buy deferred — option LTP missing after %s attempts (side stays armed)",
                tag,
                max_retries,
            )
            return None

        # Final book check — overfill/fill may have landed after last attempt.
        net_final = net_qty_for_symbol(self.broker, symbol)
        if net_final is not None and lots_fulfilled(net_final, ato_qty, lot_size):
            return last_order_id or "BOOK_FILLED"

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
        min_hyst = Decimal("1")
        if side == "CE":
            trigger_level = strike + entry_buffer
            exit_level = strike - retrace_points
            # Exit must be strictly below entry or we exit before/at trigger.
            if exit_level >= trigger_level:
                fixed = trigger_level - min_hyst
                if not getattr(self, "_hyst_fix_ce", False):
                    self._hyst_fix_ce = True
                    self.log.warning(
                        "ATO hysteresis FIX CE: sell=%s entry_buf=%s exit_buf=%s "
                        "→ trigger=%s exit %s→%s (exit must be < trigger)",
                        sell_strike,
                        entry_buffer,
                        retrace_points,
                        trigger_level,
                        exit_level,
                        fixed,
                    )
                exit_level = fixed
        else:
            trigger_level = strike - entry_buffer
            exit_level = strike + retrace_points
            # Exit must be strictly above entry or we exit while still in entry zone.
            if exit_level <= trigger_level:
                fixed = trigger_level + min_hyst
                if not getattr(self, "_hyst_fix_pe", False):
                    self._hyst_fix_pe = True
                    self.log.warning(
                        "ATO hysteresis FIX PE: sell=%s entry_buf=%s exit_buf=%s "
                        "→ trigger=%s exit %s→%s (exit must be > trigger)",
                        sell_strike,
                        entry_buffer,
                        retrace_points,
                        trigger_level,
                        exit_level,
                        fixed,
                    )
                exit_level = fixed
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
        """Return broker *average fill* only — never LIMIT/trigger price."""
        if not order_id or order_id == "BOOK_FILLED":
            return None
        fill_keys = (
            "average_price",
            "averagePrice",
            "avg_price",
            "avgPrice",
            "tradedPrice",
            "traded_price",
        )

        def _avg_from_row(row: dict) -> float | None:
            for key in fill_keys:
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

        orders = getattr(self.broker, "_orders", None)
        if isinstance(orders, list):
            for o in orders:
                if str(o.get("order_id")) != str(order_id):
                    continue
                hit = _avg_from_row(o if isinstance(o, dict) else {})
                if hit is not None:
                    return hit
        get_book = getattr(self.broker, "get_orderbook", None)
        if callable(get_book):
            try:
                book = get_book()
            except Exception:
                book = None
            if book is not None:
                try:
                    rows = book.to_dict("records") if hasattr(book, "to_dict") else list(book)
                except Exception:
                    rows = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    rid = row.get("order_id") or row.get("orderId")
                    if str(rid) != str(order_id):
                        continue
                    hit = _avg_from_row(row)
                    if hit is not None:
                        return hit
        # Direct Kite history for this order id (most reliable after COMPLETE).
        hist = getattr(self.broker, "get_order_history", None)
        if callable(hist):
            try:
                rows = hist(str(order_id)) or []
            except Exception:
                rows = []
            for row in reversed(list(rows)):
                if not isinstance(row, dict):
                    continue
                hit = _avg_from_row(row)
                if hit is not None:
                    return hit
        get_one = getattr(self.broker, "_http", None)
        if get_one is not None:
            try:
                data = self.broker._http.request("GET", f"/orders/{order_id}")
                rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
                for row in reversed(list(rows)):
                    if not isinstance(row, dict):
                        continue
                    hit = _avg_from_row(row)
                    if hit is not None:
                        return hit
            except Exception:
                pass
        return None

    def _wait_fill_price(self, order_id: str | None, *, tries: int = 6, delay: float = 0.35) -> float | None:
        """Poll briefly for average fill after a marketable LIMIT punches."""
        if not order_id or order_id == "BOOK_FILLED":
            return None
        last: float | None = None
        for i in range(max(1, int(tries))):
            last = self._fill_price_from_order(order_id)
            if last is not None and float(last) > 0:
                return float(last)
            if i + 1 < tries:
                try:
                    time.sleep(max(0.05, float(delay)))
                except Exception:
                    pass
        return last


    def _quote_protect_ltp_kite(self, symbol: str) -> float | None:
        """ATO prod: Kite /quote/ltp only — skip Feeder peek for faster punch."""
        if not symbol:
            return None
        getter = getattr(self.broker, "get_ltp", None)
        if not callable(getter):
            return None
        try:
            try:
                prices = getter([str(symbol)], kite_only=True)
            except TypeError:
                prices = getter([str(symbol)])
        except Exception as exc:
            self.log.debug("ATO Kite protect LTP failed for %s: %s", symbol, exc)
            return None
        if not isinstance(prices, dict):
            return None
        raw = prices.get(symbol) or prices.get(str(symbol))
        if raw is None:
            tail = str(symbol).split(":")[-1]
            for k, v in prices.items():
                if str(k).split(":")[-1] == tail:
                    raw = v
                    break
        if raw is not None and float(raw) > 0:
            return float(raw)
        return None

    def _resolve_option_premium(
        self, symbol: str | None, order_id: str | None = None, *, spot: float | None = None
    ) -> float | None:
        """Live/UAT option premium: prefer DRISHTI audit, then order fill, then quote.

        Never invents synthetic premiums (old intrinsic+5 / 5.00 floor) — missing
        values stay None so SARANSH can show blank rather than fake Buy/Sell.
        """
        _ = spot  # call-site compatibility; audit uses market clock
        fill = self._fill_price_from_order(order_id)
        # UAT: prefer DRISHTI option_ltp audit (replay clock or live wall clock)
        # over sticky REST/fill prices — otherwise Buy/Sell collapse to the same
        # number (observed: entry fill 42.0 kept on exit while pe_protect≈37.85).
        try:
            from core.batman_mode import is_uat
            from core.option_ltp_uat_lookup import (
                lookup_protect_premium,
                replay_market_time_from_cache,
            )

            if is_uat(_ROOT) and symbol:
                replay_t = replay_market_time_from_cache(_ROOT)
                audit_px = lookup_protect_premium(
                    symbol=symbol,
                    root=_ROOT,
                    replay_market_time=replay_t,
                    day=replay_t,
                )
                if audit_px is not None and audit_px > 0:
                    return float(audit_px)
        except Exception as exc:
            self.log.debug("Option_ltp audit premium lookup failed: %s", exc)

        if fill is not None and float(fill) > 0 and abs(float(fill) - 5.0) > 1e-9:
            return fill
        if not symbol:
            return fill if fill is not None else None
        try:
            from core.batman_mode import is_uat

            in_uat = bool(is_uat(_ROOT))
        except Exception:
            in_uat = False

        # Prod: Kite REST only on ATO hot path (no Feeder 3s peek).
        # Never pass UAT fixture expiry into live quotes — 2026-08-04 resolved
        # to nothing and ATO halted with "needs option LTP".
        if not in_uat:
            raw = self._quote_protect_ltp_kite(str(symbol))
            if raw is not None and raw > 0:
                self.log.info("ATO option LTP via Kite REST (no Feeder) %s=%.2f", symbol, raw)
                return raw

        strike, opt = _parse_protect_strike_opt(symbol)
        if not strike or not opt:
            return fill if fill is not None else None
        if in_uat:
            try:
                from core.feeder_ipc import peek_option_quote

                q = peek_option_quote(strike=int(strike), option_type=str(opt), wait_seconds=1.2)
                if q and float(q.get("ltp") or 0) > 0:
                    return float(q["ltp"])
            except Exception as exc:
                self.log.debug("Feeder option premium failed for %s: %s", symbol, exc)

        getter = getattr(self.broker, "get_nifty_option_ltps", None)
        if callable(getter):
            try:
                expiry = None
                if in_uat:
                    try:
                        from core.nifty_option_expiry import fixture_expiry_date
                        from core.uat_positions import load_positions_fixture

                        expiry = fixture_expiry_date(load_positions_fixture(_ROOT))
                    except Exception:
                        expiry = None
                try:
                    prices = getter(
                        [(strike, opt)],
                        expiry_date=expiry,
                        kite_only=not in_uat,
                    )
                except TypeError:
                    prices = getter([(strike, opt)], expiry_date=expiry)
                raw = prices.get((strike, opt)) if isinstance(prices, dict) else None
                if raw is not None:
                    value = float(raw)
                    if value > 0:
                        return value
            except Exception as exc:
                self.log.debug("Option premium quote failed for %s: %s", symbol, exc)

        # UAT: try wall-clock audit once more before giving up (no synthetic floor).
        try:
            from core.batman_mode import is_uat
            from core.option_ltp_uat_lookup import lookup_protect_premium

            if is_uat(_ROOT) and symbol:
                audit_px = lookup_protect_premium(
                    symbol=symbol, root=_ROOT, replay_market_time=None
                )
                if audit_px is not None and audit_px > 0:
                    return float(audit_px)
        except Exception as exc:
            self.log.debug("Live option_ltp audit fallback failed: %s", exc)

        # Do not invent premiums (old intrinsic+5 / 5.00 floor) — SARANSH shows blank.
        return fill if fill is not None else None

    def _watch_ato_buy_fill_rescue(self, *, position_reader=None) -> None:
        """If parked BUY is still short and LTP ran +1 Rs, Rescue completes the BUY."""
        from core.ato_exec import remaining_qty, rescue_complete_buy, should_fill_rescue

        broker = self.broker
        om = getattr(self, "order_manager", None)
        if om is not None and getattr(om, "is_paper", False):
            return
        for tag in ("ce", "pe"):
            if not self.state.get(f"ato.{tag}_ato_active"):
                continue
            if self.state.get(f"ato.{tag}_ato_exit_order_id"):
                continue
            oid = self.state.get(f"ato.{tag}_buy_oid")
            trig = self.state.get(f"ato.{tag}_buy_trigger")
            qty = int(self.state.get(f"ato.{tag}_buy_qty") or 0)
            sym = self.state.get(f"ato.{tag}_protect_symbol")
            if not oid or not trig or qty <= 0 or not sym:
                continue
            ltp = None
            try:
                ltp = self._quote_protect_ltp_kite(str(sym))
            except Exception:
                ltp = None
            if not ltp:
                try:
                    ltp = self._resolve_option_premium(str(sym), None, spot=0.0)
                except Exception:
                    continue
            if not ltp:
                continue
            filled = 0
            try:
                from core.ato_book_validation import net_qty_for_symbol

                net = net_qty_for_symbol(broker, str(sym), position_reader=position_reader)
                filled = abs(int(net or 0))
            except Exception:
                filled = 0
            rem = remaining_qty(requested=qty, filled=filled)
            if not should_fill_rescue(trigger=float(trig), ltp=float(ltp), remaining_qty=rem):
                continue
            try:
                rescue_complete_buy(
                    broker,
                    symbol=str(sym),
                    remaining=rem,
                    ltp=float(ltp),
                    existing_oid=str(oid),
                )
                self.state.set(f"ato.{tag}_buy_oid", None, save=False)
                self.log.info("ATO %s BUY fill-Rescue remaining=%s ltp=%s", tag.upper(), rem, ltp)
            except Exception as exc:
                self.log.warning("ATO %s BUY fill-Rescue failed: %s", tag, exc)

    def _watch_ato_sell_exit_rescue(self, *, position_reader=None) -> None:
        """If an ATO SELL is still pending and we still hold the protect, flatten it."""
        from core.ato_exec import rescue_flatten_sell

        broker = self.broker
        om = getattr(self, "order_manager", None)
        if om is not None and getattr(om, "is_paper", False):
            return
        product = self.config.get("strategy.product_type", "MARGIN")
        for tag in ("ce", "pe"):
            oid = self.state.get(f"ato.{tag}_ato_exit_order_id")
            sym = self.state.get(f"ato.{tag}_protect_symbol")
            if not oid or not sym:
                continue
            try:
                from core.ato_book_validation import net_qty_for_symbol

                net = net_qty_for_symbol(broker, str(sym), position_reader=position_reader)
                held = max(0, int(net or 0))
            except Exception:
                continue
            if held <= 0:
                continue
            ltp = None
            try:
                ltp = self._quote_protect_ltp_kite(str(sym))
            except Exception:
                ltp = None
            if not ltp:
                try:
                    ltp = self._resolve_option_premium(str(sym), None, spot=0.0)
                except Exception:
                    ltp = None
            if not ltp:
                continue
            try:
                reg = int(self._registered_exit_qty(tag.upper(), f"{tag}_buy") or 0)
                sell_qty = min(held, reg) if reg > 0 else held
                if held > sell_qty:
                    self.log.warning(
                        "ATO %s SELL exit-Rescue capping qty held=%s registered=%s -> sell=%s",
                        tag.upper(),
                        held,
                        reg,
                        sell_qty,
                    )
                out = rescue_flatten_sell(
                    broker,
                    symbol=str(sym),
                    remaining=int(sell_qty),
                    ltp=float(ltp),
                    existing_oid=str(oid),
                    product=product,
                )
                new_id = str((out or {}).get("order_id") or oid)
                self.state.set(f"ato.{tag}_ato_exit_order_id", new_id)
                self.log.info(
                    "ATO %s SELL exit-Rescue remaining=%s ltp=%s id=%s",
                    tag.upper(),
                    sell_qty,
                    ltp,
                    new_id,
                )
            except Exception as exc:
                self.log.warning("ATO %s SELL exit-Rescue failed: %s", tag, exc)
                try:
                    from core.desk_alerts import emit_desk_alert

                    side = tag.upper()
                    emit_desk_alert(
                        severity="red",
                        category="ATO exit",
                        alert=f"{side} extra sell was rejected — not enough margin (looks like a second short).",
                        log=f"ATO {side} SELL exit-Rescue failed: {exc}",
                        side=side,
                    )
                except Exception:
                    pass


    def _signal_web_order_fill(self, *, side: str, kind: str, order_id: str) -> None:
        """Stamp batman_state so the web desk can play engage/exit on real fills."""
        if not side or not kind:
            return
        oid = str(order_id or "").strip()
        if not oid or oid in {"MANUAL_PRE_ALGO"}:
            return
        token = f"{side.upper()}|{kind}|{oid}|{utils.now_ist().isoformat()}"
        key = "ato.web_buy_fill_token" if kind == "buy" else "ato.web_sell_fill_token"
        try:
            self.state.set(key, token)
        except Exception as exc:
            self.log.debug("web fill token soft-failed: %s", exc)

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
        buy_premium = self._wait_fill_price(order_id)
        if buy_premium is None:
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
        self._record_side_entry_replay_time(side)
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
        # Desk audio: auto protect BUY after order path (book/fill already checked upstream)
        if str(entry_source or "") == "auto":
            self._signal_web_order_fill(side=side, kind="buy", order_id=str(order_id))

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

        buy_oid = str((entry or {}).get("buy_order_id") or "")
        # Always prefer live broker average fill over sticky limit/LTP snapshots.
        buy_premium = self._wait_fill_price(buy_oid) if buy_oid else None
        if buy_premium is None and entry and entry.get("buy_option_premium") is not None:
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
                buy_oid,
                spot=float(entry.get("buy_nifty_ltp") or spot),
            )

        sell_premium = self._wait_fill_price(order_id)
        if sell_premium is None:
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
        self._signal_web_order_fill(side=side, kind="sell", order_id=str(order_id))
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
                buy_timestamp_ist=row.get("buy_timestamp_ist") or None,
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
        """Compare deployment core legs against live broker positions.

        Only the iron-condor core 4 (pe_buy/pe_sell/ce_buy/ce_sell) are required.
        Margin / 35% dyn hedge legs are optional — they may be exited intentionally
        and must not clear deployment.confirmed on restart.
        """
        _CORE_ROLES = ("pe_buy", "pe_sell", "ce_buy", "ce_sell")
        try:
            broker_df = self.broker.get_positions()
        except Exception as exc:
            self.log.error("ATO restore: broker position fetch failed — %s", exc)
            positions = cast(dict[str, Any], dep.get("positions", {}))
            missing_legs = [
                {"role": role, **leg}
                for role in _CORE_ROLES
                if isinstance((leg := positions.get(role)), dict) and leg
            ]
            return [], missing_legs

        broker_symbols: set[str] = set()
        if broker_df is not None and not broker_df.empty:
            for _, row in broker_df.iterrows():
                sym = row.get("tradingSymbol") or row.get("tradingsymbol", "")
                if sym:
                    broker_symbols.add(sym)

        confirmed: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        positions = cast(dict[str, Any], dep.get("positions", {}))
        for role in _CORE_ROLES:
            leg = positions.get(role)
            if not leg:
                continue
            sym = leg.get("symbol", "")
            entry = {"role": role, **leg}
            (confirmed if sym in broker_symbols else missing).append(entry)
        return confirmed, missing

    def _check_managed_qty_mismatch(self, *, broker_df: Any = None) -> None:
        """Halt CE/PE independently when broker qty is below managed Batman legs."""
        if not self.state.get("deployment.confirmed", False):
            return
        if broker_df is None:
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
            try:
                from core.desk_alerts import emit_desk_alert

                emit_desk_alert(
                    severity="red",
                    category="Qty mismatch",
                    alert=f"{side} size on Kite does not match Kavach — that side is halted.",
                    log=f"{side} managed qty mismatch — halting side: {mismatches}",
                    side=str(side).upper(),
                )
            except Exception:
                pass
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

        # ── Step 2b: Adopt leftover protect on registered symbols (no second BUY)
        # Covers re-Register / restart when Nifty is not currently at breach but
        # the prior ATO long is still in the broker book.
        if (
            ce_sell
            and manage_sides in ("ce", "both")
            and ce_protect_symbol
            and not self.state.get("ato.ce_ato_active", False)
            and not is_side_halted(self.state, "CE")
        ):
            broker_ce_qty = self._position_qty(ce_protect_symbol)
            if broker_ce_qty > 0:
                self.log.warning(
                    "ATO startup scan: CE protect already long qty=%s (%s) — adopting (exit-only)",
                    broker_ce_qty,
                    ce_protect_symbol,
                )
                self._adopt_manual_ato(
                    "CE", ce_protect_symbol, broker_ce_qty, expected_ce_qty or broker_ce_qty, spot
                )

        if (
            pe_sell
            and manage_sides in ("pe", "both")
            and pe_protect_symbol
            and not self.state.get("ato.pe_ato_active", False)
            and not self.state.get("ato.pe_awaiting_clearance", False)
            and not is_side_halted(self.state, "PE")
        ):
            broker_pe_qty = self._position_qty(pe_protect_symbol)
            if broker_pe_qty > 0:
                self.log.warning(
                    "ATO startup scan: PE protect already long qty=%s (%s) — adopting (exit-only)",
                    broker_pe_qty,
                    pe_protect_symbol,
                )
                self._adopt_manual_ato(
                    "PE", pe_protect_symbol, broker_pe_qty, expected_pe_qty or broker_pe_qty, spot
                )

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

        adopt_oid = "MANUAL_PRE_ALGO"
        exit_qty = int(expected_qty) if int(expected_qty or 0) > 0 else int(broker_qty)
        if side == "CE":
            self.state.set("ato.ce_triggered", True)
            self.state.set("ato.ce_ato_active", True)
            self._begin_protect_entry_cycle("CE")
            if not self.state.get("ato.ce_order_id"):
                self.state.set("ato.ce_order_id", adopt_oid, save=False)
            self._set_registered_exit_qty("CE", exit_qty)
            self._ce_cycles = getattr(self, "_ce_cycles", 0) + 1
            protect_strike = self.state.get("ato.ce_protect_strike")
            self.events.publish(
                Event.ATO_CE_TRIGGERED,
                {
                    "symbol": symbol,
                    "qty": broker_qty,
                    "spot": spot,
                    "order_id": adopt_oid,
                    "ato_strike": protect_strike,
                    "adopted": True,
                },
            )
        else:  # PE
            self.state.set("ato.pe_triggered", True)
            self.state.set("ato.pe_ato_active", True)
            self._begin_protect_entry_cycle("PE")
            if not self.state.get("ato.pe_order_id"):
                self.state.set("ato.pe_order_id", adopt_oid, save=False)
            self._set_registered_exit_qty("PE", exit_qty)
            self._pe_cycles = getattr(self, "_pe_cycles", 0) + 1
            protect_strike = self.state.get("ato.pe_protect_strike")
            self.events.publish(
                Event.ATO_PE_TRIGGERED,
                {
                    "symbol": symbol,
                    "qty": broker_qty,
                    "spot": spot,
                    "order_id": adopt_oid,
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


    # Seconds to ignore empty-book "manual exit" after algo ATO BUY (fill lag).
    _PROTECT_ENTRY_GRACE_S = 30.0
    _PROTECT_ZERO_POLLS_FOR_HALT = 3

    def _begin_protect_entry_cycle(self, side: str) -> None:
        """Reset per-cycle seen/grace so prior-cycle flags cannot false-halt."""
        prefix = self._side_prefix(side)
        setattr(self, f"_{prefix}_protect_seen_at_broker", False)
        setattr(self, f"_{prefix}_protect_zero_streak", 0)
        setattr(
            self,
            f"_{prefix}_protect_entry_pending_until",
            time.monotonic() + float(self._PROTECT_ENTRY_GRACE_S),
        )
        # Allow sync again if a prior false halt latched this in-memory guard.
        setattr(self, f"_{prefix}_manual_exit_halted", False)

    def _protect_entry_pending(self, side: str) -> bool:
        prefix = self._side_prefix(side)
        until = float(getattr(self, f"_{prefix}_protect_entry_pending_until", 0.0) or 0.0)
        return time.monotonic() < until

    def _clear_protect_entry_pending(self, side: str) -> None:
        prefix = self._side_prefix(side)
        setattr(self, f"_{prefix}_protect_entry_pending_until", 0.0)

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
            broker_qty = int(sym_qty.get(symbol, 0) or 0)
            if broker_qty == 0 and sym_qty:
                upper = symbol.upper()
                for k, v in sym_qty.items():
                    if str(k).upper() == upper:
                        broker_qty = int(v or 0)
                        break
            if expected_qty <= 0 and broker_qty > 0:
                expected_qty = broker_qty
            seen_attr = f"_{prefix}_protect_seen_at_broker"
            streak_attr = f"_{prefix}_protect_zero_streak"
            if broker_qty > 0:
                setattr(self, seen_attr, True)
                setattr(self, streak_attr, 0)
                self._clear_protect_entry_pending(side)
            elif ato_active and bool(getattr(self, seen_attr, False)):
                setattr(self, streak_attr, int(getattr(self, streak_attr, 0) or 0) + 1)
            else:
                setattr(self, streak_attr, 0)
            protect_seen = bool(getattr(self, seen_attr, False))
            zero_streak = int(getattr(self, streak_attr, 0) or 0)
            entry_pending = self._protect_entry_pending(side)
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
                entry_pending=entry_pending,
                consecutive_zero_polls=zero_streak,
                min_zero_polls_for_halt=int(self._PROTECT_ZERO_POLLS_FOR_HALT),
            )
            if result is None:
                continue
            if result.action in ("fill_pending", "await_zero_confirm"):
                self.log.info(
                    "%s protect sync %s — broker=%d expected=%d seen=%s streak=%d pending=%s",
                    side,
                    result.action,
                    broker_qty,
                    expected_qty,
                    protect_seen,
                    zero_streak,
                    entry_pending,
                )
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
        sell_leg = self.state.get(sell_leg_key)
        sell_symbol = ""
        if isinstance(sell_leg, dict):
            sell_symbol = str(sell_leg.get("symbol") or "")
        if symbol and sell_symbol:
            from core.zerodha_instruments import nifty_expiry_key

            want = nifty_expiry_key(sell_symbol)
            got = nifty_expiry_key(str(symbol))
            if want and got and want != got:
                self.log.error(
                    "ATO protect %s expiry %s != Batman sell %s (%s) — rebuild from sell",
                    symbol,
                    got,
                    sell_symbol,
                    want,
                )
                symbol = None
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

        broker_df = None
        position_reader = None
        if self.broker is not None:
            try:
                broker_df = self.broker.get_positions()
                try:
                    from core.day_pnl_cache import refresh_hybrid_day_pnl

                    refresh_hybrid_day_pnl(broker=self.broker, force=True)
                except Exception:
                    pass
                position_reader = lambda df=broker_df: df
            except Exception as exc:
                self.log.debug("ATO position book prefetch failed: %s", exc)

        try:
            spot = self._resolve_nifty_spot()
            self._watch_ato_buy_fill_rescue(position_reader=position_reader)
            self._watch_ato_sell_exit_rescue(position_reader=position_reader)
        except Exception as exc:
            self.log.warning("ATO breach check skipped — LTP unavailable: %s", exc)
            self._consecutive_ltp_failures = getattr(self, "_consecutive_ltp_failures", 0) + 1
            self._maybe_alert_ltp_failures(self.config.get("ato", {}))
            return

        if self._should_skip_for_replay_jump() or self._in_replay_resync():
            return

        self._apply_resume_reevaluate_flags()

        if position_reader is not None:
            sym_qty, had_book_failure = read_positions_with_retry(
                self.broker,
                max_retries=1,
                position_reader=position_reader,
            )
        else:
            sym_qty, had_book_failure = self._read_symbol_qty_with_retry()
        if sym_qty is None:
            self._handle_unreadable_position_book()
            return
        if had_book_failure:
            self._handle_position_book_recovered()

        self._check_managed_qty_mismatch(broker_df=broker_df)

        manage_sides = self.state.get("ato.manage_sides", "both")

        ce_strike = int(cast(dict[str, Any], ce_sell).get("strike", 0)) if ce_sell else 0
        pe_strike = int(cast(dict[str, Any], pe_sell).get("strike", 0)) if pe_sell else 0
        ce_triggered = self.state.get("ato.ce_triggered", False)
        pe_triggered = self.state.get("ato.pe_triggered", False)
        ce_ato_active = self.state.get("ato.ce_ato_active", False)
        pe_ato_active = self.state.get("ato.pe_ato_active", False)
        ce_settings = self._side_settings("CE", ce_strike) if ce_sell else None
        pe_settings = self._side_settings("PE", pe_strike) if pe_sell else None
        ce_settings, pe_settings = self._apply_cross_side_level_gap(ce_settings, pe_settings)
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

        exited_ce_this_poll = False
        exited_pe_this_poll = False
        need_exit_polls = self._exit_confirm_polls()

        # ── Exits first (both sides) — then entries ───────────
        if (
            ce_sell
            and manage_sides in ("ce", "both")
            and ce_settings
            and not is_side_halted(self.state, "CE")
            and ce_ato_active
            and ce_strike
        ):
            if self._exit_blocked_by_replay_loop("CE"):
                self._ce_exit_streak = 0
            else:
                ce_exit_hit = bool(spot <= ce_settings["exit_level"])
                if ce_exit_hit:
                    self._ce_exit_streak = getattr(self, "_ce_exit_streak", 0) + 1
                else:
                    self._ce_exit_streak = 0
                if ce_exit_hit and self._ce_exit_streak >= need_exit_polls:
                    self.log.info(
                        "↩ CE RETRACE — Spot %s ≤ CE retrace exit %s "
                        "(confirmed %s/%s polls) → exiting ATO",
                        spot,
                        ce_settings["exit_level"],
                        self._ce_exit_streak,
                        need_exit_polls,
                    )
                    self._exit_ce_ato(float(spot), ce_strike, ce_settings)
                    exited_ce_this_poll = True
                    ce_ato_active = False
                    self._ce_exit_streak = 0
                elif ce_exit_hit:
                    self.log.info(
                        "CE retrace pending — Spot %s ≤ exit %s (%s/%s polls)",
                        spot,
                        ce_settings["exit_level"],
                        self._ce_exit_streak,
                        need_exit_polls,
                    )

        if (
            pe_sell
            and manage_sides in ("pe", "both")
            and pe_settings
            and not is_side_halted(self.state, "PE")
            and pe_ato_active
            and pe_strike
        ):
            if self._exit_blocked_by_replay_loop("PE"):
                self._pe_exit_streak = 0
            else:
                pe_exit_hit = bool(spot >= pe_settings["exit_level"])
                if pe_exit_hit:
                    self._pe_exit_streak = getattr(self, "_pe_exit_streak", 0) + 1
                else:
                    self._pe_exit_streak = 0
                if pe_exit_hit and self._pe_exit_streak >= need_exit_polls:
                    self.log.info(
                        "↩ PE RETRACE — Spot %s ≥ PE retrace exit %s "
                        "(confirmed %s/%s polls) → exiting ATO",
                        spot,
                        pe_settings["exit_level"],
                        self._pe_exit_streak,
                        need_exit_polls,
                    )
                    self._exit_pe_ato(float(spot), pe_strike, pe_settings)
                    exited_pe_this_poll = True
                    pe_ato_active = False
                    self._pe_exit_streak = 0
                elif pe_exit_hit:
                    self.log.info(
                        "PE retrace pending — Spot %s ≥ exit %s (%s/%s polls)",
                        spot,
                        pe_settings["exit_level"],
                        self._pe_exit_streak,
                        need_exit_polls,
                    )

        # ── CE entry ─────────────────────────────────────────
        if (
            ce_sell
            and manage_sides in ("ce", "both")
            and ce_settings
            and not is_side_halted(self.state, "CE")
        ):
            ce_breach = bool(ce_strike and spot >= ce_settings["trigger_level"])
            ce_has_long_protect = ce_book_qty > 0
            if (
                ce_breach
                and not ce_has_long_protect
                and not self.state.get("ato.ce_awaiting_clearance", False)
                and (not ce_triggered or (ce_triggered and not ce_ato_active))
                and not exited_pe_this_poll
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
                try:
                    from core.desk_alerts import emit_desk_alert

                    emit_desk_alert(
                        severity="orange",
                        category="ATO trigger",
                        alert="Nifty hit the CE trigger — Kavach is buying CE protect.",
                        log=f"CE {label} — Spot {spot} >= CE trigger {ce_settings['trigger_level']} -> entering ATO",
                        side="CE",
                    )
                except Exception:
                    pass
                self._place_ce_protection(ce_strike, float(spot), ce_settings, trigger_reason)
            elif ce_breach and ce_has_long_protect and not ce_ato_active:
                self.log.warning(
                    "CE breach — long protect already in book qty=%s (%s) — adopting (no second BUY)",
                    ce_book_qty,
                    ce_protect_sym,
                )
                self._adopt_manual_ato(
                    "CE",
                    str(ce_protect_sym),
                    int(ce_book_qty),
                    self._ato_qty("ce_buy") or int(ce_book_qty),
                    float(spot),
                )
                ce_ato_active = True
                ce_triggered = True

        # ── PE entry (never same poll as CE exit — mid-box flip) ─
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
                and not exited_ce_this_poll
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
                try:
                    from core.desk_alerts import emit_desk_alert

                    emit_desk_alert(
                        severity="orange",
                        category="ATO trigger",
                        alert="Nifty hit the PE trigger — Kavach is buying PE protect.",
                        log=f"PE {label} — Spot {spot} <= PE trigger {pe_settings['trigger_level']} -> entering ATO",
                        side="PE",
                    )
                except Exception:
                    pass
                self._place_pe_protection(pe_strike, float(spot), pe_settings, trigger_reason)
            elif (
                pe_breach
                and not pe_has_long_protect
                and exited_ce_this_poll
            ):
                self.log.info(
                    "PE entry deferred — CE exited this poll at spot=%s "
                    "(avoid mid-box CE→PE flip); PE trigger=%s",
                    spot,
                    pe_settings["trigger_level"],
                )
            elif pe_breach and pe_has_long_protect and not pe_ato_active:
                self.log.warning(
                    "PE breach — long protect already in book qty=%s (%s) — adopting (no second BUY)",
                    pe_book_qty,
                    pe_protect_sym,
                )
                self._adopt_manual_ato(
                    "PE",
                    str(pe_protect_sym),
                    int(pe_book_qty),
                    self._ato_qty("pe_buy") or int(pe_book_qty),
                    float(spot),
                )
                pe_ato_active = True
                pe_triggered = True

        # Re-read book only after entry/exit this tick — a blind second REST call can
        # briefly return empty and wipe qty before mid-session adopt (26A).
        if exited_ce_this_poll or exited_pe_this_poll:
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
            self._begin_protect_entry_cycle("CE")
            self._set_registered_exit_qty("CE", ato_qty)
            self._record_side_entry_replay_time("CE")
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
                self._begin_protect_entry_cycle("CE")
                self._set_registered_exit_qty("CE", ato_qty)
                self._record_side_entry_replay_time("CE")
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
        self._begin_protect_entry_cycle("CE")
        self._set_registered_exit_qty("CE", ato_qty)
        self.state.set("ato.ce_ato_exit_order_id", None, save=False)
        self._ce_cycles = getattr(self, "_ce_cycles", 0) + 1
        self._maybe_soft_cap_warn("CE", spot)
        self._maybe_exit_dyn_hedge("CE")
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
            self._begin_protect_entry_cycle("PE")
            self._set_registered_exit_qty("PE", ato_qty)
            self._record_side_entry_replay_time("PE")
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
                self._begin_protect_entry_cycle("PE")
                self._set_registered_exit_qty("PE", ato_qty)
                self._record_side_entry_replay_time("PE")
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
        self._begin_protect_entry_cycle("PE")
        self._set_registered_exit_qty("PE", ato_qty)
        self.state.set("ato.pe_ato_exit_order_id", None, save=False)
        self._pe_cycles = getattr(self, "_pe_cycles", 0) + 1
        self._maybe_soft_cap_warn("PE", spot)
        self._maybe_exit_dyn_hedge("PE")
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
            self.state.set("ato.ce_entry_replay_market_time", None)
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
            self.state.set("ato.ce_entry_replay_market_time", None)
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
            self.state.set("ato.pe_entry_replay_market_time", None)
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
            self.state.set("ato.pe_entry_replay_market_time", None)
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

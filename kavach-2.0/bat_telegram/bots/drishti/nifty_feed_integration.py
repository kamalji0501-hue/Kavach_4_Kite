"""DRISHTI wiring for the reusable NIFTY REST LTP feed module."""

from __future__ import annotations

import asyncio
import html
import logging
import zoneinfo
from datetime import datetime
from pathlib import Path

from telegram.constants import ParseMode
from telegram.ext import Application, ContextTypes

from bat_telegram.incident_publisher import publish_incident, resolve_incident
from core.algo_control import is_algo_paused, pause_algo, resume_algo
from core.bot_logging import (
    bot_nifty_ltp_log_dir,
    bot_nifty_rest_ltp_log_dir,
    bot_nifty_websocket_ltp_log_dir,
    bot_option_ltp_log_dir,
)
from core.feed_recovery import (
    ALERT_INTERVAL_SECONDS,
    LABEL_AUTO_RESUME,
    LABEL_MANUAL_HANDLING,
    OWNER_DRISHTI,
    OWNER_OPERATOR,
    can_auto_resume_feed_recovery,
    clear_feed_degraded,
    clear_recovery_at_eod,
    feed_incident_severity,
    get_recovery_owner,
    is_feed_degraded,
    is_nifty_cache_trading_ready,
    is_transport_cycle_exhausted,
    mark_feed_degraded,
    record_transport_switch,
    set_recovery_owner,
    should_notify_kavach_resume_ready,
    should_notify_operator_feed_ready,
    should_send_degraded_status_alert,
    should_send_recovery_alert,
    try_session_open_auto_resume,
    update_feed_ready_stability,
)
from core.gift_nifty_ltp import (
    GIFT_NIFTY_DISPLAY_NAME,
    GIFT_NIFTY_SYMBOL,
    append_gift_nifty_audit_log,
    fetch_gift_nifty_ltp_rest_with_retry,
    read_gift_nifty_cache,
    seed_gift_nifty_cache,
)
from core.gift_nifty_probe import GiftNiftyProbeService, is_gift_probe_running
from core.kavach_telegram import send_kavach_html
from core.nifty_ltp import fetch_nifty_ltp_websocket
from core.nifty_ltp_failover import (
    active_transport_label,
    cache_transport_label,
    get_failover_state,
    is_failover_eligible,
    live_transport_label,
    resolve_active_transport,
    save_failover_state,
    try_websocket_retry_after_rest,
)
from core.nifty_ltp_feed import (
    DEFAULT_REST_STALE_CRITICAL_SECONDS,
    DEFAULT_WEBSOCKET_STALE_CRITICAL_SECONDS,
    FEED_MODE_REST,
    FEED_MODE_WEBSOCKET,
    POLL_INTERVAL_OPTIONS,
    NiftyLtpCacheSnapshot,
    NiftyLtpFeedConfig,
    NiftyLtpFeedService,
    allowed_user_ping_critical_options,
    allowed_user_ping_warning_options,
    append_nifty_ltp_audit_log,
    default_config_path,
    feed_freshness_floor_seconds,
    is_nifty_feed_task_running,
    is_nse_market_session,
    load_feed_config,
    read_nifty_ltp_cache,
    save_feed_config,
    write_nifty_ltp_cache,
)
from core.nifty_ltp_uat_replay import (
    UAT_LOG_TAG,
    NiftyLtpUatReplayService,
    UatReplayProgress,
    build_uat_replay_service,
    format_clock_ampm,
    format_uat_time_block,
    is_drishti_uat_replay_window,
    is_uat_replay_task_running,
    load_uat_replay_config_from_params,
)
from core.nifty_ltp_validation import resolve_user_ping_thresholds
from core.nifty_ltp_websocket_feed import NiftyLtpWebSocketFeedService
from core.token_store import TokenStore
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update

logger = logging.getLogger("batman.drishti.feed")

_CB_FEED = "drishti_feed"
_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]

_FEED_BLOCK_KEY = "nifty_feed_block_reason"
_UAT_REPLAY_SERVICE_KEY = "nifty_ltp_uat_replay_service"
_UAT_NOTIFY_STATE_KEY = "drishti_uat_notify_state"


def nifty_feed_token_block_reason(token_store) -> str | None:
    """Why live NIFTY feed cannot start — None when token is usable."""
    tok, _ = token_store.load()
    if not tok:
        return "No Dhan token — tap Update Token to start live feed"
    if token_store.is_effectively_expired():
        return "Token expired — tap Update Token to start live feed"
    return None


def _nifty_audit_log_dir() -> Path:
    return bot_nifty_ltp_log_dir(_WORKSPACE_ROOT)


async def _report_stale_cache_on_user_ping(
    *,
    assessment,
    context: ContextTypes.DEFAULT_TYPE,
    live_ltp: float | None = None,
) -> None:
    if not assessment.should_report_incident:
        return
    chat_id = str(context.bot_data.get("chat_id") or "")
    stale = assessment.stale_cache_ltp
    age = assessment.cache_age_seconds
    msg = (
        f"Cached ₹{stale:,.2f} was {age:.0f}s old when operator requested NIFTY LTP."
        if stale is not None
        else f"Cache missing/stale (age {age:.0f}s) on operator NIFTY LTP ping."
    )
    if live_ltp is not None:
        msg += f" Live fetch returned ₹{live_ltp:,.2f}."
    await publish_incident(
        source="drishti",
        scenario="nifty_ltp_stale_cache",
        severity="critical",
        category="connectivity",
        title="NIFTY LTP cache too old on user ping",
        error_message=msg,
        next_action="Check DRISHTI feed, token, and Dhan API. Verify logs/runtime/…/drishti/logs/nifty_ltp/",
        source_bot=context.bot,
        source_chat_id=chat_id or None,
    )


def feed_callback_prefix() -> str:
    return _CB_FEED


def build_default_feed_config(params: dict | None = None) -> NiftyLtpFeedConfig:
    """Operator defaults from ``params.json`` → ``NiftyLtpFeedConfig``."""
    feed_params = (params or {}).get("nifty_ltp_feed") or {}
    return NiftyLtpFeedConfig(
        feed_mode=str(feed_params.get("default_feed_mode", FEED_MODE_WEBSOCKET)),
        poll_interval_seconds=int(feed_params.get("default_poll_interval_seconds", 2)),
        stale_price_alert_seconds=int(feed_params.get("default_stale_price_alert_seconds", 10)),
        user_ping_warning_age_seconds=int(
            feed_params.get("default_user_ping_warning_age_seconds", 15)
        ),
        user_ping_critical_age_seconds=int(
            feed_params.get("default_user_ping_critical_age_seconds", 60)
        ),
        fetch_failure_jagran_threshold=int(feed_params.get("fetch_failure_jagran_threshold", 5)),
        rest_max_attempts=int(feed_params.get("rest_max_attempts", 3)),
        rest_retry_base_seconds=float(feed_params.get("rest_retry_base_seconds", 1.0)),
        rest_retry_backoff_multiplier=float(feed_params.get("rest_retry_backoff_multiplier", 2.0)),
        rate_limit_cooldown_seconds=float(feed_params.get("rate_limit_cooldown_seconds", 30.0)),
        websocket_startup_grace_seconds=int(
            feed_params.get("websocket_startup_grace_seconds", 30)
        ),
    )


def ensure_default_feed_config(params: dict | None = None) -> tuple[NiftyLtpFeedConfig, bool]:
    """Return feed config, creating ``data/nifty_ltp_feed_config.json`` if missing."""
    existing = load_feed_config()
    if existing is not None:
        return existing, False
    cfg = build_default_feed_config(params)
    save_feed_config(cfg)
    logger.info("Created default NIFTY LTP feed config at %s", default_config_path())
    return cfg, True


def mark_ltp_cache_unhealthy(*, reason: str) -> None:
    """Write cache as unhealthy while preserving last known LTP if any."""
    snap = read_nifty_ltp_cache()
    now = datetime.now(_IST)
    write_nifty_ltp_cache(
        NiftyLtpCacheSnapshot(
            ltp=float(snap.ltp if snap else 0.0),
            updated_at=now.isoformat(),
            last_changed_at=(snap.last_changed_at if snap else now.isoformat()),
            source="dhan_rest",
            feed_healthy=False,
            poll_interval_seconds=int(snap.poll_interval_seconds if snap else 2),
            consecutive_failures=int(snap.consecutive_failures if snap else 0),
        )
    )
    logger.info("NIFTY LTP cache marked unhealthy: %s", reason)


def deactivate_ltp_feed(app: Application) -> None:
    """Stop background poller and mark shared cache unhealthy."""
    stop_nifty_feed(app)
    stop_uat_market_replay(app)
    mark_ltp_cache_unhealthy(reason="token_deactivated")


async def feed_watchdog_loop(app: Application, token_store: TokenStore) -> None:
    """Restart the REST poller if its asyncio task dies or stops unexpectedly."""
    while True:
        await asyncio.sleep(60)
        try:
            if load_feed_config() is None:
                continue
            service = app.bot_data.get("nifty_ltp_feed_service")
            needs_restart = not is_background_feed_running(app)
            if (
                isinstance(
                    service,
                    (NiftyLtpFeedService, NiftyLtpWebSocketFeedService),
                )
                and service._task is not None
            ):
                task = service._task
                if task.done() and not task.cancelled():
                    exc = task.exception()
                    logger.warning("NIFTY feed task exited: %s", exc)
                    needs_restart = True
            if needs_restart:
                block = nifty_feed_token_block_reason(token_store)
                if block:
                    app.bot_data[_FEED_BLOCK_KEY] = block
                    continue
                logger.warning("NIFTY feed watchdog — restarting poller")
                restart_nifty_feed(app, token_store)
                chat_id = str(app.bot_data.get("chat_id") or "")
                if chat_id:
                    try:
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=(
                                "🔄 <b>NIFTY LTP feed restarted</b>\n"
                                "Background poller recovered automatically."
                            ),
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception as exc:
                        logger.warning("Feed watchdog Telegram notice failed: %s", exc)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("NIFTY feed watchdog error: %s", exc)


class DrishtiFeedHooks:
    """JAGRAN + local alert hooks for NIFTY feed services (incl. WS↔REST failover)."""

    def __init__(self, app: Application, chat_id: str, token_store: TokenStore) -> None:
        self._app = app
        self._chat_id = chat_id
        self._token_store = token_store

    def _failover(self) -> NiftyFeedFailoverController:
        key = "nifty_failover_controller"
        ctrl = self._app.bot_data.get(key)
        if not isinstance(ctrl, NiftyFeedFailoverController):
            ctrl = NiftyFeedFailoverController(self._app, self._token_store)
            self._app.bot_data[key] = ctrl
        return ctrl

    async def on_auth_failure(self, *, error: str) -> None:
        """JWT rejected — block feed; do not WS↔REST failover or ATO pause."""
        self._app.bot_data[_FEED_BLOCK_KEY] = (
            "Dhan rejected the access token — tap Update Token with a fresh JWT"
        )
        try:
            await self._app.bot.send_message(
                chat_id=self._chat_id,
                text=(
                    "🔴 <b>Dhan token rejected</b>\n\n"
                    f"<code>{html.escape(error[:200])}</code>\n\n"
                    "Live NIFTY feed paused. Paste a fresh JWT via <b>Update Token</b>."
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            logger.warning("DRISHTI auth-failure alert failed: %s", exc)
        await publish_incident(
            source="drishti",
            scenario="dhan_auth_failure",
            severity=feed_incident_severity("critical"),
            category="connectivity",
            title="Dhan access token rejected",
            error_message=error[:500],
            next_action="Paste a fresh JWT via DRISHTI Update Token.",
            source_bot=self._app.bot,
            source_chat_id=self._chat_id or None,
        )

    async def on_fetch_failure(self, *, failures: int, threshold: int, error: str) -> None:
        from core.nifty_ltp import is_auth_error

        if is_auth_error(error):
            await self.on_auth_failure(error=error)
            return
        cfg = load_feed_config()
        if is_failover_eligible(cfg):
            transport = resolve_active_transport(cfg, self._app.bot_data)
            if transport == "websocket":
                await self._failover().on_websocket_crash(
                    f"WebSocket connection errors ({failures}/{threshold}): {error}"
                )
                return
            await self._failover().on_rest_failure(
                f"REST errors ({failures}/{threshold}): {error}"
            )
            return
        await self._legacy_fetch_failure(failures=failures, threshold=threshold, error=error)

    async def _legacy_fetch_failure(self, *, failures: int, threshold: int, error: str) -> None:
        try:
            await self._app.bot.send_message(
                chat_id=self._chat_id,
                text=(f"⚠️ NIFTY LTP feed failed ({failures}/{threshold})\n" f"{error}"),
            )
        except Exception as exc:
            logger.warning("DRISHTI local feed alert failed: %s", exc)

        await publish_incident(
            source="drishti",
            scenario="ltp_fetch_failure",
            severity=feed_incident_severity("critical"),
            category="connectivity",
            title="NIFTY LTP feed failure",
            error_message=f"Failed after {failures} consecutive attempts: {error}",
            next_action=("ATO auto-paused. Fix token/Dhan feed, then tap Resume on KAVACH."),
            source_bot=self._app.bot,
            source_chat_id=self._chat_id,
        )
        pause_algo(reason="nifty_ltp_feed_failure", paused_by="drishti")
        try:
            await self._app.bot.send_message(
                chat_id=self._chat_id,
                text="⏸ <b>ATO auto-paused</b> — NIFTY LTP feed failed repeatedly.\n"
                "Fix the issue, then tap <b>Resume</b> on KAVACH.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            logger.warning("DRISHTI auto-pause notice failed: %s", exc)

    async def on_fetch_recovered(self) -> None:
        await self._failover().on_feed_healthy()
        await resolve_incident(
            source="drishti",
            scenario="ltp_fetch_failure",
            resolution_message="NIFTY LTP feed has recovered.",
            source_bot=self._app.bot,
            source_chat_id=self._chat_id,
        )

    async def on_feed_stale(self, *, age_seconds: float, threshold: float, error: str) -> None:
        cfg = load_feed_config()
        if is_failover_eligible(cfg) and resolve_active_transport(cfg, self._app.bot_data) == "websocket":
            await self._failover().on_websocket_crash(
                f"No feed refresh for {age_seconds:.0f}s (limit {threshold:.0f}s): {error}"
            )
            return
        try:
            await self._app.bot.send_message(
                chat_id=self._chat_id,
                text=(
                    f"🔴 NIFTY feed stale — no refresh for {age_seconds:.0f}s "
                    f"(limit {threshold:.0f}s)\n{error}"
                ),
            )
        except Exception as exc:
            logger.warning("DRISHTI feed-stale local alert failed: %s", exc)

        await publish_incident(
            source="drishti",
            scenario="nifty_ltp_stale_cache",
            severity=feed_incident_severity("critical"),
            category="connectivity",
            title="NIFTY LTP feed not refreshing",
            error_message=error,
            next_action=(
                "Check WebSocket/REST log under drishti/logs/nifty_websocket_ltp or "
                "nifty_rest_ltp. Fix token/Dhan feed, then Resume on KAVACH."
            ),
            source_bot=self._app.bot,
            source_chat_id=self._chat_id,
        )
        pause_algo(reason="nifty_ltp_feed_stale", paused_by="drishti")

    async def on_feed_stale_cleared(self) -> None:
        update_feed_ready_stability(ready=False)
        await resolve_incident(
            source="drishti",
            scenario="nifty_ltp_stale_cache",
            resolution_message="NIFTY LTP feed is refreshing again.",
            source_bot=self._app.bot,
            source_chat_id=self._chat_id,
        )

    async def on_stale_price(self, *, ltp: float, unchanged_seconds: float, threshold: int) -> None:
        try:
            await self._app.bot.send_message(
                chat_id=self._chat_id,
                text=(
                    f"⚠️ NIFTY price unchanged for {unchanged_seconds:.0f}s "
                    f"(limit {threshold}s)\n"
                    f"Last LTP: ₹{ltp:,.2f}\n"
                    "Possible stale broker feed — check DRISHTI / Dhan."
                ),
            )
        except Exception as exc:
            logger.warning("DRISHTI stale-price local alert failed: %s", exc)

        await publish_incident(
            source="drishti",
            scenario="nifty_ltp_stale_price",
            severity=feed_incident_severity("critical"),
            category="connectivity",
            title="NIFTY LTP price stagnant",
            error_message=(
                f"Price ₹{ltp:,.2f} unchanged for {unchanged_seconds:.0f}s "
                f"(threshold {threshold}s)."
            ),
            next_action=("ATO auto-paused. Verify Dhan feed/VPS, then tap Resume on KAVACH."),
            source_bot=self._app.bot,
            source_chat_id=self._chat_id,
        )
        pause_algo(
            reason="nifty_ltp_stale_price",
            paused_by="drishti",
        )
        try:
            await self._app.bot.send_message(
                chat_id=self._chat_id,
                text=(
                    "⏸ <b>ATO auto-paused</b> — NIFTY price unchanged for "
                    f"{unchanged_seconds:.0f}s.\n"
                    "When feed is healthy, tap <b>Resume</b> on KAVACH."
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            logger.warning("DRISHTI auto-pause notice failed: %s", exc)

    async def on_stale_price_cleared(self, *, ltp: float) -> None:
        await resolve_incident(
            source="drishti",
            scenario="nifty_ltp_stale_price",
            resolution_message=f"NIFTY LTP moving again — last ₹{ltp:,.2f}.",
            source_bot=self._app.bot,
            source_chat_id=self._chat_id,
        )
        try:
            await self._app.bot.send_message(
                chat_id=self._chat_id,
                text=(
                    "✅ NIFTY feed moving again "
                    f"(₹{ltp:,.2f}). ATO remains paused — tap "
                    "<b>Resume</b> on KAVACH when ready."
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            logger.warning("DRISHTI stale-clear notice failed: %s", exc)


def feed_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⚡ WebSocket (in-process)",
                    callback_data=f"{_CB_FEED}:mode:{FEED_MODE_WEBSOCKET}",
                )
            ],
            [
                InlineKeyboardButton(
                    "📡 REST",
                    callback_data=f"{_CB_FEED}:mode:{FEED_MODE_REST}",
                )
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_FEED}:cancel")],
        ]
    )


def feed_poll_keyboard() -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(f"{v}s", callback_data=f"{_CB_FEED}:poll:{v}")
        for v in POLL_INTERVAL_OPTIONS
    ]
    return InlineKeyboardMarkup(
        [
            row,
            [InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_FEED}:cancel")],
        ]
    )


def feed_stale_keyboard() -> InlineKeyboardMarkup:
    """Step 3 options — same intervals as poll (1s / 2s / 3s / 5s)."""
    row = [
        InlineKeyboardButton(f"{v}s", callback_data=f"{_CB_FEED}:stale:{v}")
        for v in POLL_INTERVAL_OPTIONS
    ]
    return InlineKeyboardMarkup(
        [
            row,
            [InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_FEED}:cancel")],
        ]
    )


def feed_ping_warning_keyboard(
    poll_interval_seconds: int,
    *,
    feed_mode: str = FEED_MODE_REST,
) -> InlineKeyboardMarkup:
    opts = allowed_user_ping_warning_options(poll_interval_seconds, feed_mode=feed_mode)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for value in opts:
        row.append(InlineKeyboardButton(f"{value}s", callback_data=f"{_CB_FEED}:ping_warn:{value}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_FEED}:cancel")])
    return InlineKeyboardMarkup(rows)


def feed_ping_critical_keyboard(warning_seconds: int) -> InlineKeyboardMarkup:
    opts = allowed_user_ping_critical_options(warning_seconds)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for value in opts:
        row.append(InlineKeyboardButton(f"{value}s", callback_data=f"{_CB_FEED}:ping_crit:{value}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_FEED}:cancel")])
    return InlineKeyboardMarkup(rows)


def stop_nifty_feed(app: Application) -> None:
    service = app.bot_data.get("nifty_ltp_feed_service")
    if isinstance(service, (NiftyLtpFeedService, NiftyLtpWebSocketFeedService)):
        service.stop()
    gift = app.bot_data.get("gift_nifty_probe_service")
    if isinstance(gift, GiftNiftyProbeService):
        gift.stop()
    from core.option_ltp_feed import stop_option_ltp_audit

    stop_option_ltp_audit(app.bot_data)


def stop_uat_market_replay(app: Application, *, notify: bool = True) -> None:
    """Stop UAT tick replay if running (does not touch live WS/REST services)."""
    service = app.bot_data.get(_UAT_REPLAY_SERVICE_KEY)
    if isinstance(service, NiftyLtpUatReplayService):
        if not notify:
            service.on_stopped = None
            service._started_notified = False
        service.stop()
    app.bot_data.pop(_UAT_REPLAY_SERVICE_KEY, None)


def is_uat_market_replay_running(app: Application | None) -> bool:
    if app is None:
        return False
    return is_uat_replay_task_running(app.bot_data.get(_UAT_REPLAY_SERVICE_KEY))


def get_uat_replay_progress(app: Application | None = None) -> UatReplayProgress | None:
    """Last emitted tick's LTP + market timestamp (exact pair written to cache)."""
    if app is None:
        return None
    service = app.bot_data.get(_UAT_REPLAY_SERVICE_KEY)
    if not isinstance(service, NiftyLtpUatReplayService):
        return None
    return service.progress_snapshot()


def format_uat_dashboard_html(app: Application | None = None) -> str:
    """Operator-facing UAT Market Replay card (Telegram, no commands needed)."""
    now = datetime.now(_IST)
    params = app.bot_data.get("params") if app is not None else None
    cfg = load_uat_replay_config_from_params(params if isinstance(params, dict) else None)
    snap = read_nifty_ltp_cache()
    running = is_uat_market_replay_running(app)
    progress = get_uat_replay_progress(app)
    uat_svc = app.bot_data.get(_UAT_REPLAY_SERVICE_KEY) if app is not None else None
    source_name = (
        uat_svc.source_file.name
        if isinstance(uat_svc, NiftyLtpUatReplayService)
        else "—"
    )

    lines = [
        f"{UAT_LOG_TAG} <b>Market Replay</b>",
        f"<code>{html.escape(now.strftime('%d-%b-%Y %H:%M:%S IST'))}</code>",
        "",
    ]
    if progress is not None:
        lines.append(f"<b>Nifty LTP</b>   ₹{progress.ltp:,.2f}")
        lines.append("")
        lines.append(html.escape(format_uat_time_block(progress)))
    elif snap and snap.ltp > 0:
        lines.append(f"<b>Nifty LTP</b>   ₹{snap.ltp:,.2f}")
        lines.append("Replay Market Time: — (waiting for first tick)")
        lines.append(f"Current Time:       {html.escape(now.strftime('%I:%M:%S %p').lstrip('0'))}")
        lines.append(f"Replay Speed:       {html.escape(cfg.speed_multiplier_label())}")
    else:
        lines.append("<b>Nifty LTP</b>   warming up…")
    lines.extend(
        [
            "",
            f"Status        {'🟢 Active' if running else '⚪ Idle'}",
            f"Source        <code>{html.escape(source_name)}</code>",
            f"Loop          {'On' if cfg.loop else 'Off'}",
            f"Window        {cfg.window_start.strftime('%H:%M')} → {cfg.window_end.strftime('%H:%M')} IST",
            "",
            "<i>Tap <b>Nifty LTP</b> anytime for a fresh reading. "
            "Live Price is paused in UAT mode.</i>",
        ]
    )
    return "\n".join(lines)


def uat_speed_keyboard() -> InlineKeyboardMarkup:
    """One-tap replay speed controls for operators."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Realtime", callback_data=f"{_CB_FEED}:uat_speed:realtime"),
                InlineKeyboardButton("Fast", callback_data=f"{_CB_FEED}:uat_speed:fast"),
                InlineKeyboardButton("Ultra", callback_data=f"{_CB_FEED}:uat_speed:ultra"),
            ],
            [
                InlineKeyboardButton("« Back", callback_data="drishti_menu:ping"),
            ],
        ]
    )


def uat_button_disabled_message(feature: str) -> str:
    return (
        f"{UAT_LOG_TAG} <b>Feature unavailable in UAT mode</b>\n\n"
        f"<b>{html.escape(feature)}</b> assumes a live broker quote.\n"
        "Use <b>Nifty LTP</b> / <b>NIFTY Status</b> for the replayed shared cache.\n"
        "Live Dhan quotes resume automatically during NSE hours (09:15–15:30 IST)."
    )


async def _send_uat_telegram(app: Application, text: str) -> None:
    chat_id = str(app.bot_data.get("chat_id") or "")
    if not chat_id:
        return
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.warning("%s Telegram notice failed: %s", UAT_LOG_TAG, exc)


def _queue_uat_notify(app: Application, event: str, body: str) -> None:
    """Send immediately when a loop is running; otherwise queue for the watchdog."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pending = app.bot_data.get(_UAT_NOTIFY_STATE_KEY)
        if not isinstance(pending, list):
            pending = []
        pending.append({"event": event, "body": body})
        app.bot_data[_UAT_NOTIFY_STATE_KEY] = pending
        return
    loop.create_task(_send_uat_telegram(app, body), name=f"drishti_uat_notify_{event}")


async def _flush_uat_notify(app: Application) -> None:
    pending = app.bot_data.get(_UAT_NOTIFY_STATE_KEY)
    if not isinstance(pending, list) or not pending:
        return
    app.bot_data[_UAT_NOTIFY_STATE_KEY] = []
    for item in pending:
        body = str((item or {}).get("body") or "")
        if body:
            await _send_uat_telegram(app, body)


def start_uat_market_replay(app: Application) -> bool:
    """Start UAT replay into the shared NIFTY cache. Returns True if started."""
    from core.market_data_provider import describe_mode_for_logs

    stop_uat_market_replay(app, notify=False)
    params = app.bot_data.get("params") if app.bot_data else None
    cfg = load_uat_replay_config_from_params(params if isinstance(params, dict) else None)
    logger.info("%s", describe_mode_for_logs(cfg))
    if not cfg.enabled:
        logger.info("%s Disabled in params — not starting", UAT_LOG_TAG)
        return False
    if not is_drishti_uat_replay_window(config=cfg):
        logger.info("%s Outside UAT window — not starting", UAT_LOG_TAG)
        return False

    from core.utils import is_trading_day

    started_at = datetime.now(_IST)

    def _on_started() -> None:
        service = app.bot_data.get(_UAT_REPLAY_SERVICE_KEY)
        source_name = (
            service.source_file.name
            if isinstance(service, NiftyLtpUatReplayService)
            else "unknown"
        )
        source_path = (
            str(service.source_file)
            if isinstance(service, NiftyLtpUatReplayService)
            else "unknown"
        )
        tick_count = (
            len(service.ticks) if isinstance(service, NiftyLtpUatReplayService) else 0
        )
        logger.info(
            "%s MODE ACTIVATED — Source File = %s tick_count=%s speed=%s",
            UAT_LOG_TAG,
            source_path,
            tick_count,
            cfg.replay_speed,
        )
        _queue_uat_notify(
            app,
            "activated",
            (
                f"<b>DRISHTI UAT MODE ACTIVATED</b>\n\n"
                f"{UAT_LOG_TAG}\n"
                f"Source file: <code>{html.escape(source_name)}</code>\n"
                f"Replay speed: <b>{html.escape(cfg.speed_label())}</b>\n"
                f"Tick count: <code>{tick_count}</code>\n"
                f"Start: <code>{started_at.strftime('%d-%b-%Y %H:%M:%S IST')}</code>\n"
                f"force_uat_mode: <code>{cfg.force_uat_mode}</code>\n\n"
                "Shared NIFTY cache is fed from captured ticks. "
                "Live broker feed is unchanged for market hours."
            ),
        )

    def _on_stopped() -> None:
        logger.info("%s MODE STOPPED", UAT_LOG_TAG)
        _queue_uat_notify(
            app,
            "stopped",
            (
                f"<b>DRISHTI UAT MODE STOPPED</b>\n\n"
                f"{UAT_LOG_TAG}\n"
                f"Stopped: <code>{datetime.now(_IST).strftime('%d-%b-%Y %H:%M:%S IST')}</code>"
            ),
        )

    service = build_uat_replay_service(
        config=cfg,
        workspace_root=_WORKSPACE_ROOT,
        on_started=_on_started,
        on_stopped=_on_stopped,
        trading_day_check=is_trading_day,
    )
    if service is None:
        logger.error(
            "%s Replay file missing or unusable — cannot start (no crash)",
            UAT_LOG_TAG,
        )
        _queue_uat_notify(
            app,
            "missing_source",
            (
                f"<b>DRISHTI UAT MODE ERROR</b>\n\n"
                f"{UAT_LOG_TAG}\n"
                "Replay file missing or has too few ticks.\n"
                "Capture a market-hours WS/REST LTP log first, then retry.\n"
                "<i>Live production feed is unaffected.</i>"
            ),
        )
        return False
    app.bot_data[_UAT_REPLAY_SERVICE_KEY] = service
    app.bot_data["market_data_mode"] = "uat_replay"
    service.start()
    logger.info(
        "%s service started — speed=%s source=%s ticks=%s",
        UAT_LOG_TAG,
        cfg.replay_speed,
        service.source_file.name,
        len(service.ticks),
    )
    return True


def sync_uat_market_replay(app: Application) -> str:
    """Align UAT replay with the current IST window. Returns action taken."""
    params = app.bot_data.get("params") if app.bot_data else None
    cfg = load_uat_replay_config_from_params(params if isinstance(params, dict) else None)
    running = is_uat_market_replay_running(app)
    want = bool(cfg.enabled and is_drishti_uat_replay_window(config=cfg))
    if want and not running:
        return "started" if start_uat_market_replay(app) else "start_failed"
    if not want and running:
        stop_uat_market_replay(app)
        return "stopped"
    return "running" if running else "idle"


async def uat_market_replay_watchdog_loop(app: Application) -> None:
    """Auto-enter / exit UAT Market Replay at the configured off-hours window."""
    while True:
        try:
            action = sync_uat_market_replay(app)
            if action in {"started", "stopped", "start_failed"}:
                logger.info("%s watchdog action=%s", UAT_LOG_TAG, action)
            await _flush_uat_notify(app)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("%s watchdog error: %s", UAT_LOG_TAG, exc)
        await asyncio.sleep(30)


def restart_nifty_feed(app: Application, token_store: TokenStore) -> None:
    """Start or restart background feed (WebSocket in-process or REST poller)."""
    from core.market_data_provider import (
        LIVE_LOG_TAG,
        describe_mode_for_logs,
        live_feed_should_run,
    )

    stop_nifty_feed(app)

    params = app.bot_data.get("params") if app.bot_data else None
    uat_cfg = load_uat_replay_config_from_params(params if isinstance(params, dict) else None)
    logger.info("%s", describe_mode_for_logs(uat_cfg))

    if not live_feed_should_run(uat_cfg):
        logger.info(
            "%s force_uat_mode=true — skipping LIVE WS/REST collectors; "
            "ReplayMarketProvider owns shared cache",
            UAT_LOG_TAG,
        )
        app.bot_data.pop(_FEED_BLOCK_KEY, None)
        app.bot_data["market_data_mode"] = "uat_replay"
        sync_uat_market_replay(app)
        return

    client_code = str(app.bot_data.get("client_code") or "")
    cfg = load_feed_config()
    if cfg is None:
        app.bot_data.pop(_FEED_BLOCK_KEY, None)
        logger.info("NIFTY feed not started — operator has not configured LTP Feed Setup")
        # Still attempt UAT replay off-hours (file-based; no broker token required).
        sync_uat_market_replay(app)
        return

    block = nifty_feed_token_block_reason(token_store)
    if block:
        app.bot_data[_FEED_BLOCK_KEY] = block
        logger.warning("%s NIFTY live feed not started — %s", LIVE_LOG_TAG, block)
        # Off-hours UAT replay does not need a live JWT.
        sync_uat_market_replay(app)
        return

    app.bot_data.pop(_FEED_BLOCK_KEY, None)
    app.bot_data["market_data_mode"] = "live"

    def _live_token() -> str | None:
        tok, _ = token_store.load()
        if not tok or token_store.is_effectively_expired():
            return None
        return tok

    chat_id = str(app.bot_data.get("chat_id") or "")
    hooks = DrishtiFeedHooks(app, chat_id, token_store) if chat_id else None

    from core.utils import is_trading_day

    if cfg.is_websocket_mode():
        transport = resolve_active_transport(cfg, app.bot_data)
        if transport == "rest":
            if not client_code:
                logger.info("NIFTY REST fallback not started — missing client_code")
                sync_uat_market_replay(app)
                return
            service: NiftyLtpFeedService | NiftyLtpWebSocketFeedService = NiftyLtpFeedService(
                client_code=client_code,
                token_getter=_live_token,
                config=cfg,
                hooks=hooks,
                log_dir=bot_nifty_rest_ltp_log_dir(_WORKSPACE_ROOT),
                trading_day_check=is_trading_day,
            )
        else:
            if not client_code:
                logger.info("NIFTY WebSocket feed not started — missing client_code")
                sync_uat_market_replay(app)
                return
            service = NiftyLtpWebSocketFeedService(
                client_code=client_code,
                token_getter=_live_token,
                config=cfg,
                hooks=hooks,
                log_dir=bot_nifty_websocket_ltp_log_dir(_WORKSPACE_ROOT),
                trading_day_check=is_trading_day,
            )
    else:
        if not client_code:
            logger.info("NIFTY REST feed not started — missing client_code")
            sync_uat_market_replay(app)
            return
        service = NiftyLtpFeedService(
            client_code=client_code,
            token_getter=_live_token,
            config=cfg,
            hooks=hooks,
            log_dir=bot_nifty_rest_ltp_log_dir(_WORKSPACE_ROOT),
            trading_day_check=is_trading_day,
        )

    app.bot_data["nifty_ltp_feed_service"] = service
    service.start()
    # Continuous option LTP audit for registered legs + ATO protect (1–2s).
    try:
        from core.option_ltp_feed import OptionLtpAuditService, stop_option_ltp_audit

        stop_option_ltp_audit(app.bot_data)
        option_audit = OptionLtpAuditService(
            client_code=client_code,
            token_getter=_live_token,
            log_dir=bot_option_ltp_log_dir(_WORKSPACE_ROOT),
            workspace_root=_WORKSPACE_ROOT,
            interval_seconds=2.0,
            trading_day_check=is_trading_day,
        )
        app.bot_data["option_ltp_audit_service"] = option_audit
        option_audit.start()
        logger.info(
            "%s Option LTP audit started — every 2s → option_ltp/option_ltp_YYYYMMDD.log",
            LIVE_LOG_TAG,
        )
    except Exception as exc:
        logger.warning("%s Option LTP audit not started: %s", LIVE_LOG_TAG, exc)
    active = (
        resolve_active_transport(cfg, app.bot_data)
        if cfg.is_websocket_mode()
        else cfg.feed_mode
    )
    logger.info(
        "%s NIFTY feed (re)started — config=%s active=%s poll=%ss stale=%ss",
        LIVE_LOG_TAG,
        cfg.feed_mode,
        active,
        cfg.poll_interval_seconds,
        cfg.stale_price_alert_seconds,
    )
    restart_gift_nifty_probe(app, token_store)
    sync_uat_market_replay(app)


class NiftyFeedFailoverController:
    """Runtime WS→REST failover — does not change ``nifty_ltp_feed_config.json``."""

    _MIN_SWITCH_SECONDS = 30.0

    def __init__(self, app: Application, token_store: TokenStore) -> None:
        self._app = app
        self._token_store = token_store

    def _chat_id(self) -> str:
        return str(self._app.bot_data.get("chat_id") or "")

    async def _notify(self, text: str, *, throttle: bool = False) -> None:
        if throttle and not should_send_recovery_alert(interval_seconds=ALERT_INTERVAL_SECONDS):
            return
        chat_id = self._chat_id()
        if not chat_id:
            return
        try:
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            logger.warning("DRISHTI failover notice failed: %s", exc)

    def _can_switch(self, state) -> bool:
        if state.last_switch_at is None:
            return True
        try:
            last = datetime.fromisoformat(state.last_switch_at)
            elapsed = (datetime.now(_IST) - last).total_seconds()
            return elapsed >= self._MIN_SWITCH_SECONDS
        except (TypeError, ValueError):
            return True

    async def on_websocket_crash(self, reason: str) -> None:
        cfg = load_feed_config()
        if not is_failover_eligible(cfg):
            return
        state = get_failover_state(self._app.bot_data)
        if state.failover_in_progress or not self._can_switch(state):
            return
        state.failover_in_progress = True
        try:
            today = datetime.now(_IST).date().isoformat()
            await self._notify(
                "🔴 <b>WebSocket feed failed</b>\n\n"
                f"<code>{html.escape(reason)}</code>\n\n"
                "Switching to <b>REST fallback</b> for today's session.\n"
                "<i>Saved LTP Feed Setup still shows WebSocket — change manually if needed.</i>"
            )
            pause_algo(reason="nifty_ltp_websocket_failed", paused_by="drishti")
            await self._notify(
                "⏸ <b>ATO auto-paused</b> on KAVACH — no reliable NIFTY price until REST recovers."
            )
            await publish_incident(
                source="drishti",
                scenario="nifty_ltp_stale_cache",
                severity=feed_incident_severity("critical"),
                category="connectivity",
                title="NIFTY WebSocket feed failed — REST fallback",
                error_message=reason,
                next_action="DRISHTI is switching to REST. ATO resumes when cache is fresh.",
                source_bot=self._app.bot,
                source_chat_id=self._chat_id() or None,
            )
            state.active_transport = "rest"
            state.session_rest_lock_date = today
            state.degraded = True
            state.pause_reason = "nifty_ltp_websocket_failed"
            state.last_switch_at = datetime.now(_IST).isoformat()
            save_failover_state(self._app.bot_data, state)
            mark_feed_degraded()
            record_transport_switch()
            restart_nifty_feed(self._app, self._token_store)
            await self._maybe_escalate_cycle_exhausted()
        finally:
            state.failover_in_progress = False
            save_failover_state(self._app.bot_data, state)

    async def _maybe_escalate_cycle_exhausted(self) -> None:
        if not is_transport_cycle_exhausted():
            return
        set_recovery_owner(OWNER_OPERATOR, by="transport_cycle_exhausted")
        await self._notify(
            "🔴 <b>NIFTY feed cycle exhausted</b> (WebSocket → REST → WebSocket → REST)\n\n"
            "Feed still down after 5+ minutes of retries. ATO stays paused.\n"
            f"Tap <b>{LABEL_MANUAL_HANDLING}</b> if you are fixing token/VPS yourself.\n"
            "DRISHTI will notify both chats when the feed is back.",
            throttle=False,
        )

    async def on_rest_failure(self, reason: str) -> None:
        cfg = load_feed_config()
        if not is_failover_eligible(cfg):
            return
        state = get_failover_state(self._app.bot_data)
        if state.failover_in_progress or not self._can_switch(state):
            return
        state.failover_in_progress = True
        try:
            await self._notify(
                "🔴 <b>REST fallback failed</b>\n\n"
                f"<code>{html.escape(reason)}</code>\n\n"
                "Retrying <b>WebSocket</b> — will keep alternating until feed recovers.",
                throttle=True,
            )
            pause_algo(reason="nifty_ltp_rest_fallback_failed", paused_by="drishti")
            state.degraded = True
            mark_feed_degraded()
            state.active_transport = "websocket"
            state.pause_reason = "nifty_ltp_rest_fallback_failed"
            state.last_switch_at = datetime.now(_IST).isoformat()
            save_failover_state(self._app.bot_data, state)
            record_transport_switch()
            restart_nifty_feed(self._app, self._token_store)
            await self._maybe_escalate_cycle_exhausted()
        finally:
            state.failover_in_progress = False
            save_failover_state(self._app.bot_data, state)

    async def on_feed_healthy(self) -> None:
        cfg = load_feed_config()
        if cfg is None:
            return
        snap = read_nifty_ltp_cache()
        if snap is None or snap.ltp <= 0 or not snap.feed_healthy:
            return
        if not snap.is_fresh(cfg.consumer_max_age_seconds()):
            update_feed_ready_stability(ready=False)
            return
        ready, _ = is_nifty_cache_trading_ready()
        update_feed_ready_stability(ready=ready)
        if not ready:
            return
        if not is_algo_paused():
            clear_feed_degraded()
            return
        if not can_auto_resume_feed_recovery():
            return

        state = get_failover_state(self._app.bot_data)
        label = cache_transport_label(snap)
        if resume_algo():
            clear_feed_degraded()
            state.degraded = False
            state.pause_reason = None
            save_failover_state(self._app.bot_data, state)
            await resolve_incident(
                source="drishti",
                scenario="nifty_ltp_stale_cache",
                resolution_message=f"NIFTY feed healthy — {label}.",
                source_bot=self._app.bot,
                source_chat_id=self._chat_id() or None,
            )
            await self._notify(
                f"▶ <b>ATO auto-resumed</b> — {html.escape(label)} is fresh.\n"
                "KAVACH monitoring active again."
            )


def recovery_control_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"🙋 {LABEL_MANUAL_HANDLING}",
                    callback_data=f"{_CB_FEED}:recovery_operator",
                ),
                InlineKeyboardButton(
                    f"🤖 {LABEL_AUTO_RESUME}",
                    callback_data=f"{_CB_FEED}:recovery_auto",
                ),
            ],
        ]
    )


async def notify_feed_ready_both_chats(
    app: Application,
    *,
    body_html: str,
    include_kavach_menu: bool = True,
) -> None:
    """Same feed-ready text to DRISHTI and KAVACH chats (separate groups)."""
    chat_id = str(app.bot_data.get("chat_id") or "")
    if chat_id:
        await app.bot.send_message(
            chat_id=chat_id,
            text=body_html,
            parse_mode=ParseMode.HTML,
        )
    if include_kavach_menu:
        # Always use locked KAVACH 2.0 home keyboard (no feed-recovery row).
        from bat_telegram.bots.kavach2.bot import _main_menu_keyboard

        await send_kavach_html(body_html, reply_markup=_main_menu_keyboard())
    else:
        await send_kavach_html(body_html)


async def send_kavach_feed_ready_menu(app: Application, *, body_html: str) -> None:
    await notify_feed_ready_both_chats(app, body_html=body_html, include_kavach_menu=True)


def recovery_auto_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Yes, auto resume",
                    callback_data=f"{_CB_FEED}:recovery_auto_confirm",
                ),
                InlineKeyboardButton("Cancel", callback_data=f"{_CB_FEED}:cancel"),
            ],
        ]
    )


async def feed_recovery_watchdog_loop(app: Application, token_store: TokenStore) -> None:
    """Periodic degraded-outage notices (30s throttle) and 5-minute escalation."""
    while True:
        await asyncio.sleep(30)
        try:
            if not is_nse_market_session():
                clear_recovery_at_eod()
                continue
            cfg = load_feed_config()
            if not is_failover_eligible(cfg):
                continue

            if try_websocket_retry_after_rest(app.bot_data):
                restart_nifty_feed(app, token_store)
                chat_id = str(app.bot_data.get("chat_id") or "")
                if chat_id:
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "🔄 <b>Retrying WebSocket feed</b> after REST stabilization.\n"
                            "Cache will update via WebSocket if Dhan accepts the connection."
                        ),
                        parse_mode=ParseMode.HTML,
                    )
                continue

            session_action = try_session_open_auto_resume()
            if session_action == "auto_resumed":
                chat_id = str(app.bot_data.get("chat_id") or "")
                if chat_id:
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "▶ <b>ATO auto-resumed</b> (KAVACH schedule)\n\n"
                            "NIFTY feed is healthy — KAVACH monitoring active."
                        ),
                        parse_mode=ParseMode.HTML,
                    )
                await send_kavach_feed_ready_menu(
                    app,
                    body_html="▶ <b>ATO auto-resumed</b> — NIFTY feed healthy.",
                )
                continue

            ready, age = is_nifty_cache_trading_ready()
            update_feed_ready_stability(ready=ready)
            chat_id = str(app.bot_data.get("chat_id") or "")

            if should_notify_kavach_resume_ready():
                label = cache_transport_label(read_nifty_ltp_cache())
                await send_kavach_feed_ready_menu(
                    app,
                    body_html=(
                        f"✅ <b>NIFTY feed is ready</b>\n\n{html.escape(label)} · "
                        f"cache age {age:.0f}s\n\nTap <b>Resume</b> on KAVACH."
                    ),
                )

            if ready and can_auto_resume_feed_recovery() and is_algo_paused():
                ctrl = NiftyFeedFailoverController(app, token_store)
                await ctrl.on_feed_healthy()
                continue

            if ready and should_notify_operator_feed_ready() and chat_id:
                label = cache_transport_label(read_nifty_ltp_cache())
                body = (
                    "✅ <b>NIFTY feed is back</b>\n\n"
                    f"{html.escape(label)} · cache age {age:.0f}s\n\n"
                    "Tap <b>Resume</b> on KAVACH when you want monitoring again.\n\n"
                    "<i>DRISHTI will not auto-resume in manual mode.</i>"
                )
                await send_kavach_feed_ready_menu(app, body_html=body)
                continue

            if session_action == "notify_operator" and chat_id:
                body = (
                    "🌅 <b>KAVACH schedule — feed healthy</b>\n\n"
                    "ATO still paused from yesterday. Tap <b>Resume</b> on KAVACH."
                )
                await send_kavach_feed_ready_menu(app, body_html=body)
                continue

            if not is_feed_degraded():
                continue

            if not chat_id:
                continue

            if should_send_degraded_status_alert():
                owner = get_recovery_owner()
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "⏱ <b>Feed unstable for 5+ minutes</b>\n\n"
                        "DRISHTI is still alternating WebSocket ↔ REST.\n"
                        "ATO stays paused to avoid wrong orders.\n\n"
                        "If you are fixing this yourself, tap "
                        f"<b>{html.escape(LABEL_MANUAL_HANDLING)}</b> — DRISHTI will keep retrying "
                        "but will <b>not</b> auto-resume ATO.\n"
                        f"<i>Recovery owner: {html.escape(owner)}</i>"
                    ),
                    parse_mode=ParseMode.HTML,
                    reply_markup=recovery_control_keyboard(),
                )
                continue
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Feed recovery watchdog error: %s", exc)


def format_nifty_status_html(app: Application | None = None) -> str:
    """Compact feed-only status for ``/niftystatus``."""
    cfg = load_feed_config()
    now = datetime.now(_IST).strftime("%d-%b-%Y %H:%M:%S IST")
    if cfg is None:
        return f"📊 <b>NIFTY Status</b>\n<code>{html.escape(now)}</code>\n\nFeed not configured."

    snap = read_nifty_ltp_cache()
    bot_data = app.bot_data if app is not None else {}
    active = (
        active_transport_label(cfg, bot_data)
        if cfg.is_websocket_mode()
        else cfg.feed_mode
    )
    running = is_background_feed_running(app) if app is not None else None
    ready, age = is_nifty_cache_trading_ready()
    owner = get_recovery_owner()
    owner_label = "DRISHTI auto-recovery" if owner == OWNER_DRISHTI else "Operator (manual)"
    degraded = "yes" if is_feed_degraded() else "no"

    lines = [
        "📊 <b>NIFTY Status</b>",
        f"<code>{html.escape(now)}</code>",
        "",
        f"Config mode:    <code>{html.escape(cfg.feed_mode)}</code>",
        f"Active path:    <b>{html.escape(active)}</b>",
    ]
    if app is not None and is_uat_market_replay_running(app):
        uat_svc = app.bot_data.get(_UAT_REPLAY_SERVICE_KEY)
        source_name = (
            uat_svc.source_file.name
            if isinstance(uat_svc, NiftyLtpUatReplayService)
            else "tick log"
        )
        lines.append(f"UAT replay:     <b>ON</b> · {UAT_LOG_TAG}")
        lines.append(f"UAT source:     <code>{html.escape(source_name)}</code>")
        progress = get_uat_replay_progress(app)
        if progress is not None:
            lines.append("")
            lines.append(html.escape(format_uat_time_block(progress)))
            lines.append(f"Cache LTP:      ₹{progress.ltp:,.2f} (matches replay tick)")
    if app is not None:
        raw_block = app.bot_data.get(_FEED_BLOCK_KEY)
        if isinstance(raw_block, str) and raw_block:
            lines.append(f"Feed blocked:   <b>{html.escape(raw_block)}</b>")
    lines.append(
        f"Feed task:      {'running' if running else 'stopped' if running is False else 'unknown'}"
    )
    lines.extend(
        [
            f"Recovery owner: <b>{html.escape(owner_label)}</b>",
            f"Degraded:       {degraded}",
            f"ATO cache ready: {'yes' if ready else 'no'}",
        ]
    )
    if not (app is not None and is_uat_market_replay_running(app) and get_uat_replay_progress(app)):
        if snap and snap.ltp > 0:
            lines.append(f"Cache LTP:      ₹{snap.ltp:,.2f} ({cache_transport_label(snap)})")
            lines.append(f"Cache age:      {snap.age_seconds():.0f}s")
        elif age is not None:
            lines.append(f"Cache age:      {age:.0f}s")
    return "\n".join(lines)


def restart_gift_nifty_probe(app: Application, token_store: TokenStore) -> None:
    """Start off-hours GIFT NIFTY validation probe (separate from production NIFTY cache)."""
    existing = app.bot_data.get("gift_nifty_probe_service")
    if isinstance(existing, GiftNiftyProbeService):
        existing.stop()

    if nifty_feed_token_block_reason(token_store):
        logger.info("GIFT NIFTY probe not started — Dhan token missing or expired")
        return

    client_code = str(app.bot_data.get("client_code") or "")
    cfg = load_feed_config()
    if not client_code:
        logger.info("GIFT NIFTY probe not started — missing client_code")
        return
    if cfg is None:
        cfg = NiftyLtpFeedConfig()

    from core.utils import is_trading_day

    def _live_token() -> str | None:
        tok, _ = token_store.load()
        if not tok or token_store.is_effectively_expired():
            return None
        return tok

    probe = GiftNiftyProbeService(
        client_code=client_code,
        token_getter=_live_token,
        config=cfg,
        log_dir=_nifty_audit_log_dir(),
        trading_day_check=is_trading_day,
    )
    app.bot_data["gift_nifty_probe_service"] = probe
    probe.start()
    logger.info(
        "GIFT NIFTY off-hours probe (re)started — poll=%ss",
        cfg.poll_interval_seconds,
    )


async def prompt_feed_setup(message: Message) -> None:
    await message.reply_text(
        "⚙️ <b>LTP Feed Setup</b>\n\n"
        "DRISHTI is the <b>only</b> NIFTY LTP collector. KAVACH / ATO read "
        "<code>data/nifty_ltp_cache.json</code> — they never call Dhan for spot.\n\n"
        "<b>Step 1:</b> Feed source",
        parse_mode=ParseMode.HTML,
        reply_markup=feed_mode_keyboard(),
    )


def is_background_feed_running(app: Application) -> bool:
    """True when the feed or external-watch task is active in this DRISHTI process."""
    return is_nifty_feed_task_running(app.bot_data.get("nifty_ltp_feed_service"))


def _format_cache_timestamp(raw: str) -> str:
    try:
        return datetime.fromisoformat(raw).strftime("%d-%b-%Y %H:%M:%S IST")
    except (TypeError, ValueError):
        return raw


def format_feed_status_line(app: Application | None = None) -> str:
    """One-line feed summary for the DRISHTI alive menu (reads disk cache)."""
    cfg = load_feed_config()
    if cfg is None:
        return "📡 LTP feed: not configured — defaults apply on next token save"

    if app is not None and is_uat_market_replay_running(app):
        progress = get_uat_replay_progress(app)
        if progress is not None:
            return (
                f"📡 LTP feed: {UAT_LOG_TAG} ₹{progress.ltp:,.2f} · "
                f"replay {html.escape(format_clock_ampm(progress.replay_market_time))} · "
                f"{progress.progress_percent:.1f}% · {html.escape(progress.speed_multiplier)}"
            )
        snap = read_nifty_ltp_cache()
        uat_svc = app.bot_data.get(_UAT_REPLAY_SERVICE_KEY)
        source_name = (
            uat_svc.source_file.name
            if isinstance(uat_svc, NiftyLtpUatReplayService)
            else "tick log"
        )
        if snap and snap.ltp > 0:
            return (
                f"📡 LTP feed: {UAT_LOG_TAG} replaying · ₹{snap.ltp:,.2f} · "
                f"<code>{html.escape(source_name)}</code> · age {snap.age_seconds():.0f}s"
            )
        return f"📡 LTP feed: {UAT_LOG_TAG} replaying · <code>{html.escape(source_name)}</code>"

    if app is not None:
        block = app.bot_data.get(_FEED_BLOCK_KEY)
        if isinstance(block, str) and block:
            return f"📡 LTP feed: 🔴 blocked — {html.escape(block)}"

    running = is_background_feed_running(app) if app is not None else None
    snap = read_nifty_ltp_cache()
    max_age = cfg.consumer_max_age_seconds()
    poll = cfg.poll_interval_seconds
    if cfg.is_websocket_mode():
        mode = active_transport_label(cfg, app.bot_data if app else {})
    else:
        mode = "REST"

    if running is False:
        return (
            f"📡 LTP feed: 🔴 stopped · {mode} · poll {poll}s — "
            "watchdog should restart; tap <b>Health (Python)</b>"
        )

    if snap and snap.is_fresh(max_age):
        return (
            f"📡 <b>LTP Feed:</b> 🟢 Healthy · \n"
            f"Source : {mode} \n"
            f"· Poll : {poll}s \n"
            f"· <b>₹{snap.ltp:,.2f}</b> ·"
        )
    if snap and snap.ltp > 0:
        health = "unhealthy" if not snap.feed_healthy else "stale"
        if not is_nse_market_session():
            ts = _format_cache_timestamp(snap.updated_at)
            return (
                f"📡 LTP feed: 🌙 market closed · last ₹{snap.ltp:,.2f} "
                f"({ts}) — tap <b>Live Price</b> during session for fresh quote"
            )
        return (
            f"📡 LTP feed: 🟠 {health} · poll {poll}s · "
            f"last ₹{snap.ltp:,.2f} — background feed retrying"
        )
    return f"📡 LTP feed: 🟡 warming up · poll {poll}s — cache filling…"


def format_gift_probe_status_line(app: Application | None = None) -> str:
    """One-line GIFT NIFTY off-hours validation probe (not used by KAVACH/ATO)."""
    cfg = load_feed_config()
    if cfg is None:
        return ""

    if is_nse_market_session():
        return "🎁 <b>GIFT Probe:</b> Idle (NSE open — production NIFTY feed ACTIVE )"

    snap = read_gift_nifty_cache()
    poll = cfg.poll_interval_seconds
    thresholds = resolve_user_ping_thresholds(cfg)
    max_age = thresholds.feed_max_seconds
    warn_age = thresholds.warning_seconds
    running = is_gift_probe_running(app.bot_data.get("gift_nifty_probe_service")) if app else None

    if snap and snap.probe_healthy and snap.age_seconds() <= warn_age and snap.is_fresh(max_age):
        age = snap.age_seconds()
        run_tag = " · task ✅" if running else ""
        return (
            f"🎁 GIFT probe: 🟢 ₹{snap.ltp:,.2f} · {GIFT_NIFTY_SYMBOL} · "
            f"{age:.0f}s ago · poll {poll}s · warn {warn_age:.0f}s{run_tag}\n"
            f"<i>Validation only — not for ATO/KAVACH</i>"
        )
    if snap and snap.ltp > 0:
        ts = _format_cache_timestamp(snap.updated_at)
        return f"🎁 GIFT probe: 🟠 last ₹{snap.ltp:,.2f} ({ts}) — tap <b>GIFT Nifty</b> or wait for probe"
    return f"🎁 GIFT probe: 🟡 warming · poll {poll}s when NSE closed"


def format_feed_health_block(app: Application | None = None) -> str:
    """Multi-line feed section for Health report."""
    cfg = load_feed_config()
    if cfg is None:
        return "  Feed: not configured (auto-created on token save)"

    snap = read_nifty_ltp_cache()
    running = is_background_feed_running(app) if app is not None else None
    active = (
        active_transport_label(cfg, app.bot_data)
        if app is not None and cfg.is_websocket_mode()
        else cfg.feed_mode
    )
    lines = [
        f"  Feed Mode:     {str(cfg.feed_mode).capitalize()}",
        f"  Active Path:   {active}",
        f"  Poll Interval: {cfg.poll_interval_seconds}s",
        f"  Stale Alert:   {cfg.stale_price_alert_seconds}s",
        f"  Ping Warning:  {cfg.user_ping_warning_age_seconds}s "
        f"(effective {cfg.effective_user_ping_warning_age_seconds():.0f}s)",
        f"  Ping Critical: {cfg.user_ping_critical_age_seconds}s "
        f"(effective {cfg.effective_user_ping_critical_age_seconds():.0f}s)",
        f"  Poller Task:   {'running' if running else 'stopped' if running is False else 'unknown'}",
    ]
    if app is not None and is_uat_market_replay_running(app):
        uat_svc = app.bot_data.get(_UAT_REPLAY_SERVICE_KEY)
        source_name = (
            uat_svc.source_file.name
            if isinstance(uat_svc, NiftyLtpUatReplayService)
            else "tick log"
        )
        lines.append(f"  UAT replay:    ON ({UAT_LOG_TAG})")
        lines.append(f"  UAT source:    {source_name}")
        progress = get_uat_replay_progress(app)
        if progress is not None:
            lines.append(f"  Replay mkt:    {format_clock_ampm(progress.replay_market_time)}")
            lines.append(f"  System time:   {format_clock_ampm(progress.current_system_time)}")
            lines.append(f"  Progress:      {progress.progress_percent:.1f}%")
            lines.append(f"  Replay speed:  {progress.speed_multiplier}")
    if snap:
        lines.append(f"  Cache LTP:     ₹{snap.ltp:,.2f}")
        lines.append(f"  Cache Health:  {'healthy' if snap.feed_healthy else 'unhealthy'}")
        lines.append(f"  Cache Age:     {snap.age_seconds():.0f}s")
        if snap.consecutive_failures:
            lines.append(f"  Fail Streak:   {snap.consecutive_failures}")
    return "\n".join(lines)


def _feed_mode_label(cfg: NiftyLtpFeedConfig | None) -> str:
    if cfg is None:
        return "unknown"
    if cfg.is_websocket_mode():
        return "WebSocket"
    return "REST"


def format_cache_ltp_reply(
    snap: NiftyLtpCacheSnapshot | None,
    cfg: NiftyLtpFeedConfig | None,
    *,
    feed_running: bool,
    format_ltp_card,
    in_market_session: bool | None = None,
    bot_data: dict | None = None,
    uat_replay_running: bool = False,
    uat_progress: UatReplayProgress | None = None,
) -> str:
    """Build cache-only Nifty LTP button reply — never opens a new Dhan connection."""
    poll_s = cfg.poll_interval_seconds if cfg else 2
    max_age = float(cfg.consumer_max_age_seconds() if cfg else poll_s * 3)
    in_session = is_nse_market_session() if in_market_session is None else in_market_session
    cache_label = cache_transport_label(snap)
    if bot_data is not None and cfg is not None and cfg.is_websocket_mode():
        bg_label = active_transport_label(cfg, bot_data)
    else:
        bg_label = _feed_mode_label(cfg)

    if uat_replay_running and (uat_progress is not None or (snap and snap.ltp > 0)):
        ltp = uat_progress.ltp if uat_progress is not None else float(snap.ltp)  # type: ignore[union-attr]
        lines = [
            f"{UAT_LOG_TAG}",
            f"<b>Nifty LTP:</b> ₹{ltp:,.2f}",
        ]
        if uat_progress is not None:
            lines.append("")
            lines.append(html.escape(format_uat_time_block(uat_progress)))
            # Guard: displayed LTP must match the progress tick.
            if abs(uat_progress.ltp - ltp) > 1e-9:
                lines.append("<i>Warning: LTP/time pair mismatch — check logs.</i>")
        else:
            now = datetime.now(_IST)
            lines.append("Replay Market Time: —")
            lines.append(
                f"Current Time:       {html.escape(now.strftime('%I:%M:%S %p').lstrip('0'))}"
            )
        lines.append("")
        lines.append("📡 Shared cache updating for Coverage / KAVACH / ATO")
        return "\n".join(lines)

    if snap and snap.ltp > 0:
        ts = _format_cache_timestamp(snap.updated_at)
        body = format_ltp_card(snap.ltp, cache_label, ts)
        if not in_session:
            return body + "\n\n🌙 <b>Market closed</b> — last cached NIFTY snapshot."
        if snap.is_fresh(max_age) and snap.feed_healthy:
            return body
        return (
            body
            + f"\n\n🟠 <b>Cache:</b> may be stale · age {snap.age_seconds():.0f}s"
        )

    if uat_replay_running:
        return (
            f"{UAT_LOG_TAG} <b>Market Replay active</b>\n\n"
            "Cache warming up from captured ticks…"
        )

    if not in_session:
        return "🌙 <b>Market closed</b>\n\nNo NIFTY cache yet."

    grace_s = int(cfg.websocket_startup_grace_seconds if cfg else 30)
    if feed_running:
        return (
            "⏳ <b>NIFTY LTP (cache)</b>\n\n"
            f"Background {bg_label} feed is running — cache warming up.\n"
            f"<i>WebSocket gets up to {grace_s}s after 09:15 for the first tick.</i>"
        )
    return (
        "⏳ <b>No NIFTY cache yet</b>\n\n"
        "Tap <b>LTP Feed Setup</b> or save a valid token to start the feed."
    )


def rest_method_disabled_message(cfg: NiftyLtpFeedConfig) -> str:
    mode = _feed_mode_label(cfg)
    return (
        f"REST method is not enabled for this configuration.\n"
        f"Current feed method is <b>{html.escape(mode)}</b> (<code>{html.escape(cfg.feed_mode)}</code>)."
    )


def websocket_method_disabled_message(cfg: NiftyLtpFeedConfig) -> str:
    mode = _feed_mode_label(cfg)
    return (
        f"WebSocket method is not enabled for this configuration.\n"
        f"Current feed method is <b>{html.escape(mode)}</b> (<code>{html.escape(cfg.feed_mode)}</code>)."
    )


async def reply_nifty_ltp_from_cache(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    token_store: TokenStore,
    main_menu_keyboard: InlineKeyboardMarkup,
    format_ltp_card,
) -> None:
    """Show NIFTY LTP from shared cache only — no new Dhan connection."""
    uat_running = is_uat_market_replay_running(context.application)
    tok, _ = token_store.load()
    if not tok and not uat_running:
        await message.reply_text(
            "🔴 <b>No token stored</b>\n\nTap <b>Update Token</b> and paste your Dhan JWT.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    if tok and token_store.is_effectively_expired() and not uat_running:
        await message.reply_text(
            "🟠 <b>Token expired</b>\n\nTap <b>Update Token</b> to refresh.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    cfg = load_feed_config()
    snap = read_nifty_ltp_cache()
    feed_running = is_background_feed_running(context.application)
    in_session = is_nse_market_session()
    uat_progress = get_uat_replay_progress(context.application) if uat_running else None
    text = format_cache_ltp_reply(
        snap,
        cfg,
        feed_running=feed_running,
        format_ltp_card=format_ltp_card,
        in_market_session=in_session,
        bot_data=context.application.bot_data,
        uat_replay_running=uat_running,
        uat_progress=uat_progress,
    )

    if snap is not None and snap.ltp > 0 and (cfg is None or cfg.log_enabled):
        now = datetime.now(_IST)
        await asyncio.to_thread(
            append_nifty_ltp_audit_log,
            _nifty_audit_log_dir(),
            now,
            snap.ltp,
            snap.source or "cache",
            event="user_cache_view",
        )

    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard,
    )


async def reply_live_price(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    token_store: TokenStore,
    main_menu_keyboard: InlineKeyboardMarkup,
    format_ltp_card,
) -> None:
    """One-shot live NIFTY quote using the configured feed transport."""
    from core.exceptions import BrokerAuthError, BrokerConnectionError
    from core.nifty_ltp_feed import fetch_nifty_ltp_rest_with_retry

    if is_uat_market_replay_running(context.application):
        await message.reply_text(
            uat_button_disabled_message("Live Price"),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    if not is_nse_market_session():
        await message.reply_text(
            "🌙 <b>Market is currently closed</b> (09:15–15:30 IST, trading days).\n\n"
            "Cannot fetch live NIFTY price. Tap <b>Nifty LTP</b> for the last cache snapshot.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    tok, _ = token_store.load()
    if not tok:
        await message.reply_text(
            "🔴 <b>No token stored</b>\n\nTap <b>Update Token</b> first.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return
    if token_store.is_effectively_expired():
        await message.reply_text(
            "🟠 <b>Token expired</b>\n\nTap <b>Update Token</b> to refresh.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    client_code = str(context.bot_data.get("client_code") or "")
    if not client_code:
        await message.reply_text(
            "🔴 <b>Setup incomplete</b>\n\nAdd <code>DHAN_CLIENT_CODE</code> to <code>config/.env</code>.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    cfg = load_feed_config() or build_default_feed_config(
        context.bot_data.get("params") if context.application else None
    )

    await message.reply_text(
        "⏳ Fetching live NIFTY price…",
        parse_mode=ParseMode.HTML,
    )

    try:
        if cfg.is_rest_mode():
            transport = "rest"
        elif cfg.is_websocket_mode():
            transport = resolve_active_transport(cfg, context.application.bot_data)
        else:
            transport = ""

        if transport == "rest":
            ltp = await asyncio.to_thread(
                fetch_nifty_ltp_rest_with_retry,
                client_code,
                tok,
                max_attempts=cfg.rest_max_attempts,
            )
            source = live_transport_label("rest")
            audit_source = "dhan_rest"
        elif transport == "websocket":
            snap = read_nifty_ltp_cache()
            max_age = float(cfg.consumer_max_age_seconds())
            if (
                is_background_feed_running(context.application)
                and snap is not None
                and snap.ltp > 0
                and snap.feed_healthy
                and snap.is_fresh(max_age)
            ):
                ltp = float(snap.ltp)
                source = cache_transport_label(snap)
                audit_source = snap.source or "dhan_websocket"
            else:
                ltp = await fetch_nifty_ltp_websocket(
                    client_code,
                    tok,
                    timeout_seconds=15.0,
                    max_retries=2,
                )
                source = live_transport_label("websocket")
                audit_source = "dhan_websocket"
        else:
            await message.reply_text(
                f"🔴 <b>Unsupported feed mode</b>\n\n<code>{html.escape(cfg.feed_mode)}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu_keyboard,
            )
            return
    except (BrokerAuthError, BrokerConnectionError) as exc:
        await message.reply_text(
            f"🔴 <b>Live price fetch failed</b>\n\n<code>{html.escape(str(exc))}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return
    except Exception as exc:
        await message.reply_text(
            f"🔴 <b>Live price fetch failed</b>\n\n<code>{html.escape(str(exc))}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    now = datetime.now(_IST)
    if cfg.log_enabled:
        await asyncio.to_thread(
            append_nifty_ltp_audit_log,
            _nifty_audit_log_dir(),
            now,
            ltp,
            audit_source,
            event="user_live_price",
        )

    feed_running = is_background_feed_running(context.application)
    note = (
        "\n\n🟢 One-shot live quote — background feed updates the shared cache."
        if feed_running
        else "\n\n💡 Background feed is stopped — cache may not update until feed restarts."
    )
    await message.reply_text(
        format_ltp_card(ltp, source) + note,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard,
    )


async def reply_gift_nifty_ltp(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    token_store: TokenStore,
    main_menu_keyboard: InlineKeyboardMarkup,
    format_ltp_card,
) -> None:
    """GIFT NIFTY live quote — off-hours validation (never written to production NIFTY cache)."""
    from core.exceptions import BrokerAuthError, BrokerConnectionError

    tok, _ = token_store.load()
    if not tok:
        await message.reply_text(
            "🔴 <b>No token stored</b>\n\nTap <b>Update Token</b> first.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return
    if token_store.is_effectively_expired():
        await message.reply_text(
            "🟠 <b>Token expired</b>\n\nTap <b>Update Token</b> to refresh.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    client_code = str(context.bot_data.get("client_code") or "")
    if not client_code:
        await message.reply_text(
            "🔴 <b>Setup incomplete</b>\n\nAdd <code>DHAN_CLIENT_CODE</code> to <code>config/.env</code>.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    cfg = load_feed_config()
    poll_s = cfg.poll_interval_seconds if cfg else 2
    thresholds = resolve_user_ping_thresholds(cfg)
    max_age = thresholds.feed_max_seconds
    warn_age = thresholds.warning_seconds
    snap = read_gift_nifty_cache()
    probe_running = is_gift_probe_running(
        context.application.bot_data.get("gift_nifty_probe_service")
    )

    if (
        snap
        and snap.probe_healthy
        and snap.is_fresh(max_age)
        and snap.age_seconds() <= warn_age
        and not is_nse_market_session()
    ):
        ts = _format_cache_timestamp(snap.updated_at)
        age = snap.age_seconds()
        body = format_ltp_card(
            snap.ltp,
            f"{GIFT_NIFTY_DISPLAY_NAME} — probe cache ({GIFT_NIFTY_SYMBOL})",
            ts,
        )
        extra = (
            f"\n\n🎁 <b>Off-hours validation feed</b>\n"
            f"Age {age:.0f}s · warn {warn_age:.0f}s · poll {poll_s}s · Dhan ID {snap.security_id}\n"
            "<i>Not used by KAVACH / ATO — NIFTY spot only during 09:15–15:30 IST.</i>"
        )
        if cfg is None or cfg.log_enabled:
            await asyncio.to_thread(
                append_gift_nifty_audit_log,
                _nifty_audit_log_dir(),
                datetime.now(_IST),
                snap.ltp,
                snap.source,
                event="user_ping_cache",
            )
        await message.reply_text(
            body + extra,
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    await message.reply_text(
        f"⏳ Fetching live {GIFT_NIFTY_DISPLAY_NAME} ({GIFT_NIFTY_SYMBOL}) from Dhan…",
        parse_mode=ParseMode.HTML,
    )

    try:
        ltp = await asyncio.to_thread(
            fetch_gift_nifty_ltp_rest_with_retry,
            client_code,
            tok,
            max_attempts=3,
        )
    except (BrokerAuthError, BrokerConnectionError) as exc:
        await message.reply_text(
            f"🔴 <b>GIFT NIFTY fetch failed</b>\n\n<code>{html.escape(str(exc))}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    seed_gift_nifty_cache(ltp, poll_interval_seconds=poll_s)
    now = datetime.now(_IST)
    if cfg is None or cfg.log_enabled:
        await asyncio.to_thread(
            append_gift_nifty_audit_log,
            _nifty_audit_log_dir(),
            now,
            ltp,
            "dhan_rest",
            event="user_ping",
        )

    in_session = is_nse_market_session()
    source = (
        f"{GIFT_NIFTY_DISPLAY_NAME} — Dhan REST (live validation)"
        if not in_session
        else f"{GIFT_NIFTY_DISPLAY_NAME} — Dhan REST (NSE open; spot NIFTY is production feed)"
    )
    note = (
        f"\n\n🎁 Symbol <code>{GIFT_NIFTY_SYMBOL}</code> · security ID 5024\n"
        f"Probe {'running' if probe_running else 'idle'} · poll {poll_s}s off-hours\n"
        "<i>Validation only — timestamps in "
        "<code>logs/runtime/…/drishti/logs/nifty_ltp/gift_nifty_ltp_*.log</code></i>"
    )
    await message.reply_text(
        format_ltp_card(ltp, source) + note,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard,
    )


async def test_websocket_ltp_health(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    token_store: TokenStore,
    main_menu_keyboard: InlineKeyboardMarkup,
    format_ltp_card,
) -> None:
    """After-hours / diagnostic one-shot websocket tick."""
    tok, _ = token_store.load()
    if not tok or token_store.is_effectively_expired():
        await message.reply_text(
            "🔴 <b>Token required</b>\n\nUpdate token first, then run this test.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    client_code = str(context.bot_data.get("client_code") or "")
    if not client_code:
        await message.reply_text(
            "🔴 Missing <code>DHAN_CLIENT_CODE</code> in <code>config/.env</code>.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    await message.reply_text(
        "⏳ Running NIFTY LTP (WebSocket) health test…\n\n"
        "<i>One-shot WebSocket tick — validates token, Data API subscription, "
        "and connectivity. KAVACH/ATO uses the Polling feed, not this path.</i>",
        parse_mode=ParseMode.HTML,
    )
    try:
        ltp = await fetch_nifty_ltp_websocket(
            client_code,
            tok,
            timeout_seconds=15.0,
            max_retries=1,
        )
        await message.reply_text(
            format_ltp_card(ltp, "WebSocket — Dhan v2 (health test)")
            + "\n\n✅ WebSocket path OK for this session.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
    except Exception as exc:
        await message.reply_text(
            "🔴 <b>Websocket health test failed</b>\n\n"
            f"<code>{html.escape(str(exc))}</code>\n\n"
            "Check token, Data API subscription, or VPS connectivity.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )


async def on_feed_setup_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    token_store: TokenStore,
    main_menu_keyboard: InlineKeyboardMarkup,
    send_alive_menu,
) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    message = query.message
    if message is None:
        return

    parts = (query.data or "").split(":")
    if len(parts) < 2:
        return
    action = parts[1]

    if action == "cancel":
        await send_alive_menu(message, context)
        return

    if action == "recovery_operator":
        set_recovery_owner(OWNER_OPERATOR, by="drishti_button")
        await message.reply_text(
            f"🙋 <b>{LABEL_MANUAL_HANDLING}</b> — you are in control\n\n"
            "DRISHTI keeps retrying WebSocket ↔ REST in the background.\n"
            "It will <b>not</b> auto-resume ATO.\n"
            "JAGRAN feed alerts are downgraded to <b>warning</b> while you handle this.\n\n"
            "When satisfied, tap <b>Resume</b> on KAVACH.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    if action == "recovery_auto":
        await message.reply_text(
            f"🤖 Switch to <b>{LABEL_AUTO_RESUME}</b>?\n\n"
            "DRISHTI will auto-resume ATO when the NIFTY cache is fresh.\n"
            "<i>Only confirm if you are not mid-fix on token or VPS.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=recovery_auto_confirm_keyboard(),
        )
        return

    if action == "recovery_auto_confirm":
        set_recovery_owner(OWNER_DRISHTI, by="drishti_button")
        await message.reply_text(
            f"🤖 <b>{LABEL_AUTO_RESUME}</b> enabled\n\n"
            "DRISHTI will auto-resume ATO when the NIFTY cache is fresh and healthy.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    if action == "setup":
        await prompt_feed_setup(message)
        return

    if action == "uat_speed" and len(parts) >= 3:
        speed = str(parts[2]).strip().lower()
        from core.nifty_ltp_uat_replay import REPLAY_SPEED_OPTIONS

        if speed not in REPLAY_SPEED_OPTIONS:
            await message.reply_text(
                f"{UAT_LOG_TAG} Unknown speed <code>{html.escape(speed)}</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        params = context.application.bot_data.get("params")
        if not isinstance(params, dict):
            params = {}
            context.application.bot_data["params"] = params
        uat = params.get("uat_market_replay")
        if not isinstance(uat, dict):
            uat = {}
            params["uat_market_replay"] = uat
        uat["replay_speed"] = speed
        uat["enabled"] = True
        restarted = start_uat_market_replay(context.application)
        cfg = load_uat_replay_config_from_params(params)
        await message.reply_text(
            f"{UAT_LOG_TAG} Replay speed set to <b>{html.escape(cfg.speed_label())}</b>\n"
            f"{'Restarted replay.' if restarted else 'Could not restart — check source file.'}",
            parse_mode=ParseMode.HTML,
            reply_markup=uat_speed_keyboard(),
        )
        return

    if action == "mode" and len(parts) == 3:
        mode = parts[2]
        if mode not in (FEED_MODE_REST, FEED_MODE_WEBSOCKET):
            return
        context.user_data["feed_setup_mode"] = mode
        if mode == FEED_MODE_WEBSOCKET:
            context.user_data["feed_setup_poll"] = 2
            mode_label = "WebSocket (in-process, live ticks)"
            await message.reply_text(
                f"Feed source: <b>{mode_label}</b>\n\n"
                "Live ticks — no poll interval. Feed stale critical if no tick for "
                "<b>5s</b>.\n\n"
                "<b>Step 2:</b> If NIFTY price does not change for how long "
                "should JAGRAN be alerted?",
                parse_mode=ParseMode.HTML,
                reply_markup=feed_stale_keyboard(),
            )
            return
        mode_label = "REST (DRISHTI polls Dhan)"
        await message.reply_text(
            f"Feed source: <b>{mode_label}</b>\n\n" "<b>Step 2:</b> Poll / watch interval?",
            parse_mode=ParseMode.HTML,
            reply_markup=feed_poll_keyboard(),
        )
        return

    if action == "poll" and len(parts) == 3:
        try:
            poll_s = int(parts[2])
        except ValueError:
            return
        context.user_data["feed_setup_poll"] = poll_s
        await message.reply_text(
            f"Poll interval: <b>{poll_s}s</b>\n\n"
            "<b>Step 3:</b> If NIFTY price does not change for how long "
            "should JAGRAN be alerted?",
            parse_mode=ParseMode.HTML,
            reply_markup=feed_stale_keyboard(),
        )
        return

    if action == "stale" and len(parts) == 3:
        try:
            stale_s = int(parts[2])
            poll_s = int(context.user_data.get("feed_setup_poll", 2))
            feed_mode = str(context.user_data.get("feed_setup_mode", FEED_MODE_REST))
        except (TypeError, ValueError):
            await message.reply_text("⚠️ Setup expired — tap LTP Feed Setup again.")
            return

        if stale_s not in POLL_INTERVAL_OPTIONS:
            await message.reply_text(
                "⚠️ Pick 1s, 2s, 3s, or 5s.",
                reply_markup=feed_stale_keyboard(),
            )
            return

        # Steps 4 & 5 removed — reuse Step 3 value for ping warning + critical.
        warn_s = stale_s
        crit_s = stale_s

        params = context.application.bot_data.get("params") or {}
        threshold = int(
            (params.get("nifty_ltp_feed") or {}).get("fetch_failure_jagran_threshold")
            or (params.get("health_check") or {}).get("websocket_jagran_retry_threshold", 5)
            or 5
        )
        base = build_default_feed_config(params)
        # Feed-refresh stale limit must stay above poll latency headroom.
        # Step 3 only controls unchanged-price / ping thresholds — not REST refresh.
        rest_stale = max(DEFAULT_REST_STALE_CRITICAL_SECONDS, poll_s * 3)
        ws_stale = DEFAULT_WEBSOCKET_STALE_CRITICAL_SECONDS
        try:
            cfg = NiftyLtpFeedConfig(
                feed_mode=feed_mode,
                poll_interval_seconds=poll_s,
                stale_price_alert_seconds=stale_s,
                user_ping_warning_age_seconds=warn_s,
                user_ping_critical_age_seconds=crit_s,
                fetch_failure_jagran_threshold=threshold,
                rest_max_attempts=base.rest_max_attempts,
                rest_retry_base_seconds=base.rest_retry_base_seconds,
                rest_retry_backoff_multiplier=base.rest_retry_backoff_multiplier,
                rate_limit_cooldown_seconds=base.rate_limit_cooldown_seconds,
                rest_stale_critical_seconds=rest_stale,
                websocket_stale_critical_seconds=ws_stale,
            )
        except ValueError as exc:
            await message.reply_text(
                f"🔴 <b>Invalid feed settings</b>\n\n<code>{html.escape(str(exc))}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=feed_stale_keyboard(),
            )
            return

        save_feed_config(cfg)
        for key in (
            "feed_setup_poll",
            "feed_setup_mode",
            "feed_setup_stale",
            "feed_setup_ping_warn",
        ):
            context.user_data.pop(key, None)
        restart_nifty_feed(context.application, token_store)

        mode_lines = (
            (
                "• Mode: <b>WebSocket (in-process)</b>\n"
                "• WS audit: <code>…/nifty_websocket_ltp/ws_ltp_YYYYMMDD.log</code>\n"
            )
            if feed_mode == FEED_MODE_WEBSOCKET
            else (
                f"• Mode: <b>REST</b> — polls every <b>{poll_s}s</b>\n"
                f"• REST audit: <code>…/nifty_rest_ltp/rest_ltp_YYYYMMDD.log</code>\n"
            )
        )

        await message.reply_text(
            "✅ <b>LTP feed configured</b>\n\n"
            f"{mode_lines}"
            f"• JAGRAN if price unchanged for <b>{stale_s}s</b>\n"
            f"• Ping warning if cache older than <b>{warn_s}s</b>\n"
            f"• Ping critical / incident if cache older than <b>{crit_s}s</b>\n"
            f"• Cache: <code>data/nifty_ltp_cache.json</code>\n\n"
            "<i>KAVACH / ATO read NIFTY cache only.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

    # Legacy Step 4 / 5 callbacks — redirect operators to finish via Step 3.
    if action in ("ping_warn", "ping_crit"):
        await message.reply_text(
            "Steps 4 and 5 were removed.\n\n"
            "Tap <b>LTP Feed Setup</b> again — after poll interval, pick "
            "<b>1s / 2s / 3s / 5s</b> in Step 3 (that value is used for alerts).",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard,
        )
        return

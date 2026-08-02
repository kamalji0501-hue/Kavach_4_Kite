# Reliability Failure Inventory & Ownership Map

**Sprint:** Reliability sweep (plan `reliability_sweep_plan_06273d7d`)  
**Updated:** 2026-06-25

---

## Failure classes

| Class | Symptom | Owner module | Test surface | Status |
|-------|---------|--------------|--------------|--------|
| Feed transport | WS disconnect, 429, auth errors | `core/nifty_ltp_websocket_feed.py`, `core/nifty_ltp.py` | `tests/test_nifty_ltp*.py`, market-hours deferred | Fixed (STAB-04–09) |
| Local cache write | `WinError 5` on cache replace, feed task exit | `core/nifty_ltp_feed.py` | `tests/test_nifty_ltp_feed.py`, INC-2026-023 | **Fixed 2026-06-25** |
| Failover persistence | WS→REST lock lost on DRISHTI restart | `core/nifty_ltp_failover.py` | `tests/test_nifty_ltp_failover.py` | Fixed (STAB-03) |
| False stale / resume churn | Instant resume after stale_cleared | `core/feed_recovery.py`, `nifty_feed_integration.py` | `tests/test_feed_recovery.py`, INC-022 | Fixed |
| Telegram delivery | JAGRAN publish timeout, alert loss | `core/telegram_delivery.py`, `incident_publisher.py` | `tests/test_telegram_runtime.py`, `tests/test_incident_publisher.py` | **Fixed 2026-06-25** |
| PTB polling restart | Fixed 5s delay, no RetryAfter | `run_*.py`, `core/telegram_runtime.py` | `tests/test_telegram_runtime.py` | **Fixed 2026-06-25** |
| Background task leak | Duplicate asyncio tasks after polling restart | `core/telegram_runtime.py`, DRISHTI/JAGRAN `bot.py` | `tests/test_telegram_runtime.py` | **Fixed 2026-06-25** |
| Process singleton | Duplicate DRISHTI, ORPHAN/GHOST_LOCK | `core/bot_lifecycle.py`, `bot_instance_guard.py` | `tests/test_bot_process_status.py`, harness | Fixed (STAB-08) |
| Startup LTP gate race | Abort start at 90s while cache fresh at 91s | `core/bot_supervisor.py` | `tests/test_bot_supervisor.py` | **Fixed 2026-06-25** |
| UAT state split-brain | ATO pause on wrong state file | `core/algo_control.py` | `tests/test_algo_control.py` | Fixed (STAB-01) |
| Token cold-start | KAVACH no broker until manual restart | `core/token_watch.py` | `tests/test_token_watch.py` | Fixed (STAB-10) |

---

## Architecture ownership

```
phase1_start_all.py / bot_supervisor.py
  └── DRISHTI (run_drishti.py)
        ├── nifty_feed_integration.py → feed task + watchdogs
        ├── nifty_ltp_feed.py → cache write + stale watchdog
        └── nifty_ltp_websocket_feed.py → WS collector
  └── KAVACH (run_kavach.py) → cache consumer + token_watch
  └── JAGRAN (run_jagran.py) → incident_publisher → telegram_delivery
```

---

## Remaining risk (non-blocking off-hours)

1. **Live tick validation** — deferred to `RELIABILITY_MARKET_HOURS_DEFERRED.md`
2. **Windows file-lock races** on other state files (not only `nifty_ltp_cache.json`) — monitor logs
3. **KAVACH** has no long-lived PTB background loops; `post_stop` cleanup wired for consistency
4. **15-cycle live-session harness** — partial off-hours runs complete lifecycle only

---

## Incident cross-reference

| ID | Title |
|----|-------|
| INC-2026-023 | Windows cache replace race destabilized DRISHTI feed |
| STAB-01…16 | See `docs/STABILIZATION_SPRINT.md` |

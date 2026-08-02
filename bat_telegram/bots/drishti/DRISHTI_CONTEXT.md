# DRISHTI Bot — Context & Handoff (COMPLETE for Phase 1 Gate 2 partial)

**Status:** ✅ **NIFTY LTP WebSocket + recovery CODED** (2026-06-07) — see **`NEW_CHAT_HANDOFF.md`**  
**Last updated:** 2026-06-07  
**Owner:** Rahul  
**Bot:** `@Drishti_Infrabot`

---

## 1. What DRISHTI does (locked)

| Responsibility | Status |
|----------------|--------|
| Dhan JWT delivery + validation | ✅ Live |
| NIFTY LTP on-demand (button + `/nifty_ltp`) | ✅ Live fetch when stale; cache when fresh |
| GIFT Nifty off-hours validation probe | ✅ **NEW** — polls when NSE closed |
| Token reminders (09:00 / 15:30 / 23:00 IST weekdays) | ✅ Coded |
| Market-hours health monitor (hourly LTP check) | ✅ Uses websocket |
| Fleet status (bots/modules) | ✅ Via **Fleet** button |
| AlgoScheduler prompts | 🔜 Not wired in standalone mode |

**Does NOT own:** trading commands, `/register`, `/pnl`, order placement.

---

## 2. Operator UI (final — approved by Rahul)

### Alive menu (only home screen — no Control Panel)

After `/start`, `/ping`, or any unknown message:

```
🟢 DRISHTI alive
29-May-2026 10:54:25 IST

[Health]     [Token Status]
[Update Token] [Deactivate]
[Fleet]      [Ping]
[LTP Feed Setup]
[Nifty LTP (Polling)]  [Nifty LTP (WebSocket)]
[GIFT Nifty (probe)]
```

**Removed:** Long "DRISHTI Control Panel" with slash-command list and Pro Tip.

### NIFTY LTP card (required format)

```
📈 NIFTY LTP
💰 Price: ₹23,879.45
🕒 As of: 29-May-2026 10:54:13 IST
📡 Source: Dhan websocket v2
```

### Update Token flow

1. Tap **Update Token** → bot says: *"Paste your Dhan JWT in this chat now."*
2. Paste JWT (no slash commands needed)
3. Bot validates with **live NIFTY LTP** before saving
4. Shows verified LTP card + alive menu

**Money-safe rule:** Token is **NOT saved** unless Dhan accepts it AND live NIFTY LTP fetch succeeds.

---

## 3. How to run (Windows)

| Action | Command / file |
|--------|----------------|
| **Start** | Double-click `Execution\Start Bots\start Drishti.bat` |
| **Stop** | Double-click `Execution\Stop Bots\stop Drishti.bat` |
| **Standalone** | `python run_drishti.py` |
| **Pre-flight check** | `python scripts\phase1_bot_check.py` |
| **Logs** | `logs/runtime/YYYY-MM/YYYY-MM-DD/drishti/logs/all.log` (see `LOGGING_LAYOUT.md`) |
| **NIFTY audit** | `…/drishti/logs/nifty_ltp/nifty_ltp_YYYYMMDD.log` |
| **GIFT audit** | `…/drishti/logs/nifty_ltp/gift_nifty_ltp_YYYYMMDD.log` |
| **Debug** | `python scripts/diagnose_robot.py drishti` — see `ROBOT_DEBUG_PROTOCOL.md` |

**Important:** Only one instance at a time (single-instance lock in `run_drishti.py`).

---

## 4. Key files changed this session

| File | Role |
|------|------|
| `bat_telegram/bots/drishti/bot.py` | UI, token validation, Nifty LTP button, alive menu |
| `core/nifty_ltp.py` | **NEW** — Dhan websocket v2 + REST fallback + subscription check |
| `run_drishti.py` | Standalone runner, logging, retries, single-instance lock |
| `scripts/stop_drishti.py` | **NEW** — reliable process stop |
| `scripts/phase1_bot_check.py` | Credential smoke test |
| `Execution/Start Bots/start Drishti.bat` | Auto-stop old instance, use venv python |
| `Execution/Stop Bots/stop Drishti.bat` | Calls stop script |
| `tests/test_nifty_ltp.py` | **NEW** — 5 unit tests (all pass) |
| `requirements.txt` | Added `dhanhq==2.2.0rc1` |

---

## 5. NIFTY LTP architecture (locked — updated 2026-06-02)

**Policy:** `NIFTY_LTP_POLICY.md` — DRISHTI is the **only** NIFTY LTP collector for production; GIFT is validation-only.

**Continuous feed (KAVACH/ATO path — NSE hours only):**
```
feed_mode=websocket (default):
  NiftyLtpWebSocketFeedService → Dhan WS v2 in-process → data/nifty_ltp_cache.json
  Runtime failover → REST for session if WS fails (config file unchanged)

feed_mode=rest:
  NiftyLtpFeedService → Dhan REST every 2s → same cache

KAVACH / ATO → resolve_nifty_ltp_from_cache ONLY (no broker LTP on trading path)
```

**Off-hours validation (does NOT feed KAVACH/ATO):**
```
GiftNiftyProbeService → Dhan REST GIFTNIFTY (ID 5024) every poll interval
  → data/gift_nifty_ltp_cache.json
  → gift_nifty_ltp_YYYYMMDD.log
```

**Telegram on-demand:**
```
Nifty LTP (Polling) → fresh cache during market; else live REST + validation warnings
GIFT Nifty (probe)  → off-hours live GIFT quote + audit
Nifty LTP (WebSocket) → one-shot diagnostic
Update Token        → validate LTP → seed_nifty_ltp_cache → restart feeds
```

**LTP Feed Setup (5 steps):**
1. Feed source (WebSocket / REST)
2. Poll interval (1/2/3/5s)
3. Unchanged-price JAGRAN alert (5–30s)
4. **Ping warning age** (10/15/20/30/45/60s — default **15**)
5. **Ping critical age** (30/45/60/90/120s — default **60**, must be ≥ warning + 15s)

**Stale-cache rules on user ping:**
- Never display cache older than warning threshold
- ≥ critical → JAGRAN incident `nifty_ltp_stale_cache`
- Invalid timestamp → critical + live fetch

**Auto-start:** First verified token creates `data/nifty_ltp_feed_config.json` if missing.  
**Watchdog:** `feed_watchdog_loop` restarts dead poller every 60s.

---

## 6. Smoke test evidence (2026-05-29)

| Test | Result |
|------|--------|
| DRISHTI Telegram getMe + send | ✅ PASS |
| `@Drishti_Infrabot` alive menu | ✅ PASS |
| Dhan fundlimit (after JWT refresh) | ✅ HTTP 200 |
| Dhan Data API subscription | ✅ (after Rahul subscribed) |
| NIFTY LTP websocket | ✅ ~₹23,879–23,906 |
| Token validate-before-save | ✅ Implemented |
| Unit tests `test_nifty_ltp.py` | ✅ 5/5 pass |
| Single-instance lock | ✅ Works |

### Issues resolved this session

| Issue | Fix |
|-------|-----|
| `TELEGRAM_BOT_TOKEN` ConfigError on standalone start | `run_drishti.py` loads only `DHAN_CLIENT_CODE` from `config/.env` |
| Telegram timeout on slow network | 30s timeouts + 3 retries |
| Multiple Drishti instances (409 Conflict) | Stop script + single-instance lock + start bat auto-stops |
| Invalid / expired Dhan JWT | Clear error + Update Token prompt |
| Data APIs not subscribed (806) | Clear error message; fixed after subscription |
| Tradehull REST empty LTP | Replaced with `core/nifty_ltp.py` websocket path |
| Verbose Control Panel UI | Removed — alive menu only |

---

## 7. Credentials (gitignored)

| File | Status |
|------|--------|
| `telegram/bots/drishti/token.env` | ✅ Configured |
| `config/.env` | ✅ `DHAN_CLIENT_CODE` set |
| `data/access_token.json` | ✅ Persisted JWT |

---

## 8. Prerequisites for NIFTY LTP

1. Valid Dhan JWT (paste via **Update Token** daily)
2. `DHAN_CLIENT_CODE` in `config/.env`
3. **Dhan Data API subscription** enabled on account
4. Market hours for best results (09:15–15:30 IST)

---

## 9. Next work (KAVACH register complete)

DRISHTI remains complete for Phase 1 standalone use. KAVACH register is done — see **`bat_telegram/bots/kavach/KAVACH_CONTEXT.md`**.

Next: JAGRAN standalone OR ATO module wiring (Gate 5).

See **`CONTEXT.md` §15** and **`PHASE1_IMPLEMENTATION_PLAN.md`**.

---

## 10. Related documentation

| File | Role |
|------|------|
| `CONTEXT.md` | Project master handoff |
| `bat_telegram/bots/kavach/KAVACH_CONTEXT.md` | KAVACH handoff (register complete) |
| `PHASE1_REQUIREMENTS.md` | Locked operator behavior |
| `PHASE1_DHAN_INTEGRATION.md` | LTP technical notes |
| `DHAN_API_CONTEXT.md` | **Dhan API scoped reference (orders, positions, LTP, SDKs)** |
| `NIFTY_LTP_POLICY.md` | Single collector / cache policy + GIFT validation |
| `LOGGING_LAYOUT.md` | Unified runtime log paths |
| `ROBOT_DEBUG_PROTOCOL.md` | Quick debug commands |
| `PHASE1_IMPLEMENTATION_PLAN.md` | 7-gate rollout |
| `PHASE1_OPEN_QUESTIONS.md` | Unresolved items |
| `telegram/design/drishti_design.md` | Original design spec |

---

*DRISHTI Phase 1 standalone: ROBOT-HARDENED. See §11–14. Next: Gate 5 + SARANSH.*

---

## 13. Stale-cache fix + GIFT probe + validation (2026-06-02)

| Capability | Implementation |
|------------|----------------|
| Cache seed on token save | `seed_nifty_ltp_cache()` in `_process_token` |
| Never show stale cache on ping | `assess_cache_for_user_ping()` + live REST fallback |
| Configurable ping thresholds | LTP Feed Setup steps 4–5 → `user_ping_warning_age_seconds` / `user_ping_critical_age_seconds` |
| GIFT Nifty probe | `core/gift_nifty_ltp.py`, `core/gift_nifty_probe.py`, button **GIFT Nifty (probe)** |
| Audit log format | `timestamp,ltp,source,event` — events: `poll`, `user_ping`, `user_ping_cache`, `token_save`, `probe` |
| JAGRAN stale cache incident | scenario `nifty_ltp_stale_cache` |

**GIFT Nifty (Dhan):** symbol `GIFTNIFTY`, security ID **5024**, segment `IDX_I`.

**Config file fields (new):**
```json
"user_ping_warning_age_seconds": 15,
"user_ping_critical_age_seconds": 60
```

**Tests:** `tests/test_nifty_ltp_validation.py`, `tests/test_gift_nifty_ltp.py`, `tests/test_drishti_feed_integration.py`.

---

## 14. Live test log (02-Jun-2026, off-market)

| Item | Result |
|------|--------|
| Bug: stale ₹23,497 after JWT refresh | Reproduced — cache 12.5h old, `feed_healthy: true` |
| Fix: live REST + seed | ₹23,382.6 written to cache |
| GIFT NIFTY live REST | ₹23,690.0 |
| GIFT probe auto-start | Starts with NIFTY feed restart |
| Cursor shell restarts | Exit code 1 when shell ends — use `.bat` for overnight |

**Ops:** Run `Execution\Start Bots\start Drishti.bat` (not Cursor background shell) for stable overnight operation.

**Resume:** Tap **GIFT Nifty (probe)** off-hours to confirm live ticks; tail `gift_nifty_ltp_*.log`.

---

## 11. Robot hardening summary (2026-06-01)

| Capability | Implementation |
|------------|----------------|
| REST retry + 429 backoff | `core/nifty_ltp.py`, `core/nifty_ltp_feed.py` |
| Rate-limit cooldown (no false JAGRAN) | `_handle_rate_limit()` in feed |
| Pre-start stale PID kill | `run_drishti.py` → `stop_bot_common` |
| Auto feed config on token save | `ensure_default_feed_config()` |
| Feed restart on token save | `restart_nifty_feed()` in `_process_token` |
| Deactivate → stop feed + unhealthy cache | `deactivate_ltp_feed()` |
| Feed task watchdog | `feed_watchdog_loop()` |
| JWT exp + effective expiry | `core/token_store.py` |
| Stale token monitor (standalone) | `_token_age_monitor_loop()` |
| TYPE 1 reminder suppression | `should_send_type1_token_reminder()` |
| Health includes LTP feed block | `_build_health_report_html()` |
| Telegram crash recovery | `run_drishti.py` restart loop |
| phase1 check: cache + process count | `scripts/phase1_bot_check.py` |

**Config:** `telegram/bots/drishti/params.json` → `nifty_ltp_feed` retry fields; persisted copy in `data/nifty_ltp_feed_config.json`.

**Tests:** `tests/test_drishti_robot.py`, `tests/test_drishti_feed_integration.py`, `tests/test_nifty_ltp.py`, `tests/test_nifty_ltp_feed.py`.

---

## 12. Live test log (01-Jun-2026)

Operator ran all Telegram buttons; agent reviewed runtime logs + nifty_ltp audit.

| Item | Result |
|------|--------|
| Ping / alive menu | ✅ |
| Nifty LTP (Polling) | ✅ cache-only replies |
| Health / Token Status | ✅ incl. JWT exp + feed block |
| WebSocket test | ✅ fundlimit OK |
| LTP cache during test | ₹23,522–23,533, all `ok` in nifty_ltp log |
| Single 429 at 12:54:02 | Recovered in ~10s via retry |
| **Ops issue** | 2× `run_drishti.py` PIDs → run **stop Drishti.bat** once, then **start** once |

**Resume:** Confirm `drishti_processes: 1` in phase1 check, then SARANSH (`CONTEXT.md` §17).

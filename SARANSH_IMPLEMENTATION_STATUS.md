# SARANSH — Implementation Status (Phase 1)

**Last updated:** 2026-06-07 (operator voided 2026-06-07 SARANSH Q&A — re-open wave)  
**Owner:** Rahul · **Agent session:** four-bot Phase 1 completion  
**Design authority:** `telegram/design/saransh_design.md` · **Handoff:** `bat_telegram/bots/saransh/SARANSH_CONTEXT.md`  
**Open Q&A:** `bat_telegram/bots/saransh/SARANSH_OPEN_QUESTIONS.md` (25 questions — **none validly answered yet**)

---

## Summary

| Phase | Scope | Status |
|-------|--------|--------|
| **P0** | Launcher (`run_saransh.py`, start/stop bats, menu skeleton) | ✅ **DONE** |
| **P1** | ATO JSONL + `ato_cycle_state.json` + mode paths | ✅ **DONE** |
| **P2** | KAVACH session hooks + auto SARANSH restart | ✅ **DONE** |
| **P3** | Feed ingest, ATO Cycle table, XLSX | ✅ **DONE** |
| **P4** | No JAGRAN routing; `is_trading_day` EOD; UAT PnL disclaimer | ✅ **DONE** |
| **P5** | pytest + bot checks | ✅ **DONE** (agent verification) |

**Overall SARANSH Phase 1 coding: ~95%** — remaining gaps need **fresh operator Q&A** (see `SARANSH_OPEN_QUESTIONS.md`) before next coding sprint. Gate 5 live UAT deferred until operator has a testing day (not office-work days).

---

## What SARANSH does now

1. **Optional 4th process** — started after JAGRAN via Phase 1 Start All (or `start Saransh.bat`).
2. **Telegram menu** (Non Critical Alerts chat):
   - **ATO Cycle** — today's round trips, CE/PE holding one-liners, signed point impact, net total; orders today + all-time when broker available.
   - **Daily Summary** — legacy telemetry + PnL recap + UAT disclaimer.
   - **Status** — session manifest, deployed time, mode, EOD schedule.
3. **Auto EOD** — **15:35 IST**, **trading days only** (`is_trading_day`).
4. **XLSX** — `data/{mode}/analytics/saransh/summary_YYYYMMDD.xlsx` on summary / ATO Cycle (Cycles, Session, LiveState sheets).
5. **Session sync** — KAVACH `/register` start wipes feeds; confirm + Batman Complete restart SARANSH **always** when token + enabled (even if manually stopped).
6. **No JAGRAN** — delivery failures log only + SARANSH chat; no incident fan-out.

---

## Key files (coded)

| Path | Role |
|------|------|
| `run_saransh.py` | Standalone runner, mode paths, broker optional |
| `Execution/Start Bots/start Saransh.bat` | Operator launcher |
| `Execution/Stop Bots/stop Saransh.bat` | Operator stop |
| `scripts/stop_saransh.py` | Process + lock cleanup |
| `bat_telegram/bots/saransh/bot.py` | Telegram handlers + EOD loop |
| `core/saransh_paths.py` | Mode-aware `data/uat/...` paths |
| `core/ato_cycle_feed.py` | KAVACH hot-path JSONL + state (also used by ATO module) |
| `core/saransh_session_sync.py` | Manifest, feed wipe, auto restart |
| `core/saransh_reporting.py` | Cold path: read feed → Telegram + XLSX |
| `modules/ato_protection.py` | Appends feed on BUY + cycle complete; mode telemetry paths |

---

## Data layout (UAT example)

```
data/uat/analytics/ato/ato_cycle_feed.jsonl
data/uat/analytics/ato/ato_cycle_state.json
data/uat/analytics/ato/ato_execution_telemetry.csv
data/uat/analytics/ato/ato_trade_ledger.csv
data/uat/analytics/session_manifest.json
data/uat/analytics/saransh/summary_YYYYMMDD.xlsx
data/uat/deployments/
```

---

## Tests (pytest)

| Module | File |
|--------|------|
| Paths | `tests/test_saransh_paths.py` |
| ATO feed | `tests/test_ato_cycle_feed.py` |
| Session sync | `tests/test_saransh_session_sync.py` |
| Reporting | `tests/test_saransh_reporting.py` |
| Daily ATO prompt (KAVACH) | `tests/test_daily_ato_prompt.py` |
| Halt notify spec | `tests/test_process_halt_notify.py` |

Run: `.venv\Scripts\python.exe -m pytest tests/test_saransh_*.py tests/test_ato_cycle_feed.py -q`

---

## Verification run (agent 2026-06-05)

- `pytest` SARANSH-related suite — **PASS**
- `scripts/audit_bot_tokens.py` — SARANSH **PASS**
- `scripts/phase1_bot_check.py` — includes SARANSH token check
- `optional_bot_enabled('saransh')` — **ok** (start bat present)

**Gate 5 remaining:** market-hours UAT with KAVACH ATO firing → confirm `ato_cycle_feed.jsonl` rows → SARANSH ATO Cycle button in Telegram.

---

## Deferred (not SARANSH)

| Item | When |
|------|------|
| Crash-exit on `run_*.py` + halt Telegram (OQ-P1-22) | After SARANSH sign-off |
| `data/prod/` layout | VPS |
| DRISHTI+KAVACH merge / websocket LTP | **Separate design wave** — see below |

---

## DRISHTI / KAVACH LTP (2026-06-07 — locked elsewhere)

Feed architecture **complete** — see `NEW_CHAT_HANDOFF.md`. **No SARANSH code changes** required for WS/failover/09:25 gate. SARANSH reads KAVACH analytics files only.

## Next operator wave: SARANSH implementation Q&A (re-open 2026-06-07)

1. Answer `SARANSH_OPEN_QUESTIONS.md` in batches of 5 (void all 2026-06-07 chat answers).  
2. Approve `docs/SARANSH_PHASE1_HANDOFF.md` (draft after Q&A complete).  
3. Operator says **Start coding**.  
4. Gate 5 market-hours UAT on a **dedicated testing day** (not office-work days).

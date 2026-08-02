# Phase 1 — Open Questions (Living Tracker)

Last updated: 2026-06-07 (SARANSH **implementation Q&A re-open** — void 2026-06-07 chat answers)  
Owner: Rahul

> Only **unresolved** questions live here. Answered items → **Resolved** table below.  
> **Four-bot Phase 1:** DRISHTI · KAVACH · JAGRAN · SARANSH — answer **5 questions per session** (`OQ-P1-xx`).  
> SARANSH design complete: `telegram/design/saransh_design.md`.

**Handoff docs:** `bat_telegram/bots/saransh/SARANSH_CONTEXT.md` · `telegram/design/saransh_design.md`  
**SARANSH re-open wave:** `bat_telegram/bots/saransh/SARANSH_OPEN_QUESTIONS.md` — **25 questions pending** (2026-06-07 void session)

> **End of day 2026-06-01.** DRISHTI robot hardening + live test complete. Resume: **CONTEXT.md §17** → clean single DRISHTI → SARANSH OQ-SAR-01…06.  
> **Valuation reference:** `METRICS_SUMMARY.md` §19 (complexity + India cost + AI ROI).

---

## 🟢 SARANSH — Q&A batches (5 per session)

**Mode:** Plan/design first → code when batches complete. **SANCHALAK out of scope.**

### ✅ Resolved session 1 (2026-06-05)

| ID | Topic | Resolution |
|----|-------|------------|
| OQ-SAR-Q1 | Startup | Optional 4th; Start All: DRISHTI → KAVACH → JAGRAN → **SARANSH last** |
| OQ-SAR-Q2 | Missing token | Skip + warn in `phase1_post_start_verify` (not blocking) |
| OQ-SAR-Q3 | Code strategy | Integrate existing `bot.py`; inventory in `saransh_design.md` |
| OQ-SAR-Q4 | Data pipeline | ATO: fast **JSONL + state JSON**; SARANSH: periodic **XLSX** (not Excel in KAVACH hot path) |
| OQ-SAR-Q5 | Cycles + UI | 1 BUY+1 SELL = 1 cycle; **ATO Cycle** button; CE/PE holding; total points lost today |

**Launcher wired:** `phase1_start_all.py` + `optional_bot_startup.py` (SARANSH launches when `enabled` + token + `start Saransh.bat` exist).

---

### ✅ Resolved session 2 (2026-06-05)

| ID | Topic | Resolution |
|----|-------|------------|
| OQ-SAR-10 | Point impact | **Signed point impact** per cycle: `sell_ltp − buy_ltp` on NIFTY spot (− = lost, + = gained). Show **per-cycle** (with **sell strike**) + **net total**. Label: **Point impact** (not “points lost” only). |
| OQ-SAR-11 | Open cycle UI | **B** — one line (e.g. `CE holding ATO since 14:02 IST`) inside ATO Cycle view |
| OQ-SAR-12 | Cross-day cycle | **A** — attribute cycle to **exit day**; points use **original buy LTP** from entry day |
| OQ-SAR-13 | Mode paths | **Mode-dedicated trees** — UAT under `data/uat/...`, prod under `data/prod/...`; **never mix**; same folder layout per mode |
| OQ-SAR-14 | Order counts | **B** — two lines: orders **today** + **all-time** in orderbook |

---

### ✅ Resolved session 3 (2026-06-05)

| ID | Topic | Resolution |
|----|-------|------------|
| OQ-SAR-15 | Telegram cycle detail | **D** — compact table for **all** today’s cycles (side, strike, buy, sell, point impact). Multi-message OK if needed. **Excel = every field** (picture-perfect). |
| OQ-SAR-16 | XLSX owner | **SARANSH only** builds workbook — heavy detail: timestamps, buy/sell, PnL, lots, strikes, triggers, order ids, etc. Telegram refined later. |
| OQ-SAR-17 | UAT PnL | **A** — include running PnL + disclaimer; system-calculated PnL (not Sensibull) is acceptable |
| OQ-SAR-18 | Session / cleanup | **KAVACH-owned** — see `saransh_design.md` § Batman Complete. KAVACH writes session manifest (`deployed_at`); on **Batman Complete** KAVACH cleans SARANSH feed + resets session epoch; SARANSH **Status** shows deploy time; no stale reads after complete. Fresh logs for all bots on complete → **OQ-SAR-25** (batch 4). |
| OQ-SAR-19 | Lots vs qty | **Lots only** in Telegram **and** Excel — project reporting uses **lots**, not broker qty |

---

### ✅ Resolved session 4 (2026-06-05)

| ID | Topic | Resolution |
|----|-------|------------|
| OQ-SAR-20 | Auto EOD | **B — 15:35 IST** (`params.json` + code default) |
| OQ-SAR-21 | Holidays | **`is_trading_day()`** + `NSE_HOLIDAYS_2026` in `core/utils.py` — **no auto EOD** on holidays/weekends; **manual menu always allowed** (post-market / mistake days) |
| OQ-SAR-22 | Paused KAVACH | **A — always allow** `/summary` and menu buttons |
| OQ-SAR-23 | Delivery / alerts | **SARANSH chat only** — summaries stay in SARANSH Telegram; standard `logs_{mode}/runtime/.../saransh/` logging; **no JAGRAN**, **no separate non-critical incident fan-out** for routine SARANSH messages |
| OQ-SAR-24 | Phase 1 behaviour | **Always running when started** — feed + XLSX accumulate; operator pulls update via **Telegram menu** on demand; agent validates Gate 5 + XLSX (not a separate operator “enable” milestone) |
| OQ-SAR-25 | Batman Complete | **New log session files** (rollover — **keep old logs** for analysis); wipe **state/positions/feeds** not history; **KAVACH restarts SARANSH** after Complete so it reads fresh session — mechanism → **OQ-SAR-26** |

**Design status (2026-06-05):** All SARANSH **design** Q&A complete (incl. OQ-SAR-26).  
**Implementation status (2026-06-07):** **Re-open** — operator voided SARANSH gap Q&A from chat after DRISHTI/KAVACH lock. See **`SARANSH_OPEN_QUESTIONS.md`** (OQ-SAR-REV-01…25). **No coding from void answers.**

---

### 🔴 SARANSH implementation Q&A — re-open (2026-06-07)

| ID | Status |
|----|--------|
| OQ-SAR-REV-01 … REV-25 | **UNANSWERED** — full catalogue in `bat_telegram/bots/saransh/SARANSH_OPEN_QUESTIONS.md` |
| Void session | All A/B/C answers in 2026-06-07 SARANSH Cursor chat — **ignore** |
| Next session | Q&A only · 5 questions/batch · **no testing** (operator office work) |
| Coding gate | Handoff doc approved + operator **Start coding** |

---

### ✅ Resolved — OQ-SAR-26 (session sync + automatic restart)

| ID | Topic | Resolution |
|----|-------|------------|
| OQ-SAR-26 | Restart mechanism | **Automatic** — KAVACH runs `scripts/stop_saransh.py` then starts `start Saransh.bat` (subprocess). **SARANSH** sends Telegram confirmation after restart (see design §3.1). |

**Session boundaries (operator 2026-06-05):**

| KAVACH event | Cleanup | SARANSH restart | SARANSH chat message |
|--------------|---------|-----------------|----------------------|
| **`/register` start** | Wipe stale feeds + prior cycle state (extend `prepare_uat_register_fresh` / `saransh_session_reset`) | No (wizard in progress) | — |
| **Register confirm** | New `session_manifest.json` (`status: armed`) | **Yes** | “New Batman session armed — SARANSH ready” + `deployed_at_ist` |
| **Batman Complete** | Full cleanup + log rollover + manifest `completed` | **Yes** | “Batman Complete — SARANSH restarted; awaiting /register” |

SARANSH must **never** show prior-session cycles/positions after register start or Complete.

---

## 🔴 Phase 1 four-bot — Q&A batches (DRISHTI · KAVACH · JAGRAN · SARANSH)

**SANCHALAK / LAKSHMI:** deferred (not this wave).

### ✅ Resolved batch 1 (2026-06-05)

| ID | Topic | Resolution |
|----|-------|------------|
| OQ-P1-01 | 4-bot scope | **A** — DRISHTI, KAVACH, JAGRAN, SARANSH locked in REQUIREMENTS, CONTEXT, AGENTS, cursor rule |
| OQ-P1-02 | Telegram chats | **B** — **Batman Alerts**: DRISHTI + KAVACH + JAGRAN; **Non Critical Alerts**: SARANSH only |
| OQ-P1-03 | Primary mode | **A** — **UAT primary** on laptop (`data/uat/`, shadow broker, Sensibull book) |
| OQ-P1-04 | Crash behaviour | **B** — process **exits on crash** (no infinite restart loop); operator restarts via Start bat; ATO HALT until explicit resume |
| OQ-P1-05 | Start All verify | **A** — **Core PASS** = DRISHTI + KAVACH + JAGRAN; SARANSH warn if skipped |

Also resolves legacy **OQ-G2-03** (chat topology).

---

### ✅ Resolved batch 2 (2026-06-05)

| ID | Topic | Resolution |
|----|-------|------------|
| OQ-P1-06 | JAGRAN stale cache | **A** — stale NIFTY cache → **warning** only (not critical) |
| OQ-P1-07 | DRISHTI laptop role | **A** — keep **REST LTP poll + JWT** |
| OQ-P1-08 | Daily 09:25 prompt | **B** — **skip in UAT**; no daily “run ATO today?” nag; operator uses manual resume / register flow |
| OQ-P1-09 | Health visibility | **A** — **Show Bot Status.bat** only (no DRISHTI fleet UI in Phase 1) |
| OQ-P1-10 | Gate 5 bots | **D** — **all four** bots mandatory RUNNING for Gate 5 evidence |

**Note:** OQ-P1-05 (Start All daily verify) stays **core trio PASS**; OQ-P1-10 applies to **Gate 5 / formal test** only.

---

### ✅ Resolved batch 3 (2026-06-05)

| ID | Topic | Resolution |
|----|-------|------------|
| OQ-P1-11 | Coding priority | **A** — SARANSH P0–P5 implementation first (operator approved full coding) |
| OQ-P1-12 | Gate 5 timing | **A** — Gate 5 only after SARANSH launcher + reporting path works |
| OQ-P1-13 | incident_severity | **A** — already aligned (stale cache = warning); no change |
| OQ-P1-14 | Prod layout | **A** — defer `data/prod/` until VPS |
| OQ-P1-15 | DRISHTI handlers | **A** — never touch Health/Ping/Token Status |

---

### ✅ Resolved batch 4 (2026-06-05)

| ID | Topic | Resolution |
|----|-------|------------|
| OQ-P1-16 | UAT skip 09:25 — when | **B** — immediate KAVACH patch (`core/daily_ato_prompt.py`; startup log in `run_kavach.py`) |
| OQ-P1-17 | KAVACH `/exit` | **B** — **removed**; use Pause/Resume + **Batman Complete** for session end |
| OQ-P1-18 | JAGRAN vs SARANSH EOD | **Custom** — JAGRAN **15:32 IST**, SARANSH **15:35 IST**, independent |
| OQ-P1-19 | Crash exit on `run_*.py` | **A** — after SARANSH P0–P5 |
| OQ-P1-20 | Mode-aware ATO paths | **A** — `data/{mode}/analytics/ato/` in SARANSH wave (`apply_ato_analytics_paths`) |

---

### ✅ Resolved batch 5 (2026-06-05)

| ID | Topic | Resolution |
|----|-------|------------|
| OQ-P1-21 | SARANSH restart if manually stopped | **A** — Batman Complete / register confirm **always** restart when token + enabled (`restart_saransh` stops then starts) |
| OQ-P1-22 | Crash-exit Telegram halt notice | **A** — one message before exit: core bots → Batman Alerts; SARANSH → Non Critical (`core/process_halt_notify.py`; wire in `run_*.py` after SARANSH) |
| OQ-P1-23 | Gate 5 broker evidence | **A** — **UAT shadow book only**; no live Dhan position requirement on laptop |

---

## 🔴 DEFERRED — SANCHALAK / LAKSHMI (not this wave)

### OQ-SAR-01 · SANCHALAK credentials

Operator will provide **SANCHALAK_BOT_TOKEN** + **SANCHALAK_CHAT_ID** tomorrow.

**Action:** Create `telegram/bots/sanchalak/token.env`, wire phase1 checks + optional startup.

---

### OQ-SAR-02 · LAKSHMI Phase 1 enablement

Operator confirmed **LAKSHMI** should be enabled for Phase 1 (non-critical tier, same alert path as SARANSH).

**Action tomorrow:** Confirm LAKSHMI token/chat; add to non-critical group; `enabled` switch + startup wiring.

---

### OQ-SAR-03 · Hedge box + register wizard (KAVACH)

Codebase has grown — **hedge box** logic and associated **register / position** questions need operator lock before final design.

**Action tomorrow:** Module-wise Q&A on hedge box at register time (when shown, confirm flow, Phase 1 in/out).

---

### OQ-SAR-04 · 5-year backtest architecture

Operator plan: fetch **1-minute candles from Dhan APIs**, run **full robot flow** end-to-end, compare manual vs algo results.

**Open engineering questions for tomorrow:**
- Historical replay runner vs live clock?
- Mock orders against replay LTP — same `ato_protection` path?
- How SARANSH defines “today” during replay (simulated session date)?
- Data storage path / cache for 5-year minute bars?

---

### OQ-SAR-05 · SARANSH implementation start

Design locked in `SARANSH_CONTEXT.md` §13. Pending tomorrow: confirm “start coding” after SANCHALAK + hedge box Q&A, or implement SARANSH shell first (UI, standalone, non-critical publisher).

**Locked already (no re-ask):** non-critical ≠ JAGRAN; cycle ledger; 15:30 EOD; trading-day calendar; KAVACH-style UI; optional startup; config `enabled` switches.

---

### OQ-SAR-06 · Non-critical shared chat ID for LAKSHMI

SARANSH summary + non-critical errors → group **Non Critical Alerts** (`-5163776252`). Confirm LAKSHMI uses **same group chat** for alerts when enabled.

---

## 🔴 BLOCKING — Gate 2 (before `main.py` starts)

### OQ-G2-01 · KAVACH Telegram credentials — ✅ RESOLVED 2026-05-29

Configured in `telegram/bots/kavach/token.env`. `@kavach_ATO_Bot` PASS in `phase1_bot_check.py`.

---

### OQ-G2-02 · JAGRAN Telegram credentials — ✅ RESOLVED 2026-05-29

Created `telegram/bots/jagran/token.env`. `@jagran_bot` PASS in `phase1_bot_check.py`.

---

### OQ-G2-04 · `main.py` three-bot smoke (NEW)

All three bots have valid tokens. **`python main.py` not yet smoke-tested** after laptop restart.

**Action:** After restart, run `main.py` and confirm DRISHTI + KAVACH + JAGRAN poll without crash.

---

## 🟡 Previously blocking — moved to resolved

### OQ-G2-03 · Single chat vs separate chats

Use **one Telegram chat** for DRISHTI/KAVACH/JAGRAN, or **separate chats** per bot?

- Default assumption: same operator chat ID for all three (simpler morning workflow)
- JAGRAN design intent: separate error channel — confirm if you want a different chat ID

---

## 🟡 GATE 1 — Pending market-hours evidence

### OQ-G1-01 · NIFTY LTP websocket smoke

Reference app failed off-market hours twice (~02:52 and ~03:00 IST, 2026-05-29):
- Error: `no close frame received or sent` (websocket closed)

**Action:** Re-run during **09:15–15:30 IST** before porting feed into Batman.

---

## 🟡 OPTIONAL — Low priority

### PQ-12 · Daily JWT time

What time do you usually send the Dhan token to DRISHTI? (For reminder tuning — optional)

---

## 🟡 ENGINEERING-DERIVED (resolve during implementation)

| ID | Topic | Plan |
|----|-------|------|
| EQ-01 | Stale NIFTY feed | Propose: no tick >30s → DRISHTI warn; websocket retry ≥5 → JAGRAN (per error matrix) |
| EQ-02 | GIFT NIFTY on token save | Review Dhan v2 docs + test with JWT; keep dual-check if API supports |
| EQ-03 | JAGRAN event set | Phase 1 = `JAGRAN_ERROR_MATRIX.md` DRISHTI + KAVACH rows; ATO success → KAVACH only |
| EQ-04 | Persistent vs poll websocket | Reference code reconnects each tick; Batman needs **persistent feed thread** for 1s ATO — see `PHASE1_DHAN_INTEGRATION.md` |

---

## 🟡 DEFERRED

### PQ-18 · VPS / auto-restart

**Superseded by `docs/BOT_LIFECYCLE_ARCHITECTURE.md` (2026-06-12).** Three tiers: (1) laptop hardening — partial; (2) `bot_supervisor.py`; (3) Linux systemd on VPS. Revisit implementation when starting BL-05.

---

## ✅ RESOLVED

| ID | Topic | Resolution | Date |
|----|-------|------------|------|
| PQ-R01–R16 | (sessions 1–2) | See PHASE1_REQUIREMENTS.md | 2026-05-29 |
| PQ-R17–R32 | (sessions 3–4) | Scheduler, wizard, crash, gap, JAGRAN /recent | 2026-05-29 |
| PQ-R33 | **PQ-22 Dhan docs** | https://docs.dhanhq.co/ + https://docs.dhanhq.co/api/v2/ + working code at `Dhan/Fetch LTP Working Code 09 Apr 26/NIFTY LTP With Access token only 09 Mar 26/` | 2026-05-29 |
| PQ-R34 | NIFTY instrument IDs | segment=0, security_id=13, request_code=15 (from reference) | 2026-05-29 |
| PQ-R35 | SDK for websocket | `dhanhq` MarketFeed v2; integrate alongside Tradehull for positions | 2026-05-29 |
| PQ-R36 | DRISHTI token/chat | `token.env` valid; `@Drishti_Infrabot` getMe OK; send_message OK | 2026-05-29 |
| PQ-R37 | Dhan JWT REST check | `fundlimit` HTTP 200; JWT exp ~24h from save time | 2026-05-29 |
| PQ-R39 | SARANSH Phase 1 Q&A | Non-critical tier; no JAGRAN; cycle ledger + XLSX; 15:30 EOD; trading-day; KAVACH UI; optional startup; 5-bot scope + LAKSHMI + SANCHALAK | 2026-05-30 |
| PQ-R40 | SARANSH non-critical group | Group **Non Critical Alerts** chat_id `-5163776252`; `@saransh_bm_bot` added; `token.env` updated | 2026-05-30 |
| PQ-R41 | 5-year test approach | Dhan API 1-min candles; full flow; manual vs algo comparison (details → OQ-SAR-04) | 2026-05-30 |
| PQ-R42 | SANCHALAK in SARANSH EOD | Include pause/mode status line — yes | 2026-05-30 |
| PQ-R43 | SARANSH Q1–Q5 session 1 | Optional 4th; after JAGRAN; JSON feed + ATO Cycle UI; integrate existing code | 2026-06-05 |
| PQ-R44 | SARANSH Q10–Q14 session 2 | Signed point impact; open cycle one-liner; cross-day exit-day; mode paths `data/uat/`; orders today+all-time | 2026-06-05 |
| PQ-R45 | SARANSH Q15–Q19 session 3 | Compact table Telegram; SARANSH-only heavy XLSX; UAT PnL disclaimer; KAVACH cleanup on Batman Complete; lots-only reporting | 2026-06-05 |
| PQ-R46 | SARANSH Q20–Q25 session 4 | EOD 15:35; is_trading_day auto skip; always allow manual; SARANSH-chat-only alerts; menu on demand; log rollover + SARANSH restart on Complete | 2026-06-05 |
| PQ-R47 | OQ-SAR-26 session sync | Auto stop/start SARANSH on Complete + register confirm; feed wipe on register start; SARANSH confirmation Telegram | 2026-06-05 |
| PQ-R48 | OQ-P1 batch 1 | 4-bot scope; chat tier B; UAT primary; crash exit B; Start All core PASS | 2026-06-05 |
| PQ-R49 | OQ-P1 batch 2 | JAGRAN stale=warning; DRISHTI LTP+JWT; UAT skip 09:25 prompt; health via Status bat; Gate5 all 4 bots | 2026-06-05 |
| PQ-R50 | OQ-P1 batch 3 | SARANSH coding first; Gate5 after SARANSH; prod defer; DRISHTI handlers locked | 2026-06-05 |
| PQ-R51 | OQ-P1 batch 4 | UAT 09:25 skip coded; /exit removed; JAGRAN 15:32 + SARANSH 15:35; crash exit after SARANSH; mode ATO paths | 2026-06-05 |
| PQ-R52 | OQ-P1 batch 5 | Always restart SARANSH on Complete; halt Telegram spec; Gate5 shadow-only | 2026-06-05 |

---

## 🎯 Current gate status

| Gate | Target | Status |
|------|--------|--------|
| 1 | NIFTY LTP | 🔜 Next — market-hours retest |
| 2 | Telegram bots | 🟡 Partial — DRISHTI only |
| 3 | Dhan positions API | Pending |
| 4 | KAVACH configured | Pending |
| 5 | ATO / choppy market test | Pending |
| 6 | Performance review | Pending |
| 7 | JAGRAN error reporting | Pending |

See checklists: `PHASE1_IMPLEMENTATION_PLAN.md`

---

## Foundation status

**Requirements: ~98%** · **Gate 1 coding: 0%** · **Gate 2: ~25% (DRISHTI only)** · **Overall Phase 1: ~18%**

---

*Update this file when questions close. Do not move resolved items back to open.*

# SARANSH Bot — Context & Handoff (Phase 1 enablement)

**Status:** 🟡 **~95% coded (2026-06-05)** — **implementation Q&A re-open** (2026-06-07) — see `SARANSH_IMPLEMENTATION_STATUS.md`  
**Last updated:** 2026-06-07 (session close — operator office day)  
**Authoritative design:** `telegram/design/saransh_design.md` (locks through OQ-SAR-26, **2026-06-05**)  
**Open implementation Q&A:** `bat_telegram/bots/saransh/SARANSH_OPEN_QUESTIONS.md` (**25 questions — all pending**)  
**Owner:** Rahul  
**Bot:** `@saransh_bm_bot` (id 8566818247)  
**Chat:** group **Non Critical Alerts** `-5163776252`

> **⚠️ 2026-06-07:** Operator voided all SARANSH Q&A answers from the chat that started after **DRISHTI/KAVACH feed finalization** (`NEW_CHAT_HANDOFF.md`). Those answers must **not** drive coding. Re-ask from **OQ-SAR-REV-01** (5 per batch).  
> **Tomorrow:** Q&A / handoff doc only — **no Gate 5 testing** (office work).  
> **Resume:** *"Continue SARANSH from SARANSH_OPEN_QUESTIONS.md Batch 1"* + `reference/REQUIREMENTS_QA_MASTER_PROMPT.md` format.  
> **No coding** until operator says **"Start coding"** after handoff doc approved.

### Valid baseline (unchanged)

| Layer | Source | Date |
|-------|--------|------|
| SARANSH design locks | `saransh_design.md` · `PHASE1_OPEN_QUESTIONS.md` OQ-SAR-Q1…26 | 2026-06-05 |
| DRISHTI/KAVACH feed architecture | `NEW_CHAT_HANDOFF.md` · `NIFTY_LTP_POLICY.md` | 2026-06-07 |
| Code on disk | P0–P5 per `SARANSH_IMPLEMENTATION_STATUS.md` | 2026-06-05 |

---

## 0.1 Operator decisions locked 2026-06-05 (session 1)

| Topic | Decision |
|-------|----------|
| **Q1 Startup** | Optional 4th bot; Phase 1 Start All runs **SARANSH after JAGRAN** |
| **Q2 Missing token** | Skip + **warn** in post-start verify (not blocking) |
| **Q3 Code** | **Integrate existing** `bot.py` — verify inventory in `saransh_design.md` §4 |
| **Q4 Feed** | KAVACH writes **fast JSONL + state JSON**; SARANSH owns **periodic XLSX** (not Excel in ATO hot path) |
| **Q5 Cycles** | 1 BUY + 1 SELL = 1 cycle; Telegram **ATO Cycle** button; CE/PE holding status; total points lost today |
| **SANCHALAK** | **Out of scope** this wave |

**Session 2 locked:** signed point impact (Q10); open cycle one-liner (Q11); cross-day exit-day (Q12); `data/uat/` paths (Q13); orders today+all-time (Q14).

**Session 3 locked:** compact table Telegram (Q15); SARANSH-only heavy XLSX (Q16); UAT PnL disclaimer (Q17); KAVACH cleanup + session manifest (Q18); lots-only (Q19).

**Session 4 locked:** EOD 15:35; holiday calendar; manual always; SARANSH-chat-only; log rollover + SARANSH restart on Complete.

**OQ-SAR-26 locked:** auto stop/start SARANSH on Complete + register confirm; feed wipe on `/register` start; confirmation Telegram after restart.

Coding: `saransh_design.md` §3.1 + §8. New helper: `core/saransh_session_sync.py`.

---

## 0. Why we are doing this (operator intent — 2026-05-30)

During Phase 1 Gate 5 (ATO / choppy market) testing, manually checking order counts, ATO re-entries, and entry/re-entry point loss is not practical. **SARANSH** was built as the end-of-day (and on-demand) **reporting bot** to automate that recap.

**Operator goal for this workstream:**

1. Complete **code review** of existing SARANSH implementation (coding largely done).
2. Discuss **edge cases** and answer open questions **before** any integration coding.
3. Bring SARANSH to the **same architecture / quality bar** as DRISHTI, KAVACH, JAGRAN (context file, phase1 checks, start/stop bats, modular patterns).
4. **Enable SARANSH in Phase 1** — locked (non-critical tier).
5. Credentials on disk — `telegram/bots/saransh/token.env` ✅

**Session state (2026-05-30 close):** Q&A locked. **No SARANSH coding yet.** Next: SANCHALAK token, hedge box Q&A, 5-year replay design → then implement. See §13–15.

---

## 13. Locked operator Q&A (2026-05-30)

### Phase 1 scope (UPDATED)

| Bot | Tier | Phase 1 |
|-----|------|---------|
| DRISHTI | Critical | ✅ |
| KAVACH | Critical | ✅ |
| JAGRAN | Critical alerts | ✅ mandatory startup |
| SANCHALAK | Critical control | ✅ **enable for 5-year / end-to-end testing** |
| SARANSH | Non-critical reporting | ✅ optional startup (`enabled` + token) |
| LAKSHMI | Non-critical | Later — same non-critical alert path when enabled |

**Deployment philosophy:** Each bot has `params.json` → `"enabled": true/false`. Operator toggles without code changes. Optional bots skip startup when disabled or missing `token.env`.

### Critical vs non-critical incident routing (PERMANENT)

| Tier | Bots | Telegram destination | Ledger |
|------|------|---------------------|--------|
| **Critical** | DRISHTI, KAVACH, MAIN, JAGRAN | **Batman Alerts** group (JAGRAN) | `data/analytics/incidents/` |
| **Non-critical** | SARANSH, LAKSHMI (future) | **Separate non-critical group** (operator to create) | `data/analytics/incidents/non_critical/` (CSV + XLSX) |

- **SARANSH must NOT route to JAGRAN** — confirmed intentional; old May-17 dual-route design superseded.
- SARANSH delivery failures → non-critical tracker + non-critical Telegram group only.
- JAGRAN and SARANSH incident paths are **completely separate**.

### Q&A answers (mapped to original questions)

| # | Question | Operator answer (locked) |
|---|----------|--------------------------|
| Q1 | Phase 1 bots | **DRISHTI + KAVACH + JAGRAN + SANCHALAK + SARANSH** for end-to-end / 5-year testing |
| Q2 | SARANSH startup | **Optional** — must not block whole process if missing/disabled |
| Q3 | ATO cycle metric | **Completed ATO cycles** from full ledger logic — see Section 14 |
| Q4 | Excel | **Yes** — separate XLSX per bot under SARANSH analytics; cycle + points lost |
| Q5 | Summary chat | **Dedicated SARANSH chat** — NOT KAVACH chat |
| Q6 | `/summary` while paused | **Yes, should work** (reporting bot; pause must not block recap) |
| Q7 | Auto EOD time | **15:30 IST** (align with JAGRAN) |
| Q8 | Non-trading / holidays | **Quiet** — no auto summary; use `is_trading_day()` not weekday-only |
| Q9 | JAGRAN recap in SARANSH | **No** — keep critical and reporting separate |
| Q10 | SANCHALAK in report | Not explicitly required in EOD text (TBD if status line needed) |

### Report content (locked)

1. **Order counts — both:**
   - Total orders in full orderbook (broker)
   - Orders executed **today** (separate line)
2. **Lot / qty:** Terminal shows **qty**; UI shows **lots**; 1 lot = **65 qty** (KAVACH params — same logic as KAVACH)
3. **Deployment:** Use **confirmed** deployment from KAVACH (`deployment.confirmed` + state file path) — not “latest JSON by sort”
4. **ATO cycles:** Full cycle ledger — entry → exit = 1 complete cycle; open entry without exit = **incomplete** (report explicitly)
5. **Cross-day cycles:** If BUY today, SELL tomorrow → carry forward in ledger; on exit, record with original entry timestamp + exit timestamp + points lost spanning days
6. **Points lost:** Authoritative from **ATO trade ledger** side-aware logic (`ato_trade_ledger.csv`), not telemetry shortcut
7. **UI:** **Same pattern as KAVACH/DRISHTI** — alive menu + buttons (not slash-only help wall)
8. **Credentials / loader / standalone runner / start-stop bats:** Same ops pattern as other Phase 1 bots

### Trading-day calendar (cross-bot)

- Re-enable / use `core.utils.is_trading_day()` in **KAVACH** schedulers and **SARANSH** EOD (replace weekday-only check)
- Applies to all bots that schedule market-hours behavior

### Implementation backlog (post-lock)

1. `non_critical_incident_publisher` (or tier flag on existing publisher) + folder + XLSX
2. SARANSH ledger module + daily XLSX (`data/analytics/saransh/`)
3. Ingest `ato_trade_ledger.csv` + incomplete-cycle state file
4. Remove JAGRAN calls from SARANSH delivery path
5. `run_saransh.py`, bats, button UI, `enabled` gate in startup
6. SANCHALAK `token.env` + phase1 checks
7. Update `PHASE1_REQUIREMENTS.md`, `CONTEXT.md`, cursor rules → 5-bot scope
8. Pytest for cycle parsing + summary payload

---

## 14. Q3 explained (plain English) — ATO cycle counting

**What you asked for:** “How many times did ATO complete a full round?”

Think of one **cycle** as a round trip:

```
BUY protect (entry)  →  market moves  →  SELL protect (exit)  =  1 complete cycle
```

**Examples:**

| What happened | Cycle count | Report says |
|---------------|-------------|-------------|
| 1 BUY + 1 SELL same day | 1 complete | Cycle 1 closed; points lost = X |
| 2 BUY/SELL round trips in one day | 2 complete | Cycle 1 + Cycle 2 |
| BUY at 2pm, no SELL yet | 0 complete, **1 open** | “Cycle 2: entry open since 14:02 IST” |
| BUY Monday, SELL Tuesday | 1 complete (cross-day) | Entry Mon timestamp; exit Tue; points lost on close |

**Separate from cycles — raw order count:**

- **Telemetry rows** = every BUY and SELL event (can be 4 rows for 2 cycles)
- **Cycle count** = completed round trips only (what you want for “how many times ATO ran end-to-end”)

SARANSH will show **both**: event counts in telemetry **and** completed/open cycles from the ledger.

---

## 15. Remaining clarifications — session close 2026-05-30

| # | Status |
|---|--------|
| R1 Non-critical group | ✅ **Non Critical Alerts** `-5163776252` — SARANSH added, `token.env` updated, send test PASS |
| R2 SARANSH summary chat | ✅ Same non-critical dedicated group (not KAVACH private) |
| R3 SANCHALAK token | 🔜 **Tomorrow** — see `PHASE1_OPEN_QUESTIONS.md` OQ-SAR-01 |
| R4 5-year backtest | ✅ Dhan API 1-min candles, full flow, manual vs algo — engineering details OQ-SAR-04 |
| R5 SANCHALAK in EOD | ✅ Include pause/mode status line |

**Tomorrow agenda:** SANCHALAK credentials · LAKSHMI enable · hedge box register Q&A · 5-year replay design · SARANSH coding kickoff (after locks).

---

## 1. What SARANSH does (locked design — already in code)

| Responsibility | Status |
|----------------|--------|
| Consolidated execution summary (orders, ATO, PnL, impact) | ✅ coded |
| Manual trigger `/summary` and `/summary_eod` | ✅ coded (same handler) |
| Auto EOD summary at configurable IST time (default **15:35**) | ✅ background loop |
| Dual delivery: **Telegram message + file log** every run | ✅ coded |
| JAGRAN incident on partial/full delivery failure | ✅ via `publish_incident` |
| Auto-resolve incident when both channels recover | ✅ coded |
| Read KAVACH ATO telemetry CSV for today | ✅ coded |
| Token-status ops addendum (from DRISHTI `access_token.json`) | ✅ coded |
| Paused-bot guard on `/summary` (read-only `/status` allowed) | ✅ coded |
| Excel / XLSX export of summary | ❌ **not implemented** (text log only) |
| Dedicated `SARANSH_CONTEXT.md` before this file | ✅ this file |
| Phase 1 bot checks / audit scripts | ❌ not wired |
| Start/Stop `.bat` launchers | ❌ not present |
| Standalone runner (`run_saransh.py`) | ❌ not present (starts via `main.py` only) |
| Pytest coverage | ❌ no tests found |

**Does NOT own:** trading, registration, ATO execution, incident board (JAGRAN owns alerts).

---

## 2. Summary report contents (v1 — from `bot.py`)

Each run produces a compact text report with:

| Section | Source |
|---------|--------|
| Deployment file + algo paused state | `data/deployments/batman_*.json` (latest) |
| Total broker orders today | `broker.get_orderbook()` |
| Total ATO orders today | row count in telemetry CSV for today |
| **Entry/re-entry points lost** | sum of `abs(nifty_ltp - sell_strike)` for `BUY entry` rows |
| Running PnL, one-lot equivalent, deployed lots, PnL % | broker + deployment |
| ATO split by side/action | telemetry `side` + `action` |
| Trigger mix | telemetry `trigger_reason` |
| Time density (hour buckets) | telemetry timestamps |
| Strike recap (top 3 contexts) | sell/trigger/protect strike strings |
| Ops addendum | JWT token age / reminder windows |

**Output paths:**

- Telegram → `SARANSH_CHAT_ID` from `telegram/bots/saransh/token.env`
- File → `data/analytics/saransh/summary_YYYYMMDD.log` (append per run)

**Telemetry input:**

- `data/analytics/ato_execution_telemetry.csv` (written by `modules/ato_protection.py`)
- Soft-fail if missing: report still sends with "Telemetry: missing" note

---

## 3. Commands (canonical — aliases removed)

| Command | Behavior |
|---------|----------|
| `/start` | Intro + help |
| `/summary` | Generate summary now (manual) |
| `/summary_eod` | Same as `/summary` (manual EOD-style) |
| `/status` | Deployment armed/idle, telemetry present/missing, auto EOD time |

**Read-only while paused:** `start`, `help`, `status`  
**Blocked while paused:** `/summary`, `/summary_eod`

---

## 4. Architecture & file map

```
bat_telegram/bots/saransh/
  bot.py              ← main runtime (413 lines)
  __init__.py
  SARANSH_CONTEXT.md  ← this handoff file

telegram/bots/saransh/
  params.json         ← schedule, summary_v1 toggles, enabled=true
  token.env.example   ← SARANSH_BOT_TOKEN, SARANSH_CHAT_ID
  config.json         ← deprecated pointer to params.json
  token.env           ← NOT PRESENT YET (operator to provide)

main.py               ← optional start if token.env exists (_has_bot_secrets)
bat_telegram/loader.py
bat_telegram/control.py          ← guard_paused_command
bat_telegram/incident_publisher.py ← summary_delivery_failure scenario
modules/ato_protection.py        ← writes ato_execution_telemetry.csv
simulator/app.py                 ← SARANSH wired in five-bot simulator
```

**Startup model today:**

- `main.py` starts SARANSH **optionally** when `telegram/bots/saransh/token.env` exists.
- JAGRAN is **mandatory**; SARANSH is **optional** (unlike operator's desired Phase 1 inclusion).
- No standalone `run_saransh.py` (JAGRAN/KAVACH/DRISHTI have standalone runners + Execution bats).

**Locked design decisions** (see `reference/DECISION_REGISTER.md`):

- Dual delivery Telegram + file every run
- JAGRAN escalation on either channel failure with per-channel detail
- SARANSH owns EOD schedule (not SANCHALAK)
- Auto-EOD + manual `/summary` / `/summary_eod`
- ATO impact: points + one-lot money + total-lot view + PnL %

---

## 5. Gap analysis vs Phase 1 robots (DRISHTI / KAVACH / JAGRAN)

| Pattern | DRISHTI/KAVACH/JAGRAN | SARANSH today |
|---------|----------------------|---------------|
| `*_CONTEXT.md` handoff | ✅ | ✅ (this file) |
| `token.env` on disk | ✅ | ❌ pending operator |
| `scripts/audit_bot_tokens.py` | 3 bots only | ❌ not included |
| `scripts/phase1_bot_check.py` | 3 bots only | ❌ not included |
| `Execution/Start Bots/*.bat` | ✅ per bot | ❌ missing |
| Standalone runner | ✅ `run_*.py` | ❌ main.py only |
| Pytest | ✅ broad | ❌ none for saransh |
| `.cursor/rules/batman-phase1.mdc` | 3-bot scope | SARANSH listed out-of-scope |
| `PHASE1_REQUIREMENTS.md` | 3 bots | SARANSH out-of-scope |
| Excel export | JAGRAN has CSV/XLSX ledger | ❌ SARANSH text log only |

**Code quality note:** `bot.py` is self-contained (~400 lines), uses shared loader/control/incident patterns, async EOD loop, `asyncio.to_thread` for blocking broker/IO — structurally aligned with other bots but **not yet validated** at OPS level (`IMPLEMENTATION_TRACKER.md`: `OPS_VALIDATION_PENDING`).

---

## 6. Phase 1 integration — proposed scope (pending Q&A)

When operator confirms after edge-case discussion:

1. Add `telegram/bots/saransh/token.env` (operator provides credentials).
2. Extend `audit_bot_tokens.py` + `phase1_bot_check.py` to include `saransh`.
3. Add `run_saransh.py` + `Execution/Start Bots/start Saransh.bat` + stop bat (match JAGRAN pattern).
4. Update `PHASE1_REQUIREMENTS.md`, `CONTEXT.md`, `.cursor/rules/batman-phase1.mdc`, `AGENTS.md` — **4-bot Phase 1** (DRISHTI, KAVACH, JAGRAN, SARANSH).
5. Decide Excel/XLSX: extend SARANSH or reuse JAGRAN ledger patterns?
6. Add pytest for summary payload computation (telemetry parsing, impact_points, soft-fail).
7. Gate 5 validation: run ATO sim → verify telemetry → `/summary` → check file + Telegram.

**SANCHALAK remains out of Phase 1** unless operator changes scope again.

---

## 7. Code review (complete — 2026-05-30)

### Completion estimate: ~75% coded, ~25% integration/hardening

| Area | Status |
|------|--------|
| Core summary logic (`_compute_summary_payload`, `_render_summary`) | ✅ Done |
| DESIGN.md v1 metrics (orders, ATO count, impact, PnL, token addendum) | ✅ Done |
| DESIGN.md derived telemetry metrics (side split, trigger mix, density, strike recap) | ✅ Done |
| Dual delivery + incident on failure | ✅ Coded |
| Auto EOD scheduler | ✅ Coded |
| `ato_trade_ledger.csv` ingestion (cycle_index, proper points_lost) | ❌ Not wired |
| Excel/XLSX summary export | ❌ Not wired (ATO module already exports ledger XLSX snapshots) |
| JAGRAN routing for `summary_delivery_failure` | ❌ **Bug** — not in allowlist |
| Phase 1 ops parity (standalone, bats, audit scripts, pytest) | ❌ Missing |
| `params.json` summary_v1 toggles | ⚠️ Defined but **ignored** in code |
| `is_trading_day()` for EOD | ❌ Uses weekday only, not holiday calendar |

### Implemented well

- Telemetry ingestion with IST date filter and tolerant timestamp parsing
- Soft-fail when telemetry missing/empty (report still sends)
- `asyncio.to_thread` for blocking broker/CSV reads
- Dual-channel delivery with structured incident + recovery path
- EOD once-per-day guard; weekend skip
- Shares loader, control, incident_publisher patterns with other bots

### Bugs / inconsistencies found

1. **JAGRAN allowlist — intentional (2026-05-30):** SARANSH **must not** route to JAGRAN. Remove existing `publish_incident` / `resolve_incident` calls from SARANSH; use non-critical publisher instead.

2. **Pause semantics mismatch (MEDIUM):** `guard_paused_command` checks `control.paused_apps` (SANCHALAK per-bot pause). Summary shows `algo.paused` (KAVACH pause/resume). Phase 1 has no SANCHALAK — so `/summary` is effectively **never blocked** by KAVACH algo pause. Report may show `Algo paused: no` while KAVACH is paused.

3. **Impact points calculation differs from ATO ledger (MEDIUM):** SARANSH sums `abs(nifty_ltp - sell_strike)` on BUY entry rows in telemetry. ATO module records **`points_lost`** per completed cycle in `ato_trade_ledger.csv` using side-aware logic (CE: entry_spot − exit_spot; PE: exit_spot − entry_spot). These numbers can disagree. Ledger also has `cycle_index`, `points_lost_x_lots` — richer than telemetry-only view.

4. **Lot size default wrong (LOW):** `config.get("strategy.lot_size", 1)` defaults to 1; Phase 1 NIFTY lot size is 65. If global config lacks this key, one-lot normalization will be wrong.

5. **Deployment file detection (LOW):** Uses latest `batman_*.json` by sort order, not state `deployment.file` or confirmed armed status — could report wrong deployment after cleanup.

6. **Order count not filtered to today (LOW):** `total_orders = len(orderbook.index)` — entire orderbook, not today-only.

7. **`params.json` toggles unused (LOW):** `summary_v1.include_*` flags exist but `_render_summary` always includes all sections.

8. **No Telegram message length guard (LOW):** Long strike recaps could hit 4096 char limit on busy ATO days.

### Excel — what already exists elsewhere

- **JAGRAN:** daily incident ledger CSV + XLSX export (`ledger.py`, `incident_publisher.py`)
- **ATO module:** writes `ato_trade_ledger.csv` and snapshot XLSX with `Ledger` + `DailySummary` sheets (cycles, points_lost sums) — SARANSH does **not** read or reference this today

**Recommendation for Q&A:** Either SARANSH ingests `ato_trade_ledger.csv` as authoritative for cycles/points, or SARANSH adds its own daily summary XLSX mirroring the Telegram text.

### Architecture comparison vs JAGRAN/KAVACH

| Pattern | JAGRAN/KAVACH | SARANSH |
|---------|---------------|---------|
| Modular split (`ledger.py`, etc.) | ✅ | ❌ monolithic `bot.py` |
| Standalone `run_*.py` + lock file | ✅ | ❌ |
| Start/Stop bats | ✅ | ❌ |
| Button menu UI | ✅ | ❌ slash-only (OK for reporting bot?) |
| Background scheduler | ✅ EOD 15:30 | ✅ EOD 15:35 |
| Phase 1 audit scripts | ✅ | ❌ |
| Pytest | ✅ | ❌ |
| MarkdownV2 | JAGRAN uses HTML | Plain text (OK) |

### Operator speech note: "how many times the ATO user created"

Not in current SARANSH code. Closest existing metrics:

- `total_ato_orders` — telemetry row count today
- `action_counter` — split by CE/PE × BUY entry / SELL exit
- `ato_trade_ledger.csv` — **`cycle_index`** per side (completed entry→exit cycles)

**Likely intent:** count of ATO **cycles** (entry + re-entry rounds) — needs ledger ingestion or explicit cycle counter in report.

---

## 8. Open questions — RESOLVED (see Section 13)

All original Q1–Q10 answered 2026-05-30. Remaining items: Section 15 (R1–R5).

---

## 9. Credentials (configured 2026-05-30)

File: `telegram/bots/saransh/token.env` (gitignored)

- Bot: `@saransh_bm_bot`
- Chat ID: `-5163776252` (group **Non Critical Alerts** — verified send 2026-05-30)
- Audit: `scripts/audit_bot_tokens.py` includes SARANSH — all checks passed
- Smoke: `scripts/phase1_bot_check.py` includes SARANSH — PASS

Re-fetch chat_id after `/start`: `.venv\Scripts\python.exe scripts\fetch_bot_chat_id.py saransh`

---

## 10. Resume checklist (next session)

- [x] Operator answers Section 8 questions (2026-05-30)
- [x] Operator provides `token.env` (2026-05-30)
- [ ] Agent delivers **full code review** (bot.py, incident wiring, telemetry contract, simulator)
- [ ] Agent compares SARANSH output against a real Gate 5 ATO test day
- [ ] Implement integration gaps from Section 6 (only after Q&A locked)
- [ ] Run quality gates + extend phase1 checks
- [ ] Update `CONTEXT.md`, `PHASE1_REQUIREMENTS.md`, `IMPLEMENTATION_TRACKER.md`, `SESSION_CAPTURE_LOG.md`

---

## 11. Key references

| Doc | Relevance |
|-----|-----------|
| `bat_telegram/bots/saransh/bot.py` | Runtime implementation |
| `telegram/bots/saransh/params.json` | Schedule + summary toggles |
| `reference/DECISION_REGISTER.md` | Locked SARANSH decisions (2026-05-17) |
| `IMPLEMENTATION_TRACKER.md` | Row: SARANSH summary bot — OPS_VALIDATION_PENDING |
| `JAGRAN_ERROR_MATRIX.md` | `summary_delivery_failure` scenario |
| `kavach-2.0/bat_telegram/bots/kavach2/KAVACH_CONTEXT.md` | Pattern for context file quality |
| `bat_telegram/bots/jagran/JAGRAN_CONTEXT.md` | Pattern for standalone + bats + XLSX |
| `GATE5_RUNBOOK.md` | ATO test procedure — SARANSH validates after Gate 5 runs |
| `PHASE1_REQUIREMENTS.md` | Currently lists SARANSH out-of-scope — update after lock |

---

## 12. Related tracker status (snapshot)

From `IMPLEMENTATION_TRACKER.md`:

- **SARANSH summary bot:** `OPS_VALIDATION_PENDING` — validate manual/auto EOD, paused behavior, JAGRAN channel-failure alerts
- **Runtime code exists:** `main.py` optional wiring when secrets present
- **Simulator:** five-bot interlinks include SARANSH

---

*End of handoff — resume conversation with: "Continue SARANSH Phase 1 enablement from SARANSH_CONTEXT.md"*

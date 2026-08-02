# Phase 1 Daily Log — 2026-05-29 (Day 1)

Owner: Rahul  
Facilitator: Architecture discovery session (Cursor Agent)

---

## Session summary

**Theme:** Requirements-first discovery — no Batman core code refactors today.

We established Phase 1 scope (3 Telegram bots: **DRISHTI, KAVACH, JAGRAN**), locked operator requirements in plain English, mapped gaps vs existing codebase, and prepared for **Target #1: consistent NIFTY LTP fetch via Dhan websocket**.

---

## Decisions locked today

| Area | Decision |
|------|----------|
| **Scope** | DRISHTI + KAVACH + JAGRAN only; LAKSHMI comment out (preserve code) |
| **Registration** | Once per week via KAVACH `/register`; legs persist full week |
| **Day 1 confirm** | ATO monitoring starts immediately after Confirm + startup scan |
| **Daily gate** | Each trading day 09:25 IST: "Run ATO today?" Yes/No; no reply = no run |
| **Schedule** | Start 09:25 IST, end 15:15 IST (config-driven) |
| **Exit features** | Remove `/exit`, emergency watchdog — manual Dhan exit only |
| **Orders (laptop)** | Simulated only; read live positions; no orders (static IP rule) |
| **LTP feed** | Dhan websocket v2; reference code in `Dhan/Fetch LTP Working Code...` |
| **NIFTY instrument** | segment=0, security_id=13, request_code=15 |
| **DRISHTI health** | Check every 1 minute |
| **Crash** | Alert JAGRAN + HALT; no auto-resume |
| **Gap open** | Operator handles manually; normal ATO from 09:25 |
| **Wizard** | Keep existing buffer/retrace/poll prompts; remove break-even + calendar only |
| **JAGRAN** | Separate chat; errors only; add `/recent` |
| **Dev path** | Skip Flask simulator; Dhan websocket on laptop first; VPS later |

---

## Code / config changes today

| Change | Path | Notes |
|--------|------|-------|
| Created broker env | `config/.env` | gitignored — client_id + JWT |
| Token persistence | `data/access_token.json` | gitignored — TokenStore format |
| Reference LTP token | `Dhan/.../config/token.txt` | gitignored path under Dhan folder |
| Phase 1 requirements | `PHASE1_REQUIREMENTS.md` | Operator source of truth |
| Open questions | `PHASE1_OPEN_QUESTIONS.md` | Living tracker |
| Dhan integration notes | `PHASE1_DHAN_INTEGRATION.md` | Websocket + reference analysis |
| Context pointer | `CONTEXT.md` | Phase 1 scope override |

**Not changed today (Day 1 AM):** `main.py`, `core/broker.py`, ATO module wiring, AlgoScheduler integration.

**Changed today (Day 1 late session):**

| Change | Path | Notes |
|--------|------|-------|
| DRISHTI UI restore | `bat_telegram/bots/drishti/bot.py` | Compact 6-button menu; post-token alive card; fixed emoji mojibake in callbacks |
| Bot credential check | `scripts/phase1_bot_check.py` | Validates DRISHTI/KAVACH/JAGRAN without printing secrets |
| Alive menu helper | `scripts/send_drishti_alive.py` | Dev script to push alive card to Telegram |

---

## Smoke test evidence

| Test | When | Result |
|------|------|--------|
| Reference LTP app `main.py --once` | ~02:52 IST | **FAIL** — websocket closed (`no close frame`) — likely off-market hours |
| Reference LTP app `main.py --once` | ~03:00 IST | **FAIL** — same (retried late session) |
| DRISHTI Telegram getMe + send | ~03:00 IST | **PASS** — `@Drishti_Infrabot` |
| KAVACH token.env load | ~03:00 IST | **FAIL** — placeholder values only |
| JAGRAN token.env | ~03:00 IST | **FAIL** — file missing |
| Dhan REST `fundlimit` | ~03:00 IST | **PASS** — JWT valid |
| `run_drishti.py` startup | ~03:07 IST | **PASS** — Application started, polling |
| DRISHTI alive menu sent | ~03:07 IST | **PASS** — message delivered with 6-button keyboard |

**Retry LTP tomorrow** during market hours (09:15–15:30 IST).

---

## Topics discussed (conversation arc)

1. Full codebase discovery (architecture, simulator, tests, gaps)
2. Phase 1 scope narrowed to 3 bots
3. Q&A sessions A–D (register, ATO, pause, scheduler, wizard)
4. Q&A sessions on crash, gap, JAGRAN, dev mode
5. Dhan docs + working LTP project review
6. JWT stored in gitignored config for tomorrow's dev

---

## Tomorrow morning — Target #1

**Goal:** Fetch NIFTY LTP **consistently** via Dhan websocket on laptop.

**Also before `main.py`:** Fill KAVACH + JAGRAN `token.env` (see `PHASE1_OPEN_QUESTIONS.md` OQ-G2-01/02).

**Steps (see `PHASE1_IMPLEMENTATION_PLAN.md`):**

1. Fill KAVACH + JAGRAN tokens → run `scripts/phase1_bot_check.py`
2. Re-run reference LTP app during market hours — confirm token + websocket work
3. If reference works → port persistent feed into Batman (`core/` or new feed service)
4. Wire DRISHTI to show LTP health; feed cache for future KAVACH ATO
5. Run `python main.py` — 3 bots
6. Log results in `PHASE1_DAILY_LOG_2026-05-30.md` + tracker

**JWT:** Valid ~24h from issue; refresh via DRISHTI if expired.

**DRISHTI:** Restart with `python run_drishti.py` if laptop was rebooted.

---

## Late session topics (2026-05-29 evening)

1. Telegram bot token audit (DRISHTI/KAVACH/JAGRAN)
2. Dhan JWT REST validation
3. DRISHTI UI restored to screenshot look & feel (alive card + 6-button menu)
4. `run_drishti.py` started; dev check scripts added
5. Context + open questions saved for Day 2 resume

---

## Open questions remaining

| ID | Topic |
|----|-------|
| OQ-G2-01 | KAVACH token.env — placeholders, needs real values |
| OQ-G2-02 | JAGRAN token.env — file missing |
| OQ-G2-03 | Same chat ID for all 3 bots vs separate JAGRAN chat |
| OQ-G1-01 | NIFTY LTP websocket — market-hours retest |
| PQ-12 | Usual daily JWT time (optional) |
| EQ-01–04 | Engineering: stale feed thresholds, GIFT check, persistent websocket design |

Full list: `PHASE1_OPEN_QUESTIONS.md`

---

## Related files (start here tomorrow)

1. **`PHASE1_DAILY_LOG_2026-05-30.md`** — Day 2 checklist
2. `PHASE1_IMPLEMENTATION_PLAN.md` — ordered backlog + progress %
3. `PHASE1_OPEN_QUESTIONS.md` — **unresolved questions only**
4. `PHASE1_REQUIREMENTS.md` — locked behavior
5. `PHASE1_DHAN_INTEGRATION.md` — LTP technical notes
6. `CONTEXT.md` — Section 15 handoff
7. `IMPLEMENTATION_TRACKER.md` — Phase 1 matrix rows
8. `SESSION_CAPTURE_LOG.md` — audit row for today

---

## Operator rollout sequence (locked end of Day 1)

Seven gates — see `PHASE1_IMPLEMENTATION_PLAN.md` for full checklists:

1. NIFTY LTP → 2. Telegram bots → 3. Dhan positions → 4. KAVACH config → 5. ATO/choppy test → 6. Performance → 7. JAGRAN errors

---

*End of Day 1 — Gate 1 (LTP) is next; Gate 2 partial (DRISHTI only). Resume: `PHASE1_DAILY_LOG_2026-05-30.md`.*

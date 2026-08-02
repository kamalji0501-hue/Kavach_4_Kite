# SARANSH — Reporting Bot Design (authoritative plan)

**Status:** IMPLEMENTATION_COMPLETE (Phase 1 P0–P5) — Gate 5 market-hours evidence pending  
**Last updated:** 2026-06-05 (coding complete — see `SARANSH_IMPLEMENTATION_STATUS.md`)  
**Owner:** Rahul  
**Bot:** `@saransh_bm_bot` · **Non Critical Alerts** `-5163776252`  
**Out of scope:** SANCHALAK

> Handoff: `bat_telegram/bots/saransh/SARANSH_CONTEXT.md` · Q&A: `PHASE1_OPEN_QUESTIONS.md` § SARANSH

---

## 1. Purpose

SARANSH is the **reporting robot** — no trading. KAVACH executes; SARANSH reads execution feed and answers: how many ATO round trips today, CE/PE holding status, buy/sell prices, total points lost.

## 2. Locked decisions (2026-06-05)

| ID | Decision |
|----|----------|
| Q1 | Optional 4th bot; Start All: DRISHTI → KAVACH → JAGRAN → **SARANSH last** |
| Q2 | Missing token/disabled → **skip + warn** in post-start verify (not blocking) |
| Q3 | **Integrate** existing `bot.py` — not build from zero |
| Q4 | **Fast JSON feed** from ATO; SARANSH owns Excel (not KAVACH hot path) |
| Q5 | **1 BUY + 1 SELL = 1 cycle**; Telegram **ATO Cycle** button (minimal commands) |
| Q10 | **Point impact** — signed per cycle + net total; include sell strike |
| Q11 | Open leg: **one line** in ATO Cycle view |
| Q12 | Cross-day: **exit day** attribution; points from original buy LTP |
| Q13 | **Mode trees** — `data/uat/...` vs `data/prod/...`; never mix |
| Q14 | Orders: **today** + **all-time** two lines |
| Q15 | Telegram: **compact table** all cycles; Excel: **full detail** every field |
| Q16 | **SARANSH only** builds XLSX (heavy sheets) |
| Q17 | UAT PnL included + disclaimer (system calc, not Sensibull) |
| Q18 | **KAVACH** session manifest + cleanup on Batman Complete |
| Q19 | **Lots only** in Telegram and Excel (project convention) |
| Q20 | Auto EOD **15:35 IST** |
| Q21 | Auto EOD skips non-trading days (`is_trading_day`); **manual menu always** |
| Q22 | **Always allow** reports while KAVACH paused |
| Q23 | **SARANSH chat only** + standard robot logs — no JAGRAN / incident fan-out |
| Q24 | Running bot + on-demand menu; data always stored |
| Q25 | Log **rollover** (keep history); **restart SARANSH** on Batman Complete |

## 3. Data pipeline (locked)

**KAVACH hot path:** append `ato_cycle_feed.jsonl` + atomic `ato_cycle_state.json` (milliseconds, file lock).

**SARANSH cold path:** read feed → Telegram buttons → periodic `summary_YYYYMMDD.xlsx`.

Keep `ato_trade_ledger.csv` / telemetry CSV until feed validated.

### Point impact (signed — locked Q10)

Per completed round trip on NIFTY spot at execution:

```
point_impact = sell_nifty_ltp − buy_nifty_ltp
```

| Example | Impact | Label |
|---------|--------|-------|
| Buy 100, sell 98 | **−2** | 2 points lost |
| Buy 92, sell 87 | **−5** | 5 points lost |
| Buy 100, sell 103 | **+3** | 3 points gained |

- Show **sell strike** (and side CE/PE) on each cycle line.
- Show **per-cycle impact** and **net total point impact** for the day.
- Telegram label: **Point impact** with `−` / `+` notation (bracket optional: “lost” / “gained”).

Cross-day (Q12): on **exit day**, use **entry-day buy LTP** with exit-day sell LTP for the same formula.

### Mode paths (locked Q13)

All artifacts under `core.batman_mode.data_root()` — same layout per mode:

```
data/uat/analytics/ato/ato_cycle_feed.jsonl
data/uat/analytics/ato/ato_cycle_state.json
data/uat/analytics/saransh/summary_YYYYMMDD.xlsx
data/uat/deployments/
data/uat/batman_state.json
```

Prod mirrors under `data/prod/...`. **No shared `data/analytics/`** across modes.

### ATO Cycle button shows

- Round trips completed today (count)  
- CE: Holding ATO / Not holding — **one line** if open (Q11)  
- PE: same  
- **Compact table** — all today’s cycles: side, sell strike, buy LTP, sell LTP, point impact (`±`)  
- Multi-message split if table exceeds Telegram limit  
- **Net point impact** total  

### Telegram vs Excel (locked Q15–Q16)

| Channel | Detail level |
|---------|----------------|
| **Telegram (ATO Cycle)** | Compact table — all cycles, readable on mobile |
| **XLSX (SARANSH only)** | Picture-perfect: every timestamp, buy/sell, point impact, lots, PnL, triggers, protect strike/symbol, order ids, deployment id, session epoch |

SARANSH is the **only** XLSX builder for operator reports. ATO stops XLSX in hot path (JSONL only).

### Lots convention (locked Q19)

All SARANSH reporting uses **lots** (from KAVACH `params.json` lot_size, default 65). Do not show broker qty in Telegram or Excel.

### UAT PnL (locked Q17)

Include running PnL with disclaimer: *“UAT shadow PnL — system calculated; may not match Sensibull screenshot.”*

## 3.1 Session lifecycle — KAVACH ↔ SARANSH (locked Q18, Q25, Q26)

SARANSH is **dependent on KAVACH session boundaries**. Old cycles/positions must never appear after **register start**, **register confirm**, or **Batman Complete**.

**Manifest:** `data/{mode}/analytics/session_manifest.json`

```json
{
  "session_id": "20260605_110032",
  "status": "armed|completed|idle",
  "deployed_at_ist": "2026-06-05 11:00:32 IST",
  "completed_at_ist": null,
  "deployment_file": "batman_20260605.json",
  "mode": "uat",
  "restart_reason": "register_confirm|batman_complete"
}
```

### Three KAVACH hooks (new module: `core/saransh_session_sync.py`)

| Event | KAVACH hook | Files / state | SARANSH process |
|-------|-------------|---------------|-----------------|
| **`/register` start** (`wizard_entry`) | `saransh_session_reset(feeds_only=True)` | Delete `ato_cycle_feed.jsonl`, `ato_cycle_state.json`; manifest → `idle` if prior `completed` | **No restart** (wizard open) |
| **Register confirm** (`_finalize_register_confirm`) | `saransh_session_reset(armed=True)` + new manifest | Fresh manifest `status: armed`, new `session_id` | **Auto restart** |
| **Batman Complete** (`_batman_complete_locked`) | Full cleanup + log rollover | Archive XLSX; wipe feeds; manifest `completed` | **Auto restart** |

### Automatic restart (OQ-SAR-26 — locked)

KAVACH calls (async `to_thread`):

1. `scripts/stop_saransh.py --silent`  
2. `Execution/Start Bots/start Saransh.bat` (or `run_saransh.py` via subprocess with `BATMAN_LAUNCHED_VIA_BAT=1`)

Skip restart if SARANSH not running / not configured (`optional_bot_enabled`).

### SARANSH confirmation Telegram (after restart)

On `post_init`, SARANSH reads manifest `restart_reason` and sends **one** message to SARANSH chat:

| Reason | Message (plain text) |
|--------|----------------------|
| `batman_complete` | `Batman Complete acknowledged. SARANSH restarted. No active session — run /register on KAVACH when ready.` |
| `register_confirm` | `New Batman session armed. SARANSH restarted. Deployed: {deployed_at_ist}. Use ATO Cycle for live recap.` |
| (none / idle) | No auto message |

**Status** button always shows: `deployed_at_ist`, `session_id`, `status`, CE/PE holding from `ato_cycle_state.json`.

### Batman Complete cleanup checklist (extend `batman_cleanup.py`)

1. Archive session SARANSH XLSX  
2. Wipe feeds + cycle state  
3. Manifest → `completed` + `completed_at_ist`  
4. Existing deployment/state/ATO checks  
5. Log session rollover (new files; **keep** old logs)  
6. `saransh_session_sync.restart_saransh()`  

### Register start cleanup

Extend existing `prepare_uat_register_fresh` / `wizard_entry` UAT path to call `saransh_session_reset(feeds_only=True)` so **old positions/cycles are gone before wizard steps** — fresh register = fresh reporting slate.

**Remove from SARANSH:** `publish_incident` / JAGRAN on delivery failure — log + SARANSH chat only (Q23).

## 3.2 Schedule & manual access (Q20–Q22)

| Rule | Behaviour |
|------|-----------|
| Auto EOD | **15:35 IST** on trading days only |
| Calendar | `core.utils.is_trading_day()` + `NSE_HOLIDAYS_2026` (update yearly) |
| Off-calendar / post-market | **No auto EOD**; operator uses **ATO Cycle** / **Daily Summary** buttons anytime |
| KAVACH paused | Reports **always allowed** |

## 4. Existing code inventory

| Path | Status |
|------|--------|
| `bat_telegram/bots/saransh/bot.py` | Coded |
| `SARANSH_CONTEXT.md` | Handoff |
| `telegram/bots/saransh/token.env` | PASS audit + send |
| `main.py` | Optional wire |
| `modules/ato_protection.py` | CSV/XLSX producer (to add JSON feed) |
| `run_saransh.py` + start bat | ✅ P0 |
| `core/saransh_reporting.py` | ✅ P3 |
| `core/saransh_session_sync.py` | ✅ P2 |

## 5. Implementation phases

P0 launcher · P1 JSON feed in ATO · P2 SARANSH ingest + buttons · P3 XLSX · P4 cleanup · P5 Gate 5 tests

## 6. Code verification (not building from zero)

Existing SARANSH report logic in `bot.py`: `_compute_summary_payload`, `_render_summary`, `_send_summary`, EOD loop, telemetry ingest from `ato_execution_telemetry.csv`.

**Gap vs new design:** no JSON feed ingest, no ATO Cycle button, no XLSX in SARANSH process, telemetry-only points math.

ATO already writes rich data in `modules/ato_protection.py`: `_append_telemetry_row`, `_record_trade_cycle`, `ato_trade_ledger.csv`, XLSX snapshots — **new work** is thin JSONL writer + SARANSH reader, not full report rewrite.

## 7. Q&A status

**All questions locked** Q1–Q25 + **OQ-SAR-26**. Design complete — ready to code.

## 8. Implementation order (coding)

| Phase | Deliverable |
|-------|-------------|
| P0 | `run_saransh.py`, start/stop bats, menu buttons skeleton |
| P1 | ATO JSONL + state JSON + `session_manifest.json` (mode paths) |
| P2 | KAVACH Batman Complete cleanup + log rollover + SARANSH restart |
| P3 | SARANSH feed ingest, ATO Cycle compact table, heavy XLSX |
| P4 | Remove JAGRAN from SARANSH; `is_trading_day` EOD; 15:35 |
| P5 | Gate 5 agent verification |

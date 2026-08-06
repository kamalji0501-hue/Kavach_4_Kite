# Gate 5 — Simulated ATO Test (Mock Orders)

**Target:** Monday market session (or first open market after Saturday dry-run)  
**Owner:** Rahul  
**Mode:** `mock` only — no live broker orders until VPS (~15 days out)

---

## Prerequisites

| # | Check |
|---|--------|
| 1 | DRISHTI running — JWT valid, **LTP Feed Setup** completed (operator chooses poll + stale seconds) |
| 2 | KAVACH running — `run_kavach2.py` / start bat; log shows **ATO Protection module started** |
| 3 | JAGRAN running — Batman Alerts group receiving incidents |
| 4 | Fresh **Batman Complete** → verified cleanup → **/register** full **4-leg** deployment |
| 5 | `control.runtime_mode` = **mock** (laptop default) |
| 6 | `deployment.confirmed` = true after register confirm |

---

## Ledger / evidence to capture

Store under `data/analytics/ato/` and note in `PHASE1_DAILY_LOG`:

| Artifact | Path |
|----------|------|
| ATO cycle CSV (live append) | `data/analytics/ato/ato_cycles.csv` |
| Snapshot copy (safe to open while running) | `data/analytics/ato/snapshots/ato_cycles_YYYYMMDD_HHMMSS.xlsx` |
| NIFTY LTP feed log | `logs/bots/drishti/nifty_ltp/nifty_ltp_YYYYMMDD.log` |
| LTP cache | `data/nifty_ltp_cache.json` |
| KAVACH startup | `logs/bots/kavach/startup.log` |
| Auto-pause state | `data/batman_state.json` → `algo.paused`, `algo.pause_reason` |

**Per-cycle fields to verify:** side (CE/PE), buy/sell timestamps, trigger level, exit/retrace level, qty, points lost, points × lots.

---

## Test sequence (mock)

### A. Feed health (5 min)

1. DRISHTI → **Nifty LTP (Polling)** — price matches cache age.
2. Confirm `data/nifty_ltp_cache.json` updates at chosen poll interval.
3. Optional: **Nifty LTP (WebSocket)** — health test only (not ATO path).

### B. ATO armed (2 min)

1. KAVACH → `/ato_status` — idle, strikes set, not paused.
2. KAVACH → `/start_algo_now` if algo not already running.

### C. Simulated breach (simulator or manual spot move)

**Using simulator** (`python simulator/app.py` → market UI):

1. Note CE/PE sell strikes + entry buffers from deployment.
2. **CE Breach** — sets NIFTY above CE trigger → expect mock ATO BUY on CE protect leg.
3. Check KAVACH/JAGRAN notifications (ATO triggered).
4. Confirm row appended to `ato_cycles.csv` (BUY leg).

### D. Simulated retrace exit

1. **CE Retrace** (or PE equivalent) — spot pulls back inside retrace buffer.
2. Expect mock SELL / exit on ATO leg.
3. Confirm cycle row completed (SELL leg, points lost computed).

### E. Auto-pause drill (optional)

1. Stop DRISHTI feed or force stale LTP (config: short stale threshold for test).
2. Expect JAGRAN stale-feed alert + **algo auto-pause**.
3. KAVACH → **Resume** after feed healthy — manual only (no auto-resume).

---

## Pass criteria

- [ ] Mock ATO BUY placed on breach (no duplicate orders on retry poll).
- [ ] Mock exit on retrace per configured buffer.
- [ ] Cycle ledger row complete with qty = **managed BUY qty** (not hard 1:2).
- [ ] XLSX snapshot created under `snapshots/`.
- [ ] No live orders (`runtime_mode` stayed mock).
- [ ] Feed stale → pause → operator Resume works.

---

## Fail / escalate

| Symptom | Action |
|---------|--------|
| ATO never triggers | Check `deployment.confirmed`, `algo.paused`, LTP cache age, sell strikes |
| Duplicate orders | Check idempotency logs in `ato_protection.py` / broker mock |
| Ledger empty | Confirm ATO module thread running in KAVACH startup log |
| Markdown errors in menus | Retest Positions/Legs after `_md2` fix |

Route blockers to JAGRAN scenario + note in daily log.

---

## Operator decisions (locked 2026-05-30 night)

- **Mock only** on laptop until VPS (~15 days).
- **Batman Complete → cleanup verified → register** (no register while armed). Full rules: **`docs/KAVACH_ATO_OPERATOR_RULES.md`**.
- **4-leg** registration scope.

---

## Economy / chop test profile (UAT — locked 2026-06-20)

Use when testing choppiness **without** expensive near-ATM protect premium.

| Field | Example |
|-------|---------|
| CE sell (Batman) | 24,500 CE |
| CE protect (custom) | 26,000 CE (+1500) |
| ATO lots | 1 (not full managed size) |
| Entry buffer | 0 |
| Exit buffer | 5 |
| Trigger | Still **24,500** sell — not 26,000 |

**Pass extras for this profile:**

- [ ] CE protect presets: **+500 / +1000** only on CE side (PE uses **−100 / −500** only)
- [ ] Confirm warns **custom strike / economy profile**
- [ ] Breach → mock BUY **1 lot** at 26k (not 24,550)
- [ ] Retrace exit uses **sell strike** retrace logic
- [ ] Soft-cap warn at **3** cycles (side); no auto-stop
- [ ] SARANSH shows **Custom ATO / economy profile** tag (when implemented)
- [ ] Re-register only after **Batman Complete** (not over old deployment)

Full scenario bible: **`docs/KAVACH_ATO_OPERATOR_RULES.md`** §13–§15.
- **LTP poll/stale numbers:** operator sets via DRISHTI **LTP Feed Setup** (not hardcoded for prod).
- **Stop-all.bat:** out of scope.

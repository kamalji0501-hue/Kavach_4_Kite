# Reliability Validation — Market Hours Deferred Checklist

**Purpose:** Items that require a **live NIFTY feed** (NSE session ~09:15–15:30 IST) cannot be fully proven after market close. Run this checklist on the next trading day.

**Off-hours completed (agent-owned):** bot lifecycle, Telegram retry/runtime, process singleton, cache-write resilience, mocked fault injection, incident fix verification.

---

## When to run

| Window | IST | Live LTP required |
|--------|-----|-------------------|
| Pre-open | before 09:14 | No (gate skipped) |
| Market session | 09:15–15:30 | **Yes** |
| Post-close | after 15:35 | No (gate skipped) |
| NSE holiday / weekend | — | No |

Supervisor uses `core/startup_gates.py` → `ltp_gate_skip_reason()`.

---

## Deferred checks (operator or agent, market open)

### Feed / WebSocket

- [ ] DRISHTI writes `data/nifty_ltp_cache.json` with `feed_healthy=true` and age &lt; 90s
- [ ] Cache `source` is `dhan_websocket` or `dhan_rest` (not stale-only)
- [ ] No false failover on Dhan `Previous Close` control frames (STAB-04)
- [ ] WS HTTP 429 does not trigger reconnect storm (STAB-05/06)
- [ ] Mid-session WS reconnect respects transport grace 30s (STAB-06 / INC-017)
- [ ] WS→REST failover persists across DRISHTI restart (STAB-03)
- [ ] Same-day WS retry after REST lock (STAB-13)
- [ ] Live Price button does not open parallel WS (STAB-14)

### KAVACH / ATO

- [ ] KAVACH reads fresh cache; no `NIFTY LTP cache stale` on startup scan
- [ ] Feed stale → ATO pause uses correct UAT state path (STAB-01)
- [ ] Sustained feed recovery before auto-resume (INC-022, ≥45s stable)

### 15-cycle harness (live session)

```powershell
.venv\Scripts\python.exe scripts\run_phase1_reliability_loop.py --cycles 15 --wait-seconds 180
```

Expect `market_session.live_ltp_required: true` and `price_flow_mode: live_session_feed_healthy` on every cycle.

### Stress (optional, market open only)

- [ ] Brief network disconnect — feed recovers without manual restart
- [ ] DRISHTI-only restart — failover state preserved; KAVACH cache consumer OK

---

## Commands (market day)

```powershell
.venv\Scripts\python.exe scripts\phase1_bot_check.py
.venv\Scripts\python.exe scripts\run_uat_e2e_verification.py
.venv\Scripts\python.exe scripts\run_phase1_reliability_loop.py --cycles 15 --wait-seconds 180
.venv\Scripts\python.exe scripts\generate_reliability_engineering_report.py
```

---

## Evidence paths

| Artifact | Path |
|----------|------|
| Reliability JSON | `data/analytics/reliability/phase1_reliability_*.json` |
| Engineering report | `docs/RELIABILITY_ENGINEERING_REPORT.md` |
| DRISHTI feed log | `logs_uat/runtime/.../drishti/logs/all.log` |
| NIFTY cache | `data/nifty_ltp_cache.json` |

---

## MCX SILVER off-hours connectivity probe (optional)

When NSE is closed but **MCX is open** (~09:15–23:30 IST), use the same Dhan JWT to prove live ticks without touching NIFTY/ATO:

```powershell
.venv\Scripts\python.exe scripts\mcx_silver_probe.py --contract jul --samples 3
```

Resolved from Dhan security master (2026-06-25):

| Contract | Security ID | Dhan segment | Trading symbol |
|----------|-------------|--------------|----------------|
| SILVER JUL FUT | **464150** | `MCX_COMM` | SILVER-03Jul2026-FUT |
| SILVER SEP FUT | 471725 | `MCX_COMM` | SILVER-04Sep2026-FUT |
| SILVER DEC FUT | 495214 | `MCX_COMM` | SILVER-04Dec2026-FUT |

**Verified:** REST LTP returned ~₹2,16,500–2,16,600 on 2026-06-25 (matches Sensibull snapshot order of magnitude). This does **not** substitute for NIFTY `feed_healthy` in the reliability harness.

Re-resolve IDs after contract roll via `dhanhq.fetch_security_list("compact")` filtered to `SEM_EXM_EXCH_ID == "MCX"` and `SEM_INSTRUMENT_NAME == "FUTCOM"`.

---

## Sign-off

When all boxes above pass on a live session day, add a row to `SESSION_CAPTURE_LOG.md` and mark market-hours deferred section **COMPLETE**.

---

## Tomorrow start (2026-06-26)

**Handoff:** `NEW_CHAT_HANDOFF.md` + `docs/RELIABILITY_TOMORROW_HANDOFF.md`

**Operator:** Paste agent prompt from handoff § "Tomorrow — copy-paste" after 09:15 IST.

**Quick command (agent runs autonomously):**

```powershell
.venv\Scripts\python.exe scripts\run_phase1_reliability_loop.py --cycles 15 --wait-seconds 180
```

**Off-hours completed 2026-06-25:** pytest green, stabilization PASS, lifecycle 7/7 total cycles PASS across two artifacts, all bots STOPPED at session end.

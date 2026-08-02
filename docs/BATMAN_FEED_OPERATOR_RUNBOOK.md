# Batman Algo — Feed & Recovery Operator Runbook

Last updated: 2026-06-07  
Owner: Rahul  
Audience: Operator (UAT and production VPS)

This document is the **full operator reference** for NIFTY feed health, ATO pause/resume, and Telegram controls across **DRISHTI** and **KAVACH**.

---

## 1. Architecture (locked)

| Bot | Role | Calls Dhan for NIFTY? | Writes cache? |
|-----|------|----------------------|---------------|
| **DRISHTI** | Sole NIFTY collector + token/infra | Yes (WebSocket or REST) | `data/nifty_ltp_cache.json` |
| **KAVACH** | Deployment, ATO, orders | **No** — reads cache only | No |

**Rule:** KAVACH/ATO never poll Dhan for Nifty spot. If cache is stale, fix DRISHTI — do not restart KAVACH expecting a feed fix.

See also: `NIFTY_LTP_POLICY.md` in repo root.

---

## 2. Daily timeline (IST, trading day)

| Time | DRISHTI | KAVACH / ATO |
|------|---------|--------------|
| Before 09:15 | Feed idle (off-hours probe optional) | Idle or armed — no breach checks |
| 09:15 | NIFTY feed starts (WebSocket first) | Cache fills; **ATO still waits** |
| **09:25** | Feed continues | **ATO monitoring starts** — breach checks active |
| 09:25+ | Silent failover WS↔REST if needed | Paused if feed fails; resume rules apply |
| 15:30 | Session ends | Market-hours gate stops checks |
| EOD | Recovery owner reset (optional) | **Batman Complete** → full state + recovery reset |

**Config:** `telegram/bots/kavach/params.json` → `ato_monitoring.start_time_ist` (default `"09:25"`).

---

## 3. Normal morning (no outage)

1. Start **DRISHTI** (`run_drishti.py`) — token active, feed mode `websocket` (or `rest` for comparison).
2. Start **KAVACH** (`run_kavach.py`).
3. Register / confirm deployment on KAVACH.
4. Before **09:25**: tap **ATO Status** or **Status** — you should see:
   - `⏳ Waiting — monitoring starts at 09:25 IST`
   - Logs: `ATO Protection: running OK — waiting for monitoring start (09:25 IST)` every ~60s
5. At **09:25**: logs show `monitoring start time reached`; ATO Status shows `▶ Monitoring active`.
6. DRISHTI **NIFTY Status** button shows feed path, cache age, recovery owner.

---

## 4. Feed failure — what happens automatically

1. **Stale or dead feed** (no tick/poll refresh — not “unchanged price”):
   - WebSocket: no refresh **5s** → degraded
   - REST: no poll **10s** → degraded
2. **ATO pauses** with reason e.g. `nifty_ltp_websocket_failed` or `nifty_ltp_feed_stale`.
3. **DRISHTI retries silently** — runtime transport alternation (does **not** change config file):
   - WebSocket → REST → WebSocket → REST (**4 switches** = one full cycle)
4. After **~5 minutes** still degraded: escalation alert + auto **Manual handling** (operator owns recovery).
5. DRISHTI keeps retrying in background.
6. When feed is healthy again: **same message** posted to **both** DRISHTI and KAVACH Telegram chats.
7. Operator taps **Resume** on KAVACH when ready.

**No 30-second spam** during retry — only escalation (~5 min) and feed-back notification.

---

## 5. Telegram buttons & commands

### DRISHTI

| Control | Action |
|---------|--------|
| **Health (Python)** | Process / bot liveness |
| **Nifty LTP** | Cache snapshot + transport label |
| **Live Price** | One-shot live fetch (market hours) |
| **NIFTY Status** | Full feed card: mode, active path, task, recovery owner, cache age |
| **LTP Feed Setup** | Change `feed_mode` in config (`websocket` / `rest`) |
| **Manual handling** | Operator takes recovery; DRISHTI still retries; no auto-resume |
| **Auto resume** | Return recovery to DRISHTI (confirm step) |
| `/niftystatus` | Same as **NIFTY Status** button |

### KAVACH

| Control | Action |
|---------|--------|
| **Status** | Broker, algo, deployment, **ATO Schedule**, **NIFTY Feed** one-liner |
| **ATO Status** | Breach levels, triggers, **Schedule** line, Nifty spot from cache |
| **Pause** | Stops **ATO only** (`kavach_manual`) — **DRISHTI feed keeps running** |
| **Resume** | Unpauses ATO — blocked as **Waiting for feed** until cache healthy (feed outage only) |
| **Manual handling** | Same as DRISHTI — during feed outage |
| **Batman Complete** | Archive deployment, reset state, clear `nifty_feed_recovery` |

---

## 6. Pause & resume rules (locked decisions)

### Manual KAVACH Pause (Q6 = A)

- Sets `pause_reason = kavach_manual`.
- **Does not** stop DRISHTI or the Nifty writer.
- **Resume** works immediately — no feed cache check.
- Use when you want to stop trading actions but keep the feed warm.

### Feed-related pause

- Reasons include: `nifty_ltp_websocket_failed`, `nifty_ltp_rest_fallback_failed`, `nifty_ltp_feed_stale`, etc.
- **Resume blocked** until cache is trading-ready.
- Button shows **Waiting for feed** (visible, not hidden).
- **No force resume** without healthy feed (Q8 = A) — never bypass cache check.

### Auto-resume at session open

- At **09:25** IST, if ATO was paused for **feed** only and cache is healthy and DRISHTI owns recovery → ATO may auto-resume.
- If **Manual handling** (operator owner) → you must tap **Resume** yourself.

---

## 7. Recovery ownership

| Owner | Who drives resume | JAGRAN feed incidents |
|-------|-------------------|----------------------|
| `drishti` (default) | Auto-resume at 09:25 if feed OK | Critical |
| `operator` (Manual handling) | Operator taps Resume | Downgraded to warning |

State file: `data/batman_state.json` → `nifty_feed_recovery`.

**Batman Complete** clears all recovery flags for a clean next session.

---

## 8. Escalation matrix

| Condition | ATO | DRISHTI action | Telegram |
|-----------|-----|----------------|----------|
| Feed stale < 5 min | Paused | WS↔REST cycle, silent retry | No spam |
| Degraded ≥ 5 min, cycle not exhausted | Paused | Keep retrying | Escalation alert |
| 4 transport switches, still down | Paused | Manual handling auto-set | Escalation + manual path |
| Feed back | Still paused until Resume | Notify both chats | Feed-ready message |
| Operator Resume + healthy cache | Running | Owner → drishti | — |
| Manual KAVACH Pause | Paused (manual) | Feed unaffected | — |

---

## 9. Log paths (UAT)

Base: `logs_uat/runtime/YYYY-MM/YYYY-MM-DD/`

| Component | Path |
|-----------|------|
| DRISHTI bot | `drishti/logs/` |
| WebSocket ticks | `drishti/logs/nifty_websocket_ltp/ws_ltp_YYYYMMDD.log` |
| REST ticks | `drishti/logs/nifty_rest_ltp/rest_ltp_YYYYMMDD.log` |
| NIFTY cache | `data/nifty_ltp_cache.json` |
| Feed config | `data/nifty_ltp_feed_config.json` (change via LTP Feed Setup only) |
| Batman state | `data/batman_state.json` |
| Deployments | `data/deployments/` (active), `data/deployments/archive/` |
| ATO module | KAVACH process logs / `ato_protection` logger |

**Prod:** same layout under `logs_prod/`.

---

## 10. UAT verification checklist

### Feed & cache

- [ ] DRISHTI starts with `websocket` mode (or chosen mode via LTP Feed Setup).
- [ ] `nifty_ltp_cache.json` updates during 09:15–15:30.
- [ ] WebSocket log file receives ticks (`HH:MM:SS.mmm | LTP`).
- [ ] **NIFTY Status** shows `Feed task: running`, cache age < 5s (WS).

### Schedule gate (09:25)

- [ ] Deploy before 09:25; **ATO Status** shows waiting line.
- [ ] ATO log: `waiting for monitoring start (09:25 IST)` before 09:25.
- [ ] No ATO orders / breach firing before 09:25.
- [ ] At 09:25: `monitoring start time reached`; breach checks run.

### Failover

- [ ] Kill WebSocket or block network → ATO pauses within stale threshold.
- [ ] DRISHTI switches to REST without editing config file.
- [ ] Feed-back message on **both** chats when recovered.
- [ ] **Resume** blocked until cache fresh; then works.

### Manual controls

- [ ] **Pause** on KAVACH during feed outage → `kavach_manual`; Resume without waiting.
- [ ] DRISHTI process still writing cache after KAVACH Pause.
- [ ] **Manual handling** → no auto-resume; critical → warning on feed incidents.
- [ ] **Batman Complete** → recovery flags cleared; redeploy clean.

### Force resume (must NOT exist)

- [ ] No button/command resumes ATO with stale cache during feed pause.

---

## 11. What NOT to do

1. **Do not stop DRISHTI** during a feed outage — that kills recovery.
2. **Do not edit** `nifty_ltp_feed_config.json` by hand mid-session — use **LTP Feed Setup**.
3. **Do not Resume** after feed pause until feed-ready message (unless you used manual KAVACH Pause).
4. **Do not merge** DRISHTI and KAVACH Telegram chats for alerts — both get feed-ready duplicate by design.
5. **Do not expect ATO** before 09:25 even if deployed at 09:16.

---

## 12. Quick troubleshooting

| Symptom | Check | Fix |
|---------|-------|-----|
| ATO Status: cache stale | DRISHTI running? Token valid? | Restart DRISHTI; refresh token |
| Waiting for feed forever | WS/REST logs; network | Manual handling; fix VPS network; wait for cycle |
| No ticks in WS log | Feed mode; market hours | LTP Feed Setup → websocket; confirm 09:15+ |
| Live feed not started on DRISHTI start | Token expired / missing | **Update Token** — feed stays blocked until JWT is fresh (valid scenario) |
| ATO fired before 09:25 | Clock / params | Confirm `start_time_ist`; check logs for schedule gate |
| Resume greyed as Waiting for feed | Cache age on NIFTY Status | Wait for DRISHTI recovery or Manual Pause if intentional |
| 429 / rate limit | Duplicate DRISHTI instances | One DRISHTI only in REST mode |
| Feed restarts but WS reconnects immediately | DRISHTI log shows `WinError 5` on `nifty_ltp_cache.json` replace | Treat as a local cache-write race, not a broker disconnect; let DRISHTI retry, then check for tools/processes holding the cache file |

### Distinguish transport vs cache-write failures

- **True transport issue:** WebSocket/REST auth, 429, stale, or network errors dominate the DRISHTI feed logs.
- **Local cache-write race:** `NIFTY feed task exited` or `NIFTY WebSocket feed error` with `Access is denied` on `data/nifty_ltp_cache.json`.
- In the second case, the upstream WebSocket may still be healthy. The problem is the shared disk cache layer, not necessarily Dhan connectivity.

---

## 13. Config reference

| File | Key | Default | Notes |
|------|-----|---------|-------|
| `telegram/bots/kavach/params.json` | `ato_monitoring.start_time_ist` | `09:25` | ATO breach checks start |
| `telegram/bots/drishti/params.json` | feed / grace settings | websocket, 30s grace | DRISHTI defaults |
| `data/nifty_ltp_feed_config.json` | `feed_mode` | manual setup | `websocket` / `rest` |

---

## 14. Related docs

- `NIFTY_LTP_POLICY.md` — single-source-of-truth policy
- `bat_telegram/bots/kavach/KAVACH_CONTEXT.md` — KAVACH feature map
- `tests/test_feed_recovery.py` — recovery unit tests
- `tests/test_ato_monitoring_schedule.py` — 09:25 schedule tests

---

*End of runbook.*

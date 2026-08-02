# JAGRAN Bot — Context & Handoff

**Status:** ✅ **Phase 1 standalone implemented**  
**Last updated:** 2026-05-30 (verified in Batman Alerts group — tool restart handoff)  
**Owner:** Rahul  
**Bot:** `@jagran_bot`

---

## 1. What JAGRAN does

| Responsibility | Status |
|----------------|--------|
| Receive critical incidents (separate Telegram chat) | ✅ via `incident_publisher` |
| Dedup + still-failing + recovery messages | ✅ |
| Daily incident ledger (CSV/XLSX) | ✅ `data/analytics/incidents/` |
| Button menu: Status, Recent, Today, Test Alert | ✅ |
| EOD digest **15:30 IST, trading days only** | ✅ background scheduler |
| Standalone runner + Start/Stop bats | ✅ |

**Does NOT own:** trading commands, token delivery, registration wizard.

---

## 2. Architecture (two layers)

1. **Outbound (no JAGRAN process required)** — DRISHTI/KAVACH/main call `publish_incident()` which sends to JAGRAN chat using `telegram/bots/jagran/token.env`.
2. **Inbound (JAGRAN process)** — `run_jagran.py` polls Telegram for operator buttons and EOD scheduler.

Always run JAGRAN alongside DRISHTI/KAVACH during dev so `/recent` and EOD work.

---

## 3. Routing rules (locked)

- **Separate bot token + separate chat ID** — group **Batman Alerts** (`JAGRAN_CHAT_ID=-5174160875` in `token.env`).
- **Dual publish:** allowlisted incidents → source bot chat **and** JAGRAN.
- **KAVACH → JAGRAN only after Confirm** (`deployment.confirmed` in state). Wizard/ratio errors stay in KAVACH wizard only.
- **DRISHTI websocket:** local message on each failed health check; **JAGRAN at 5 consecutive failures** (`websocket_jagran_retry_threshold`).
- **No notifications on non-trading days** (EOD skipped via `is_trading_day()`).
- Phase 1 **excluded** from allowlist: emergency exit, SANCHALAK, SARANSH.

Allowlist source: `JAGRAN_ERROR_MATRIX.md` + `bat_telegram/incident_publisher.py`.

---

## 4. Operator UI

After `/start` or `/ping`:

```
🚨 JAGRAN alive
[Status]  [Recent]
[Today]   [Test Alert]
```

---

## 5. How to run (Windows)

| Action | Command / file |
|--------|----------------|
| **Start** | `Execution\Start Bots\start Jagran.bat` |
| **Stop** | `Execution\Stop Bots\stop Jagran.bat` |
| **Standalone** | `python run_jagran.py` |
| **Pre-flight** | `python scripts\phase1_bot_check.py` |
| **Logs** | `logs\jagran_startup.log` |

---

## 6. Key files

| File | Role |
|------|------|
| `bat_telegram/bots/jagran/bot.py` | UI + EOD scheduler |
| `bat_telegram/bots/jagran/ledger.py` | Read/summarize incident CSV |
| `bat_telegram/incident_publisher.py` | Outbound routing + ledger write |
| `run_jagran.py` | Standalone runner |
| `telegram/bots/jagran/token.env` | Secrets (gitignored) |
| `telegram/bots/jagran/params.json` | Dedup, EOD time, recent limit |

---

## 7. Gate 7 smoke test

| Test | Result |
|------|--------|
| `/start` + alive menu | ✅ Verified |
| Test Alert → Batman Alerts group | ✅ Verified |
| EOD digest (15:30 IST trading day) | ✅ Verified (catch-up on late start) |
| Recent / Today ledger buttons | ✅ Coded — retest after live incidents |
| DRISHTI websocket → JAGRAN at 5 failures | ✅ Coded — `health_check.websocket_jagran_retry_threshold` |
| KAVACH incidents after Confirm only | ✅ Coded in `incident_publisher.py` |

**Note:** Ledger may contain test rows from `tests/test_jagran.py` — not live trading.

---

## 8. After tool/laptop restart

1. `Execution\Start Bots\start Jagran.bat`
2. Tap **Test Alert** in Batman Alerts group
3. Keep JAGRAN running alongside DRISHTI + KAVACH during dev

# Agent Testing Protocol — Batman Telegram Bots

Last updated: 2026-06-01  
Owner: Rahul

> **Operator should not manual-test routine fixes.** The agent implements, verifies, reads logs, fixes, and re-runs until stable.

Cursor rule: `.cursor/rules/batman-agent-testing.mdc` (always applied)

---

## 1. Principle

This project is **backend + Telegram automation**. UI button testing is done by the agent via:

- **pytest** (handler / callback simulation)
- **Smoke scripts** (`scripts/phase1_bot_check.py`)
- **Log review** after short bot runs
- **Telegram Bot API** (getMe, send when needed) using on-disk `token.env`

The operator reports strategic issues; the agent owns regression verification for each change.

---

## 2. Mandatory loop (every feature / fix)

```
Implement → Test → Read logs → Fix → Re-test
         ↑__________________________|
              (up to 4 cycles)

**Automated loop:** `scripts/run_agent_feedback_loop.py` — diagnose all bots, pytest, UAT E2E, session log scan, incident report. Report: `data/analytics/feedback_loop/LATEST_RUN.md`. Launcher: `Execution/Run Agent Feedback Loop.bat`.
```

| Step | Agent action |
|------|----------------|
| 1 | Minimal code change for scoped request |
| 2 | Add/update tests in `tests/test_*_{robot,modules,feed}.py` |
| 3 | Run targeted pytest, then affected suite |
| 4 | Run `scripts/phase1_bot_check.py` if Telegram tokens touched |
| 5 | If bot runtime changed: start bot briefly OR run integration test; stop cleanly |
| 6 | Read logs (see §4); note errors, tracebacks, stale cache |
| 7 | Fix failures; repeat from step 2 |
| 8 | Report with evidence (test count, log paths, remaining limits) |

**Done means:** tests green + no new errors in relevant logs + handler path exercised.

---

## 3. What “press every button” means for the agent

We cannot click the mobile Telegram UI. Equivalent coverage:

| Operator action | Agent equivalent |
|-----------------|------------------|
| Tap inline button | pytest: build `CallbackQuery` with `callback_data`, call handler |
| Send command | pytest: `Message` with `/register`, `/health`, etc. |
| Check reply text | Assert on handler return / mock `reply_text` calls |
| End-to-end smoke | `phase1_bot_check.py` + optional live `send_message` |
| ATO / register flow | `tests/test_modules.py`, `simulator/app.py`, KAVACH handler tests |

When adding a **new button**, add a **test case** that fires the same `callback_data` string defined in `bot.py`.

---

## 4. Log locations (per robot)

| Robot | Primary logs | Runtime artifacts |
|-------|--------------|-------------------|
| **DRISHTI** | `logs/bots/drishti/startup.log` | `data/nifty_ltp_cache.json`, `logs/bots/drishti/nifty_ltp/nifty_ltp_YYYYMMDD.log` |
| **KAVACH** | `logs/bots/kavach/startup.log` | `data/` state, deployment JSON |
| **JAGRAN** | Incident / jagran logs | `bat_telegram/incident_publisher.py` ledger |
| **All** | pytest output, ruff/mypy | — |

After a test run, agent **opens and searches** logs for `ERROR`, `Traceback`, `429`, `REJECTED`.

Optional future: `logs/agent_runs/YYYYMMDD_HHMM_{robot}_{feature}.log` for scripted regression captures.

---

## 5. Standard commands (Windows, project root)

```powershell
# Unit + integration tests (always)
.venv\Scripts\python.exe -m pytest tests -q --tb=short

# Targeted (example: DRISHTI feed)
.venv\Scripts\python.exe -m pytest tests/test_drishti_robot.py tests/test_drishti_feed_integration.py -q

# Telegram credential smoke (all Phase 1 bots)
.venv\Scripts\python.exe scripts/phase1_bot_check.py

# Token audit
.venv\Scripts\python.exe scripts/audit_bot_tokens.py
```

Quality gates (ruff, black, mypy): see `AGENTS.md`.

### UAT E2E (autonomous — no manual Telegram)

```powershell
Mode\Set-UAT.bat
.venv\Scripts\python.exe scripts\run_uat_e2e_verification.py
```

Agent playbook + Cursor prompt: **`UAT_E2E_AGENT.md`**.  
Logs: `logs_uat/runtime/YYYY-MM/YYYY-MM-DD/{robot}/logs/all.log`

---

## 6. Scope by change type

| Change | Minimum verification |
|--------|---------------------|
| DRISHTI button / feed | `test_drishti_*`, cache file, `nifty_ltp` log if LTP touched |
| KAVACH register / ATO | `test_modules.py` ATO tests, KAVACH handler tests if exist |
| Shared `core/` | pytest for that module + dependents |
| Docs only | No runtime test; link check |

---

## 7. Market-hours / Dhan limits

Some checks need **09:15–15:30 IST** + valid JWT + Data API:

- Live NIFTY LTP REST/WebSocket
- Live positions
- Live orders (Phase 1 laptop = **mock only**)

Agent still runs all **off-hours** tests (handlers, cache logic, token validation, pytest mocks). Report clearly: *“market-hours proof pending”* vs *“failed in session.”*

---

## 8. What the agent may need from operator (rare)

| Blocker | Operator action |
|---------|-----------------|
| Missing `token.env` | Fill `telegram/bots/{name}/token.env` once |
| Expired Dhan JWT | Paste via DRISHTI Update Token (morning) |
| Two DRISHTI instances | Run `stop Drishti.bat` once |
| Live order test on VPS | Explicit sign-off + static IP (not laptop Phase 1) |

Otherwise: **no “please test this button”** requests.

---

## 9. Agent completion checklist (copy for PR / chat)

- [ ] Code change scoped and matches conventions
- [ ] New/updated pytest for changed behavior
- [ ] `pytest` pass (state count)
- [ ] `phase1_bot_check.py` if bots/tokens affected
- [ ] Logs reviewed — path cited, no unhandled errors
- [ ] Up to 4 fix/retest cycles completed if issues found
- [ ] Report: tested surfaces, evidence, any market-hours gap

---

*Referenced from `AGENTS.md` and `.cursor/rules/batman-agent-testing.mdc`.*

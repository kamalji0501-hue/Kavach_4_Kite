# UAT E2E Agent — autonomous test loop (Cursor)

**Session handoff:** full project state → **`CONTEXT.md` §20** (resume tomorrow).

**Daily test matrix (Excel):** `daily_test_execution/test_matrix.xlsx` — updated by `scripts/run_uat_daily_test_suite.py`. Summary link: `daily_test_execution/LATEST_RUN.md`.

Use this when you want the **AI agent to iterate without you** after code changes: fix → re-run verification → read logs → repeat (up to 4 cycles).

Operator gives **one instruction**; the agent runs everything in this doc.

---

## Copy-paste agent prompt (start a session)

Paste into **Cursor Agent** (Composer):

```
You are the Batman UAT E2E agent. Read UAT_E2E_AGENT.md and follow it exactly.

After every code change in this session:
1. Run .venv\Scripts\python.exe scripts\run_quality_gates.py (or targeted pytest if huge diff).
2. Ensure Mode\Set-UAT.bat and screenshot in uat\deployed_positions\ (newest file wins).
3. If market hours (09:15-15:30 IST): Execution\Start Bots\Phase 1 Start All Robots.bat — verify RUNNING not ORPHAN.
4. Run .venv\Scripts\python.exe scripts\run_uat_daily_test_suite.py
   (updates daily_test_execution\test_matrix.xlsx + LATEST_RUN.md)
5. If any FAIL: fix minimal diff, re-run step 4 (max 4 cycles).
6. Read logs_uat/runtime/.../kavach/logs/all.log for new ERROR lines.
7. Report PASS/FAIL; give full path to test_matrix.xlsx from LATEST_RUN.md.

Rules:
- Mode must be uat (Mode\Set-UAT.bat). Screenshot book: uat\deployed_positions\
- JWT: read data\access_token.json — never ask me to paste tokens.
- Do not ask me to run commands or test Telegram buttons.
- Register/ATO: prefer pytest + run_uat_e2e_verification; live bots only if script fails and bots are already running.
- Stop/start KAVACH via Execution\Stop Bots\stop Kavach.bat and start Kavach.bat — clear kavach.lock if ORPHAN.

When all verification steps pass, say "UAT E2E gate passed" and list evidence.
```

---

## How to run the agent (no manual testing)

| Method | What you do |
|--------|-------------|
| **One-shot** | New Agent chat → paste prompt above → `@UAT_E2E_AGENT.md` |
| **After each fix** | Same chat: "continue UAT E2E loop" — agent re-runs verification script |
| **Recurring loop** | In Agent: `/loop 10m` + paste the prompt block (agent re-checks every 10 min) |
| **Headless only (no AI)** | Double-click `Execution\Run UAT E2E Verification.bat` or run script below |

---

## Headless verification (agent runs this)

```powershell
cd "H:\RK Data\Algo Trading Parent\DEV Batman Algo"
Mode\Set-UAT.bat
.venv\Scripts\python.exe scripts\run_uat_e2e_verification.py
```

| Flag | Purpose |
|------|---------|
| `--ingest` | Force Sensibull OCR even if `positions.json` is fresh |
| `--json` | JSON report for automation |
| `--skip-register-smoke` | Skip mocked `/register` entry test |
| `--log-tail 300` | Scan more log lines per robot |

**Exit 0** = UAT gate passed. **Non-zero** = agent must fix and re-run.

### What the script checks

1. `config/batman_mode.json` → `uat`
2. `uat/deployed_positions/` screenshot + `positions.json`
3. Dhan JWT in `data/access_token.json` (not expired)
4. Optional ingest (skip if fresh)
5. `validate_fixture.py` (symbols + JWT)
6. pytest: shadow resolver, KAVACH scenarios, UAT ingest
7. Mocked `wizard_entry` (Register not blocked on OCR)
8. `phase1_bot_check.py` (Telegram + DRISHTI health snapshot)
9. Bot process lines from `bot_status.py`
10. Error scan in `logs_uat/runtime/.../{kavach,drishti,jagran}/logs/all.log`

---

## Full agent loop (after code changes)

```
Implement fix
    → run_quality_gates.py
    → run_uat_e2e_verification.py
    → tail logs_uat (kavach / drishti)
    → if FAIL: fix (cycle ≤ 4)
    → if PASS: done
```

Optional live stack (only when script passes but you want runtime proof):

```powershell
Execution\Start Bots\Phase 1 Start All Robots.bat
.venv\Scripts\python.exe scripts\run_uat_e2e_verification.py
```

---

## Prerequisites (one-time / morning)

| Item | Location |
|------|----------|
| UAT mode | `Mode\Set-UAT.bat` |
| Sensibull screenshot | `uat\deployed_positions\` (any PNG name) |
| JWT | DRISHTI Update Token → `data\access_token.json` |
| Telegram tokens | `telegram\bots\{drishti,kavach,jagran}\token.env` |

Agent refreshes JWT from disk; operator only pastes in DRISHTI when script reports `dhan_jwt FAIL`.

---

## Related docs

| File | Role |
|------|------|
| `AGENTS.md` | General agent playbook |
| `TESTING_PROTOCOL.md` | Verify loop (4 cycles) |
| `.cursor/rules/batman-agent-testing.mdc` | Always-on testing rule |
| `.cursor/rules/batman-agent-autonomy.mdc` | Run commands without asking |
| `backtest_engine/tools/prepare_uat_session.py` | Manual UAT folder + validate |

---

## Scenario matrix (agent-owned)

| ID | Agent verifies via |
|----|-------------------|
| UAT-00 | `run_uat_e2e_verification.py` all steps |
| UAT-01 Register | `register_wizard_smoke` + `test_kavach_scenarios.py` |
| UAT-02 Positions | `validate_fixture` + ShadowBroker pytest |
| UAT-03 LTP | `phase1_bot_check` + DRISHTI log scan |
| UAT-04 Deploy confirm | pytest deployment handlers + `data/uat/deployments/batman_*.json` after live register |

Live Telegram wizard proof remains optional; **gate** is headless script + pytest.

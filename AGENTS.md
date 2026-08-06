<!-- RAHUL SANDBOX BANNER -->
> **RAHUL SANDBOX** (`/home/ubuntu/rahul_Changes`)  
> Before any work: read `RAHUL_CHANGES_README.md`, `NEW_CHAT_HANDOFF.md`, `docs/PROJECT_DIRECTION.md`.  
> Runtime: `/home/ubuntu/Trading_Runtime_Rahul` only. Do not use Kamalji’s `/home/ubuntu/Trading_Runtime`.  
> Baseline behaviour = Kamalji Batman; this track improves architecture + Place Order execution integration.

# Batman v3 — Agent Playbook (Cursor)

Operator gives **instructions only**. The agent **executes** — reads code, runs scripts, fixes issues, verifies gates, updates docs when scope changes.

## First reads (before multi-file work)

| Priority | File | Why |
|----------|------|-----|
| 0 | `context/KAMALJI_HANDOFF.md` | **Kamalji ownership** — start every new chat here |
| 0a | `context/CURSOR_AI_GUIDE_FOR_KAMALJI.md` | How Kamalji should drive Cursor safely |
| 0b | `NEW_CHAT_HANDOFF.md` | Session bridge (ownership banner + older notes) |
| 0c | `docs/BOT_LIFECYCLE_ARCHITECTURE.md` | **Bot start/stop** — Tier 1–3 lifecycle design |
| 1 | `CONTEXT.md` | Current scope, architecture, status |
| 2 | `UAT_E2E_AGENT.md` | **Autonomous UAT loop** — script + agent prompt (no manual Telegram testing) |
| 3 | `PHASE1_REQUIREMENTS.md` | Locked operator requirements |
| 4 | `GATE5_RUNBOOK.md` | ATO / mock-order test procedure |
| 4b | `docs/KAVACH_ATO_OPERATOR_RULES.md` | **KAVACH/ATO operator rules** — register, Complete, manual legs, economy testing (Q1–Q46 locked) |
| 4c | `docs/KAVACH_TOMORROW_HANDOFF.md` | **KAVACH session bridge** — implementation status, tomorrow agenda (read after restart) |
| 4d | `docs/KAVACH_OPEN_QUESTIONS.md` | **Pending operator Q&A** — Q47–Q54 awaiting answers |
| 4e | `docs/INCIDENT_MANAGEMENT_SYSTEM.md` | **Incident RCA registry + knowledge base** |
| 5 | `reference/FUNCTION_OWNERSHIP_INDEX.md` | Where logic lives — avoid full-repo scans |
| 6 | `reference/TECHNICAL_CHANGE_INDEX.md` | Side effects when touching owners |

## Project map

```
bat_telegram/bots/     DRISHTI, KAVACH, JAGRAN Telegram handlers (active)
core/                  broker, state, event_bus, config, token_store
modules/               ATO protection, algo modules
scripts/               audit, bot checks, stop helpers
Execution/             Start/Stop .bat launchers (Windows)
tests/                 pytest suite
data/                  runtime state, LTP cache, analytics (gitignored secrets)
config/                global settings + Dhan .env
telegram/bots/*/       token.env + params.json per bot (secrets — never commit)
simulator/             local UI harness for mock flows
```

## Active Phase 1 bots (independent processes — locked)

| Bot | Entry | Role |
|-----|-------|------|
| DRISHTI | `run_drishti.py` | JWT, LTP poll → `data/nifty_ltp_cache.json`, health |
| KAVACH | `run_kavach.py` | Register, ATO, pause/resume, algo |
| JAGRAN | `run_jagran.py` | Critical incident alerts |

**Architecture lock (`CONTEXT.md` §23):** **Four** separate OS processes (DRISHTI, KAVACH, JAGRAN, SARANSH) — **do not merge** pairs. Coordination via disk only. Start order: DRISHTI → KAVACH → JAGRAN → SARANSH optional last (`phase1_start_all.py`). **UAT primary** on laptop. Chats: Batman Alerts (trio) + Non Critical Alerts (SARANSH).

**Out of scope:** LAKSHMI, SANCHALAK, SARANSH — do not wire into Phase 1 startup. **`main.py` single-process orchestrator** — not Phase 1 laptop runtime.

## Voice control (hands-free)

Operator uses voice input — avoid approval stalls. One-time Cursor UI: **Run Everything**, protections off, sound on. Full checklist: **`VOICE_CONTROL_CURSOR.md`**.

## Agent execution defaults

1. **Python:** always `.venv\Scripts\python.exe` (never system Python).
2. **After code changes:** run quality gates (see below).
3. **Testing ownership:** agent verifies all changed Telegram handlers and modules — see `TESTING_PROTOCOL.md` (implement → test → logs → fix, up to 4 cycles). Operator does not manual-test routine fixes.
4. **Bot checks:** `scripts/audit_bot_tokens.py` then `scripts/phase1_bot_check.py`.
5. **Secrets:** read `token.env` / `config/.env` from disk — never ask operator to paste tokens.
6. **Minimal diffs:** match existing patterns; one concern per change.
7. **Do not touch without explicit ask:** DRISHTI Health/Ping/Token Status handlers; five-bot startup.

## Quality gates (run autonomously)

```powershell
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m black --check .
.venv\Scripts\python.exe -m mypy core modules bat_telegram
.venv\Scripts\python.exe -m pytest tests -q --tb=short
```

Or: **Terminal → Run Task → Quality gates** or `Ctrl+Shift+B`.

**UAT mode (virtual broker / Sensibull book):** after gates, run:

```powershell
.venv\Scripts\python.exe scripts\run_uat_e2e_verification.py
```

Full autonomous loop: **`UAT_E2E_AGENT.md`** (paste prompt into Agent; agent iterates up to 4 cycles without operator testing).

## Phase 1 bot lifecycle (operator + agent)

- **Operator:** start/stop only via `Execution\Start Bots\` and `Execution\Stop Bots\` — never CMD window X, never ad-hoc `python run_*.py`. Full contract: `CONTEXT.md` §3.1 · guide: `Execution/PHASE1_ROBOT_LAUNCHER.md`.
- **Bulk:** `Phase 1 Start All Robots.bat` / `Phase 1 Stop All Robots.bat`; engines `scripts/phase1_start_all.py`, `scripts/phase1_stop_all.py`; logs under `logs/runtime/.../launchers/`.
- **Visibility:** `Show Bot Status.bat` in Start Bots or Stop Bots — must show **STOPPED** before trusting a stop.
- **Preflight:** start `.bat` calls `scripts/ensure_bot_stopped.py` after silent stop; blocks duplicate/orphan starts.
- **Agent:** `scripts/stop_all_phase1.py`, `stop_*.py`, `diagnose_robot.py`, `bot_status.py`, `incident_report.py`; domain incidents: `INCIDENT_TRACKER.md`.

## Common operator requests → agent actions

| Instruction | Agent does |
|-------------|------------|
| "Check bots" | `bot_status.py all` + audit + phase1_bot_check; read logs if fail |
| "Feedback loop" | `scripts/run_agent_feedback_loop.py` (or `Execution\Run Agent Feedback Loop.bat`) — diagnose → test → logs, up to 4 cycles |
| "Start KAVACH" | Use task **Restart KAVACH** or Start Bots bat (not raw run_kavach.py for operator) |
| "Fix ATO bug" | Read `modules/ato_protection.py`, `GATE5_RUNBOOK.md`, run pytest |
| "Why no LTP?" | Check `data/nifty_ltp_cache.json`, DRISHTI logs, `core/broker.py` |
| "Gate 5 prep" | Follow `GATE5_RUNBOOK.md` checklist; verify mock mode |

## Key data paths

| Artifact | Path |
|----------|------|
| NIFTY LTP cache | `Desktop/Batman Executed Data/Data and Reports/data/shared/nifty_ltp_cache.json` |
| Runtime state | `Desktop/Batman Executed Data/Data and Reports/data/uat/batman_state.json` (UAT) |
| Access token | `Desktop/Batman Executed Data/Data and Reports/data/shared/access_token.json` |
| UAT logs | `Desktop/Batman Executed Data/Logs/uat/runtime/...` |
| Reports / Excel | `Desktop/Batman Executed Data/Data and Reports/reports/` |
| Secrets | `Desktop/Batman-Secrets/` (Telegram + Dhan `.env`) |
| Code repo | Git only — see `docs/MULTI_DEV_SETUP.md` |

## Continuity (significant sessions only)

Update when architecture, scope, or gate status changes:

- `SESSION_CAPTURE_LOG.md` — what was done
- `IMPLEMENTATION_TRACKER.md` — if feature status changed
- `CONTEXT.md` — if scope/architecture changed

## Register / ATO reminders

- Broker **qty** vs UI **lots** (NIFTY lot size 65 from params).
- ATO qty from managed BUY qty; use `normalize_buffer_field` from `core.buffer_config`.
- Telegram MarkdownV2: real `\n` newlines, not `r"\n"`.
- After **Batman Complete**: verified cleanup → fresh `/register` (4-leg).

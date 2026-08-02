# Batman v3 — Technical Implementation Playbook

<!-- markdownlint-disable MD022 MD032 -->

Last updated: 2026-05-17
Audience: Developers building, extending, or operating a similar Telegram-controlled automated trading system.

## 1. What This Project Is

Batman v3 is a single-process, multi-bot Python trading platform where all operational control is through Telegram.

Primary goals:
- Safe automation with human-visible controls.
- Strong separation of responsibilities per bot/module.
- Operational observability (logs, telemetry, incident ledgers).
- Fast iteration with testability and clear file ownership.

## 2. Architecture Methodology Used

### 2.1 Core architectural approach
- Single Python process with asyncio for bot orchestration.
- Modular trading logic in independent modules.
- Shared core services injected into modules/bots:
  - Broker adapter
  - State manager
  - Event bus
- Telegram as command/control plane.

Why this approach:
- Reduced process complexity (no inter-process communication needed).
- Easier state sharing and event propagation.
- Lower operational overhead on VPS/laptop.

### 2.2 Separation of concerns (strict boundaries)
- `core/`: infra primitives and adapters.
- `modules/`: strategy/runtime logic.
- `bat_telegram/bots/`: bot-facing UX and command handlers.
- `telegram/design/`: design contracts and flow docs.
- `reference/`: decision, discussion, and implementation governance.

### 2.3 Incremental delivery methodology
- Design lock first (what behavior should be).
- Small, atomic coding waves.
- Validate with tests + static checks.
- Update continuity artifacts (tracker, session logs, context).

## 3. Active Bot System Model

Active testing scope currently:
- DRISHTI: token + infra health surface.
- KAVACH: trading command surface and deployment flow.
- SANCHALAK: global control-plane guardrails.
- SARANSH: summary/reporting surface.
- JAGRAN: incident routing target.

Guiding principle:
- Ownership per bot is explicit. Cross-bot interactions are via shared state/events, not hidden coupling.

## 4. Technical Building Blocks and Co-dependencies

### 4.1 Runtime co-dependencies
- `main.py` wires:
  - `core/broker.py`
  - `core/state.py`
  - `core/event_bus.py`
  - module instances
  - bot applications
- Modules depend on injected core services, not bot internals.
- Bots depend on shared state and module map only where explicitly required.

### 4.2 Control-plane co-dependencies
- Pause/read-only enforcement is centralized in `bat_telegram/control.py`.
- Runtime mode is broker-enforced (orders blocked in mock mode).
- SANCHALAK controls global run/pause/mode state; downstream bots honor it.

### 4.3 Incident/observability co-dependencies
- Incident publisher (`bat_telegram/incident_publisher.py`) is shared by bots/main.
- Source + JAGRAN dual-routing policy is controlled by allowlist/config.
- Analytics artifacts are written to `data/analytics/`.

## 5. Python Libraries and Why They Are Used

Defined in `requirements.txt`:

### Core runtime
- `Dhan-Tradehull>=3.2.0`
  - Purpose: Broker API wrapper.
  - Why: Trading execution, positions, LTP integration.

- `python-telegram-bot>=20.0`
  - Purpose: Async Telegram bot framework.
  - Why: Reliable command handlers and callback workflows.

- `python-dotenv>=1.0.0`
  - Purpose: Environment variable loading.
  - Why: Secret/config separation.

### Data and exports
- `pandas>=2.0.0`
  - Purpose: Tabular analytics processing.
  - Why: CSV/XLSX ledger and summary generation.

- `openpyxl>=3.1.0`
  - Purpose: Excel engine for pandas writes.
  - Why: Multi-sheet workbook output.

### OCR utilities (support tooling)
- `rapidocr-onnxruntime>=1.4.4`
- `opencv-python-headless>=4.13.0`
  - Purpose: Local OCR/image preprocessing support scripts.

### Testing
- `pytest>=7.4.0`
- `pytest-asyncio>=0.21.0`
- `pytest-cov>=4.1.0`

## 6. Development Toolchain and Extensions

### VS Code extensions used/recommended
From `.vscode/extensions.json`:
- `ms-python.python`
- `ms-python.vscode-pylance`
- `charliermarsh.ruff`
- `ms-python.black-formatter`
- `ms-python.mypy-type-checker`
- `littlefoxteam.vscode-python-test-adapter`
- `SonarSource.sonarlint-vscode`
- `EditorConfig.EditorConfig`
- `streetsidesoftware.code-spell-checker`
- `tamasfe.even-better-toml`
- `eamodio.gitlens`
- `mhutchie.git-graph`

Why this set:
- Python authoring + type analysis.
- Lint/format/type consistency.
- Test execution and review ergonomics.
- Collaboration, navigation, and quality hygiene.

### Standard quality gates
- Ruff (lint)
- Black (format)
- Mypy (runtime typing)
- Pytest (behavioral tests)

## 7. Advanced Patterns Used

- State-driven bot interlocks (pause/read-only/global mode).
- Idempotency and safety guards for trading actions.
- Event-driven notifications via pub/sub.
- Startup restore + validation flows for deployment continuity.
- Snapshot-safe analytics export strategy.
- Optional bot startup based on secret presence.

## 8. Methodology for Making Changes Safely

### 8.1 Change routing process (used in this repo)
1. Identify function owner in `reference/FUNCTION_OWNERSHIP_INDEX.md`.
2. Confirm side effects via `reference/TECHNICAL_CHANGE_INDEX.md`.
3. Apply minimal patch in owner files.
4. Run quality gates.
5. Update continuity artifacts.

### 8.2 Mandatory continuity artifacts
- `IMPLEMENTATION_TRACKER.md`
- `IMPLEMENTATION_TRACKER.csv`
- `SESSION_CAPTURE_LOG.md`
- `CONTEXT.md` (when architecture/scope/status changes)
- `reference/DECISION_REGISTER.md` (new locked decisions)
- `reference/DISCUSSION_CAPTURE.md` (session summary)

## 9. Infrastructure and Environment Expectations

### 9.1 Python/runtime
- Python 3.12.x
- Project virtual environment (`.venv`) in workspace

### 9.2 Secret/config model
- `token.env` files per bot for secrets.
- `params.json` files per bot for non-secret behavior settings.
- `config/settings.json` for global strategy/runtime settings.

### 9.3 Execution environments
- Laptop simulation/testing mode.
- VPS target for long-running/production operation.

## 10. How to Build a Similar Project (Blueprint)

### Step 1: Define ownership map
- Split infra, strategy modules, and bot interfaces.
- Define explicit ownership per bot and per module.

### Step 2: Implement core primitives
- Broker adapter
- State manager
- Event bus
- Config loader

### Step 3: Implement command/control bots
- Infra bot (token/health)
- Trading bot (entry/exit/ops commands)
- Control-plane bot (global mode/pause)
- Reporting bot (summary/evidence)
- Incident bot/channel (critical escalation)

### Step 4: Add observability early
- Structured logs
- Action telemetry CSV
- Incident ledger with export

### Step 5: Add simulator/harness
- Reproduce command surface in local simulator
- Validate behavior before live rollout

### Step 6: Enforce quality gates
- Lint + format + typing + tests in every change wave

### Step 7: Add continuity governance
- Decision and discussion capture
- Tracker status discipline
- Session handoff protocol

## 11. Known Gap Classes to Watch in Similar Systems

- Duplicate analytics writes during restart/retry paths.
- Silent export failures due engine/dependency mismatch.
- Design-doc drift after fast coding waves.
- Alias drift between bot command UX and runtime handlers.
- Optional-secret startup assumptions causing environment mismatch.

## 12. Practical Onboarding Checklist for New Developers

1. Install Python and create `.venv`.
2. Install `requirements.txt`.
3. Install recommended VS Code extensions.
4. Run quality gates once (ruff/black/mypy/pytest).
5. Read:
   - `CONTEXT.md`
   - `IMPLEMENTATION_TRACKER.md`
   - `reference/FUNCTION_OWNERSHIP_INDEX.md`
   - `reference/TECHNICAL_CHANGE_INDEX.md`
6. Configure bot token.env files for intended test scope.
7. Start with simulator validation before live validation.

## 13. Glossary (project-specific)

- ATO: Adjustment To Original protection cycle.
- Control-plane: Global bot-mediated runtime governance.
- Active scope: Current set of bots/features under immediate implementation/testing.
- OPS_VALIDATION_PENDING: Code implemented but operational evidence not fully captured yet.

## 14. Final Note

This playbook documents not only what was built, but how it was built and why. It is intended to make replication, maintenance, and safe evolution of this class of system significantly easier.

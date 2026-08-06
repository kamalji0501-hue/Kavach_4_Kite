#!/usr/bin/env python3
"""
Batman v3 — Complete Project File Inventory Generator
======================================================
Generates PROJECT_FILE_INVENTORY.xlsx in the workspace root.

Sheets:
  Overview          — Module summary table + architecture blurb
  Core Runtime      — core/ shared services
  Modules           — modules/ trading logic
  Telegram Bots     — bat_telegram/ runtime bot code
  Simulator         — simulator/ local test harness
  Tests             — tests/ pytest suite
  Config            — config/, .vscode/, .github/, root config files
  Design & Docs     — telegram/design/, root docs, CONTEXT.md etc.
  Reference         — reference/ governance artifacts
  Tools             — tools/ scripts
  Bot Legacy        — bot/ retired folder
  Data & Analytics  — data/ runtime-generated files
  Testing Mocks     — testing/ mocks and scenario docs
  Assets            — screenshots/, image/, logs/, Prod Data/
  Python Packages   — .venv installed packages (key ones annotated)
  Cache & Generated — .ruff_cache/, .mypy_cache/, .pytest_cache/, __pycache__

Run:
    .venv\\Scripts\\python.exe tools\\generate_file_inventory.py
"""

from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────────────────────────────────────
# STYLING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

STATUS_BG = {
    "ACTIVE": "E2EFDA",  # light green
    "RETIRED": "FCE4D6",  # light orange
    "CONFIG": "DDEBF7",  # light blue
    "TEMPLATE": "FFF2CC",  # light yellow
    "DESIGN": "E8D5F5",  # light purple
    "DOCS": "EDE7F6",  # soft lavender
    "GENERATED": "EDEDED",  # light grey
    "CACHE": "EDEDED",
    "MOCK": "FFF2CC",
    "ASSET": "FFF9E6",
}

HDR_NAVY = "1F3864"
HDR_BLUE = "2E75B6"
ALT_ROW = "F7F7F7"


def fill(hex_col: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_col)


def thin_border() -> Border:
    s = Side(style="thin", color="CCCCCC")
    return Border(left=s, right=s, top=s, bottom=s)


def hdr_font(fg: str = "FFFFFF", size: int = 10) -> Font:
    return Font(name="Calibri", color=fg, bold=True, size=size)


def body_font(bold: bool = False, size: int = 9) -> Font:
    return Font(name="Calibri", bold=bold, size=size)


def c_align(wrap: bool = False) -> Alignment:
    return Alignment(horizontal="center", vertical="center", wrap_text=wrap)


def l_align(wrap: bool = True) -> Alignment:
    return Alignment(horizontal="left", vertical="top", wrap_text=wrap)


def write_header_row(ws, headers, row: int = 1, bg: str = HDR_NAVY):
    """Write a formatted header row. headers = list of (label, col_width)."""
    for col_idx, (label, width) in enumerate(headers, 1):
        c = ws.cell(row=row, column=col_idx, value=label)
        c.fill = fill(bg)
        c.font = hdr_font()
        c.alignment = c_align(wrap=True)
        c.border = thin_border()
        ws.column_dimensions[get_column_letter(col_idx)].width = width


def write_data_row(ws, row_idx: int, values: list, status: str = "ACTIVE"):
    bg_hex = STATUS_BG.get(status, ALT_ROW if row_idx % 2 == 0 else "FFFFFF")
    for col_idx, val in enumerate(values, 1):
        c = ws.cell(row=row_idx, column=col_idx, value=str(val) if val is not None else "")
        c.fill = fill(bg_hex)
        c.font = body_font(bold=(col_idx == 1))
        c.alignment = l_align()
        c.border = thin_border()
    ws.row_dimensions[row_idx].height = 14


# ─────────────────────────────────────────────────────────────────────────────
# KNOWLEDGE BASE
# ─────────────────────────────────────────────────────────────────────────────
# Each entry: path -> dict with keys:
#   category, sub, purpose, what_it_does, inputs, outputs, depends_on, supports, status, notes

KB: dict = {}


def _kb(
    path: str,
    category: str,
    sub: str,
    purpose: str,
    what_it_does: str,
    inputs: str,
    outputs: str,
    depends_on: str,
    supports: str,
    status: str = "ACTIVE",
    notes: str = "",
) -> None:
    KB[path] = dict(
        category=category,
        sub=sub,
        purpose=purpose,
        what_it_does=what_it_does,
        inputs=inputs,
        outputs=outputs,
        depends_on=depends_on,
        supports=supports,
        status=status,
        notes=notes,
    )


# ── ROOT FILES ────────────────────────────────────────────────────────────────
_kb(
    "main.py",
    "Runtime",
    "Entry Point",
    "Process entry point — launches all bots and AlgoScheduler as async tasks",
    "Bootstraps Config, BatmanBroker, StateManager, EventBus; starts DRISHTI/KAVACH/JAGRAN/SANCHALAK/SARANSH bots as asyncio tasks; starts AlgoScheduler; hard-fails if JAGRAN token.env is missing; publishes heartbeat to JAGRAN channel; runs asyncio event loop until shutdown.",
    "config/settings.json, telegram/bots/*/token.env, data/access_token.json (optional)",
    "Running asyncio process with all bots and modules active",
    "core/config.py, core/broker.py, core/state.py, core/event_bus.py, bat_telegram/loader.py, bot/algo_scheduler.py, bat_telegram/incident_publisher.py",
    "ALL bots and modules",
    "ACTIVE",
    "JAGRAN startup gate: process exits if JAGRAN token.env is absent or invalid.",
)

_kb(
    "pyproject.toml",
    "Config",
    "Project Config",
    "Python project configuration — Ruff, Black, pytest, mypy settings",
    "Defines linter rules (Ruff: E,W,F,B,I), formatter line-length (Black: 100), test discovery (tests/), mypy type-check scope (core,modules,bat_telegram,main.py), and all CI gate parameters.",
    "N/A",
    "Toolchain behaviour for CI/CD and local dev",
    "N/A",
    "All Python source files",
    "CONFIG",
    "Single source of truth for all quality-gate configuration.",
)

_kb(
    "requirements.txt",
    "Config",
    "Dependencies",
    "Runtime Python dependency manifest",
    "All pip-installable packages required for production. Install with: pip install -r requirements.txt.",
    "N/A",
    "Installed packages in .venv",
    "N/A",
    "All Python modules",
    "CONFIG",
    "Keep in sync with actual imports.",
)

_kb(
    "batman.service",
    "Config",
    "VPS Systemd Unit",
    "Linux systemd service file for auto-starting Batman on VPS reboot",
    "Defines service name, working directory (/opt/batman_v3), ExecStart (python main.py), restart policy (always, 10s delay), EnvironmentFile (config/.env), and logging to journald.",
    "config/.env environment variables on VPS",
    "Auto-started process via systemd on VPS boot",
    "main.py",
    "VPS deployment workflow",
    "CONFIG",
    "Copy to /etc/systemd/system/batman.service; run: systemctl enable batman && systemctl start batman",
)

_kb(
    "batman_flowchart.html",
    "Docs",
    "Visual Design",
    "Browser-viewable HTML flowchart of Batman v3 architecture",
    "Static HTML page rendering a Mermaid/D3 flowchart of the full runtime architecture: startup → bot tasks → module scheduling → ATO cycles → hedge → EOD.",
    "N/A (static HTML)",
    "Visual reference page opened in a browser",
    "N/A",
    "Developer/stakeholder onboarding",
    "DOCS",
)

_kb(
    "flowchart.md",
    "Docs",
    "Visual Design",
    "Markdown source for architecture flowchart diagrams",
    "Contains Mermaid diagram definitions for system architecture and bot interaction flows. Source for batman_flowchart.html.",
    "N/A",
    "Rendered diagrams in Markdown viewers or batman_flowchart.html",
    "N/A",
    "batman_flowchart.html",
    "DOCS",
)

_kb(
    "CONTEXT.md",
    "Docs",
    "Governance",
    "Master project context — single source of truth for current state and design locks",
    "Tracks: active scope lock, implementation status (CODED/PENDING), design decisions that are LOCKED, architecture summary, module-to-file map, task-to-file routing guide, quality gate evidence, and closure criteria. AI tools read this at session start.",
    "Session discussions, implementation work",
    "AI session context, developer handoff document",
    "All project files (meta-reference)",
    "All files",
    "DOCS",
    "ALWAYS read this first at session start. Updated every meaningful work session.",
)

_kb(
    "DESIGN.md",
    "Docs",
    "Governance",
    "Detailed design decisions and locked specifications",
    "Captures all locked design: bot responsibility matrix, command contracts, ATO logic invariants (fire at sell_strike NOT sell_strike+buffer), incident routing policy, 6-step wizard definition, control-plane interlocks, break-even confirm flow.",
    "User requirements, architecture discussions",
    "Implementation contract for all bots/modules",
    "N/A",
    "bat_telegram/bots/*.py, modules/*.py",
    "DOCS",
)

_kb(
    "IMPLEMENTATION_TRACKER.md",
    "Docs",
    "Governance",
    "Feature implementation status matrix",
    "Tracks every feature with status (CODED / DESIGN_LOCKED_NOT_CODED / OPS_VALIDATION_PENDING / PENDING_DESIGN), evidence links, and next actions. Updated every session.",
    "Session work",
    "Prioritization guide, audit trail",
    "N/A",
    "All features",
    "DOCS",
)

_kb(
    "IMPLEMENTATION_TRACKER.csv",
    "Docs",
    "Governance",
    "CSV version of implementation tracker for spreadsheet tooling",
    "Machine-readable version of IMPLEMENTATION_TRACKER.md. Import to Excel/Sheets for filtering.",
    "IMPLEMENTATION_TRACKER.md",
    "Spreadsheet/CI tooling",
    "IMPLEMENTATION_TRACKER.md",
    "N/A",
    "DOCS",
)

_kb(
    "SESSION_CAPTURE_LOG.md",
    "Docs",
    "Governance",
    "Chronological audit trail of design and implementation sessions",
    "One entry per meaningful session: date, focus, tracker delta, files updated, quality gate evidence, next action. Provides full project history for continuity.",
    "Session work",
    "Audit trail",
    "CONTEXT.md",
    "All files",
    "DOCS",
)

_kb(
    "JAGRAN_ERROR_MATRIX.md",
    "Docs",
    "Governance",
    "JAGRAN incident routing allowlist and error matrix",
    "Defines which error scenarios from which bots/modules route to JAGRAN alert channel. Includes scenario ID, source bot, priority level, routing policy, and wildcard patterns.",
    "Design discussions",
    "Incident routing configuration for incident_publisher.py",
    "bat_telegram/incident_publisher.py",
    "bat_telegram/incident_publisher.py",
    "DOCS",
)

_kb(
    "JAGRAN_ERROR_MATRIX.csv",
    "Docs",
    "Governance",
    "CSV version of JAGRAN error matrix for tooling",
    "Machine-readable allowlist for JAGRAN incident routing. Mirrors JAGRAN_ERROR_MATRIX.md.",
    "JAGRAN_ERROR_MATRIX.md",
    "bat_telegram/incident_publisher.py reference",
    "JAGRAN_ERROR_MATRIX.md",
    "N/A",
    "DOCS",
)

_kb(
    "METRICS_SUMMARY.md",
    "Docs",
    "Governance",
    "Code metrics, effort breakdown, and ROI analysis",
    "Summarises total LOC, developer-hours estimate, completion %, Copilot ROI multiplier, risk assessment, and rolling feature roadmap.",
    "Codebase analysis",
    "Management/stakeholder reporting",
    "N/A",
    "N/A",
    "DOCS",
)

_kb(
    "OPEN_QUESTIONS.md",
    "Docs",
    "Governance",
    "Parked design questions awaiting user answers",
    "Numbered register of open questions (OQ-xx) covering hedge logic decisions, incident containment policy, service restart strategy, and advanced control scenarios. Resolved questions moved to DECISION_REGISTER.",
    "Design sessions",
    "Future design decisions",
    "N/A",
    "DESIGN.md, CONTEXT.md",
    "DOCS",
)

_kb(
    "fixes",
    "Docs",
    "Session Notes",
    "Ad-hoc fix notes from development sessions",
    "Short-form notes of fixes applied during sessions. Not structured — raw session scratch pad.",
    "N/A",
    "Developer reference",
    "N/A",
    "N/A",
    "DOCS",
)

_kb(
    "Hedge Box Trading View/Hedge Box Trading View.txt",
    "Assets",
    "Reference Data",
    "TradingView export of Hedge Box levels — raw text data",
    "Text export from TradingView platform showing Hedge Box zone levels, entry/exit price points, and associated NIFTY price annotations for the active hedge configuration.",
    "TradingView platform export",
    "Reference for hedge box zone calibration",
    "N/A",
    "telegram/design/hedge_box_design.md, modules/ratripal.py",
    "ASSET",
)

# ── CORE ──────────────────────────────────────────────────────────────────────
_kb(
    "core/__init__.py",
    "Core Runtime",
    "Package Init",
    "Python package marker for core/",
    "Empty __init__.py making core/ importable as a Python package.",
    "N/A",
    "Package namespace",
    "N/A",
    "All core/ modules",
    "ACTIVE",
)

_kb(
    "core/broker.py",
    "Core Runtime",
    "Broker Integration",
    "Dhan-Tradehull broker wrapper — all market operations go through here",
    "Wraps Tradehull SDK. Key methods: connect_with_token(token), hot_reload_token(token) — swaps JWT without restart, get_nifty_ltp(), get_gift_ltp(), get_live_pnl(), place_order(), close_position(), needs_reauth(). mock_mode=True blocks all real order placement during testing.",
    "Dhan JWT access token, Tradehull SDK",
    "BatmanBroker instance consumed by all 7 modules and main.py",
    "core/token_store.py, Dhan_Tradehull (PyPI), dhanhq (PyPI)",
    "modules/*.py, main.py, bat_telegram/bots/drishti/bot.py",
    "ACTIVE",
    "hot_reload_token() is the live token swap path. NEVER restart the process for a new token.",
)

_kb(
    "core/config.py",
    "Core Runtime",
    "Configuration",
    "settings.json loader with dot-path access and ${ENV_VAR} expansion",
    "Loads config/settings.json at startup. Resolves ${VAR} placeholders against os.environ. Provides Config.get('section.key') dot-path access. Raises ConfigError on missing required variables.",
    "config/settings.json, environment variables",
    "Config singleton used by all modules, bots, and main.py",
    "config/settings.json",
    "All modules, main.py",
    "ACTIVE",
    "Never read settings.json directly — always use Config.get(). All secrets arrive via env vars.",
)

_kb(
    "core/event_bus.py",
    "Core Runtime",
    "Event System",
    "Async pub/sub event bus — decouples modules from bots",
    "Defines Event enum (ATO_TRIGGERED, ATO_EXITED, POSITION_UPDATE, EMERGENCY_EXIT, INCIDENT, etc.). EventBus class: subscribe(event, callback), publish(event, payload). Async dispatch. All cross-component communication goes through events.",
    "Event enum values, async subscriber callbacks",
    "Event notifications dispatched to subscribed bots and modules",
    "N/A",
    "modules/*.py, bat_telegram/bots/*.py",
    "ACTIVE",
    "Modules never import bot code. Bots subscribe to events emitted by modules.",
)

_kb(
    "core/exceptions.py",
    "Core Runtime",
    "Error Types",
    "Custom exception hierarchy for typed error handling",
    "Defines: BatmanError (base), BrokerError, ConfigError, TokenError, StateError, ModuleError. Enables typed except clauses and JAGRAN routing by error type.",
    "N/A",
    "Raised by core/ and modules/ code",
    "N/A",
    "All core/ and modules/ files",
    "ACTIVE",
)

_kb(
    "core/models.py",
    "Core Runtime",
    "Data Models",
    "Shared dataclasses and data models used across modules and bots",
    "Defines: DeploymentData, LegInfo (strike, symbol, qty), AtoState, PositionSnapshot, HedgeBoxDecision and similar typed dataclasses. Prevents dict-of-dicts anti-pattern.",
    "N/A",
    "Typed data objects passed between modules and bots",
    "N/A",
    "modules/*.py, bat_telegram/bots/*.py",
    "ACTIVE",
)

_kb(
    "core/module_base.py",
    "Core Runtime",
    "Module Framework",
    "Abstract base class that all 7 trading modules inherit",
    "Provides start()/stop()/is_running() async lifecycle. Injects State, EventBus, BatmanBroker, Config at construction. Sets up standard logger. Enforces consistent module contract for AlgoScheduler.",
    "State, EventBus, BatmanBroker, Config instances at injection",
    "Base class object inherited by 7 modules",
    "core/state.py, core/event_bus.py, core/broker.py, core/config.py",
    "modules/*.py",
    "ACTIVE",
)

_kb(
    "core/resilience.py",
    "Core Runtime",
    "Reliability",
    "Retry decorators and circuit breaker for transient failure handling",
    "Provides: @retry(max_attempts, delay_secs, backoff_factor) decorator with exponential backoff; CircuitBreaker(failure_threshold, recovery_timeout) class with half-open recovery. Applied to broker API calls and Telegram sends.",
    "Function to decorate, retry/circuit parameters",
    "Decorated functions with auto-retry or circuit-break behaviour",
    "N/A",
    "core/broker.py, bat_telegram/bots/*.py",
    "ACTIVE",
)

_kb(
    "core/runtime_logging.py",
    "Core Runtime",
    "Observability",
    "IST-millisecond text log writer with time-window file routing",
    "RuntimeLogger class: creates time-windowed log files named <bot>_YYYYMMDD_<window>.log in data/analytics/runtime_smoke/YYYY-MM/YYYY-MM-DD/logs/. Routes lines to both main runtime log and module-specific log. Files created on-demand (not pre-created). Publishes sink-failure incident on write error.",
    "Log line strings from all modules and bots, IST clock",
    "Time-segmented .log files in data/analytics/runtime_smoke/",
    "core/event_bus.py, config/settings.json (window definitions)",
    "All modules and bots",
    "ACTIVE",
    "Time windows configured in settings.json. Dual-sink: main + module-specific log per line.",
)

_kb(
    "core/state.py",
    "Core Runtime",
    "State Store",
    "Thread-safe in-memory key-value state store — single source of truth for all runtime state",
    "StateManager class: get(key, default), set(key, value), delete(key), snapshot() → dict. Uses threading.RLock. Optional disk persistence. All runtime flags, lifecycle flags, ATO state, deployment refs live here. No module holds its own state.",
    "Key-value pairs set by modules and bots",
    "Runtime state readable by all modules and bots",
    "N/A",
    "All modules and bots",
    "ACTIVE",
    "INVARIANT: no module maintains own state vars — all goes through State.",
)

_kb(
    "core/token_store.py",
    "Core Runtime",
    "Token Lifecycle",
    "Dhan access-token persistence to disk with TTL check",
    "TokenStore class: save(token) → writes token + saved_at to data/access_token.json; load() → reads and returns token; is_expired(ttl_hours=6) → bool; token_age_hours() → float. Used at startup to restore token across reboots.",
    "Dhan JWT access token string",
    "data/access_token.json (gitignored runtime file)",
    "N/A",
    "core/broker.py, bat_telegram/bots/drishti/bot.py, main.py",
    "ACTIVE",
    "data/access_token.json is gitignored. DRISHTI calls save() daily; broker calls load() at startup.",
)

_kb(
    "core/utils.py",
    "Core Runtime",
    "Utilities",
    "Shared utility functions across core/ and modules/",
    "IST datetime helpers (now_ist(), ist_date()), NIFTY strike rounding (round_to_50()), lot-size calculations, safe JSON load/dump (no key error), Telegram message formatting helpers, duration formatting.",
    "Various primitives (datetime, numbers, strings)",
    "Formatted/computed values",
    "N/A",
    "modules/*.py, bat_telegram/bots/*.py",
    "ACTIVE",
)

# ── MODULES ───────────────────────────────────────────────────────────────────
_kb(
    "modules/__init__.py",
    "Modules",
    "Package Init",
    "Python package marker for modules/",
    "Empty __init__.py.",
    "N/A",
    "Package namespace",
    "N/A",
    "All modules/ files",
    "ACTIVE",
)

_kb(
    "modules/ato_protection.py",
    "Modules",
    "ATO Logic",
    "ATO breach detection, cycle management, telemetry, and XLSX snapshots",
    "Core ATO loop: polls NIFTY LTP at configurable interval; checks LTP >= ce_sell_strike (CE side) or LTP <= pe_sell_strike (PE side) with optional entry buffer; on breach — places protective buy, enters cycle, waits for retrace; on retrace — exits, resets cycle. Appends every event to ato_execution_telemetry.csv and consolidated ato_trade_ledger.csv with duplicate-tail guard. Writes lock-safe XLSX snapshots. Respects ato_manage_sides (CE_ONLY/PE_ONLY/BOTH) gating.",
    "NIFTY LTP from broker, deployment JSON (sell strikes, retrace, entry buffer, poll interval, side config), State",
    "data/analytics/ato_execution_telemetry.csv, data/analytics/ato/ato_trade_ledger.csv, data/analytics/ato/snapshots/*.xlsx",
    "core/broker.py, core/state.py, core/event_bus.py, core/config.py",
    "kavach-2.0/bat_telegram/bots/kavach2/bot.py (ATO notifications), bat_telegram/bots/saransh/bot.py (EOD digest)",
    "ACTIVE",
    "ATO fires at sell_strike — NOT sell_strike + entry_buffer. Buffer adjusts trigger threshold only. Retrace points is EXIT buffer to prevent whipsaw.",
)

_kb(
    "modules/batman_entry.py",
    "Modules",
    "Trade Entry",
    "Iron condor deployment file writer — creates the shared deployment contract",
    "Writes data/deployments/batman_YYYY-MM-DD.json when KAVACH /register wizard completes (Step 6 confirm). JSON includes: 4 leg details (symbol, strike, expiry, qty), break-even levels, retrace_points, entry_buffer, poll_interval_secs, ato_manage_sides, deployment_date, wizard_timestamp.",
    "Leg selections from KAVACH wizard, config defaults",
    "data/deployments/batman_YYYY-MM-DD.json",
    "core/state.py, core/config.py",
    "modules/ato_protection.py, modules/overnight_hedge.py, modules/ratripal.py",
    "ACTIVE",
    "Deployment file is the shared contract between KAVACH and all runtime modules.",
)

_kb(
    "modules/emergency_exit.py",
    "Modules",
    "Risk Management",
    "Emergency exit — market-order flatten all open positions immediately",
    "EmergencyExit.execute(): places market-order SELL simultaneously for all open options legs; publishes EMERGENCY_EXIT event; logs outcome to state and telemetry. Triggered by KAVACH /exit after explicit YES confirmation within 30s. No retry — slippage accepted over delay risk.",
    "Open position list from State, broker connection",
    "Market orders placed, position state cleared, EMERGENCY_EXIT event published",
    "core/broker.py, core/state.py, core/event_bus.py",
    "kavach-2.0/bat_telegram/bots/kavach2/bot.py",
    "ACTIVE",
    "Nuclear option. /exit requires explicit YES within 30s. No retry.",
)

_kb(
    "modules/overnight_hedge.py",
    "Modules",
    "Hedge",
    "Post-market hedge placement — skipped on 0DTE (Tuesday)",
    "Triggers at 15:15 IST on 4DTE–1DTE days (Wednesday–Monday). Calls ratripal.determine_zone() to identify Hedge Box zone; calls ratripal.execute_hedge_buy() for KAVACH confirm prompt. Skips entirely on Tuesday (0DTE expiry day) to avoid buying worthless hedge.",
    "NIFTY spot, break-even levels from deployment, time (IST)",
    "Hedge buy order (via ratripal), deployment file updated with hedge details",
    "core/broker.py, core/state.py, modules/ratripal.py",
    "kavach-2.0/bat_telegram/bots/kavach2/bot.py (HITL confirm/deny)",
    "ACTIVE",
    "Tuesday = 0DTE: hedge skipped. White zone = break-even strike (no buy needed).",
)

_kb(
    "modules/position_monitor.py",
    "Modules",
    "Observability",
    "MTM polling — publishes live P&L events for LAKSHMI bot",
    "Polls broker.get_live_pnl() at configurable interval (default 5 min); publishes POSITION_UPDATE event with MTM snapshot dict (total_pnl, per_leg_pnl, unrealised_pnl); triggers PROFIT_ALERT/LOSS_ALERT events when configured thresholds crossed.",
    "Broker live P&L, config thresholds (settings.json)",
    "POSITION_UPDATE events on EventBus",
    "core/broker.py, core/event_bus.py, core/config.py",
    "bat_telegram/bots/lakshmi/bot.py",
    "ACTIVE",
)

_kb(
    "modules/profit_trailing.py",
    "Modules",
    "Risk Management",
    "0DTE trailing stop logic — locks in profits on Tuesday expiry day",
    "Activates only on Tuesday (0DTE). Monitors live MTM P&L against configurable trailing stop percentage. Moves stop-loss floor up as profit increases. Triggers close when stop-loss level is hit. Publishes TRAILING_STOP_HIT event.",
    "Live MTM from broker, trailing config from settings.json (trailing_pct, activation_threshold)",
    "Close orders via emergency_exit when trailing stop triggered, TRAILING_STOP_HIT event",
    "core/broker.py, core/state.py, core/config.py",
    "modules/emergency_exit.py, kavach-2.0/bat_telegram/bots/kavach2/bot.py",
    "ACTIVE",
)

_kb(
    "modules/ratripal.py",
    "Modules",
    "Hedge",
    "RATRIPAL — Hedge Box zone engine and broker-buy executor",
    "determine_zone(nifty_spot, breakeven, side) → zone (GREEN/ORANGE/BLUE/YELLOW/WHITE/NONE). execute_hedge_buy(): resolves target strike per zone, sends KAVACH confirm/deny callback prompt (60s timeout), places broker buy on confirm, writes hedge details to PRABHAT MUKTI handoff CSV, publishes JAGRAN incident on failure. Tuesday 0DTE: returns SKIP.",
    "NIFTY spot, break-even from deployment file, Hedge Box config from settings.json",
    "Hedge buy order placed, PRABHAT MUKTI CSV updated, KAVACH HITL prompt sent, JAGRAN on failure",
    "core/broker.py, core/state.py, core/event_bus.py, bat_telegram/incident_publisher.py",
    "kavach-2.0/bat_telegram/bots/kavach2/bot.py, modules/overnight_hedge.py",
    "ACTIVE",
    "Zone map: White=break-even strike (no buy on Tue), Green=1 inside, Orange=2, Blue=3, Yellow=4 strikes inside break-even.",
)

# ── BAT_TELEGRAM ──────────────────────────────────────────────────────────────
for _p in [
    "bat_telegram/__init__.py",
    "bat_telegram/bots/__init__.py",
    "bat_telegram/bots/_template/__init__.py",
    "bat_telegram/bots/artha/__init__.py",
    "bat_telegram/bots/drishti/__init__.py",
    "kavach-2.0/bat_telegram/bots/kavach2/__init__.py",
    "bat_telegram/bots/lakshmi/__init__.py",
    "bat_telegram/bots/sanchalak/__init__.py",
    "bat_telegram/bots/saransh/__init__.py",
]:
    _kb(
        _p,
        "Telegram Bots",
        "Package Init",
        f"Python package marker for {Path(_p).parent.name}/",
        "Empty __init__.py.",
        "N/A",
        "Package namespace",
        "N/A",
        "Sibling modules in package",
        "ACTIVE",
    )

_kb(
    "bat_telegram/loader.py",
    "Telegram Bots",
    "Config Loader",
    "Bot configuration loader — reads token.env + params.json per bot",
    "load_bot_config(bot_name) reads telegram/bots/<name>/token.env for BOT_TOKEN and CHAT_ID; merges with telegram/bots/<name>/params.json for all tunable params. Returns merged dict. Supports: DRISHTI, KAVACH, LAKSHMI, JAGRAN, SANCHALAK, SARANSH.",
    "telegram/bots/<name>/token.env (gitignored), telegram/bots/<name>/params.json",
    "Config dict with token, chat_id, and all bot-specific parameters",
    "N/A",
    "bat_telegram/bots/*.py, main.py",
    "ACTIVE",
    "token.env files are gitignored. params.json files are safe to commit.",
)

_kb(
    "bat_telegram/incident_publisher.py",
    "Telegram Bots",
    "Incident Routing",
    "JAGRAN incident publisher — dedup, recovery tracking, daily ledger, XLSX export",
    "publish_incident(scenario_id, source_bot, message): sends alert to source chat + JAGRAN channel per allowlist (wildcard support e.g. 'module_offline_*'); deduplicates within time window; tracks active/resolved incidents; appends to daily incidents CSV; exports Incidents/Recoveries/Combined XLSX workbook on retry schedule.",
    "Incident scenario_id, source bot name, message text, JAGRAN allowlist",
    "Telegram alerts, data/analytics/incidents/YYYY-MM-DD_incidents.csv, data/analytics/incidents/YYYY-MM-DD_incidents.xlsx",
    "bat_telegram/loader.py (JAGRAN config)",
    "All bots that raise incidents, main.py (heartbeat)",
    "ACTIVE",
    "Wildcard allowlist: 'module_offline_*' matches any module offline event.",
)

_kb(
    "bat_telegram/control.py",
    "Telegram Bots",
    "Control Plane",
    "Cross-bot control plane — shared pause/resume/mode state for all bots",
    "ControlPlane class: manages per-bot paused state and global execution mode (live/mock/paper). SANCHALAK writes to it; DRISHTI/KAVACH/SARANSH read from it to gate commands. State resets on process restart (in-memory only). Prevents conflicting simultaneous control actions via overlap guard.",
    "SANCHALAK commands (start_all/stop_all/pause_bot/resume_bot/set_mode)",
    "Paused/active state per bot, global mode flag",
    "N/A",
    "bat_telegram/bots/sanchalak/bot.py, kavach-2.0/bat_telegram/bots/kavach2/bot.py, bat_telegram/bots/drishti/bot.py, bat_telegram/bots/saransh/bot.py",
    "ACTIVE",
    "In-memory only — resets to defaults on restart. SANCHALAK is the only writer.",
)

_kb(
    "bat_telegram/bots/drishti/bot.py",
    "Telegram Bots",
    "DRISHTI Bot",
    "DRISHTI — broker health bot: daily JWT token delivery, fleet visibility, AlgoScheduler prompts",
    "Receives daily Dhan JWT from user → broker.hot_reload_token() → TokenStore.save(). Validates token by checking NIFTY + GIFT LTP (dual-check). Commands: /token <jwt>, /status (token age, broker health), /fleet_status (all 5 bots + 7 modules health table). Sends 9AM AlgoScheduler start prompt and configurable EOD stop prompt. Sends stale-token reminders at configurable intervals.",
    "Daily Dhan JWT from user, NIFTY/GIFT LTP from broker, fleet health from State",
    "Token persisted, broker hot-reloaded, Telegram fleet status/reminders",
    "core/token_store.py, core/broker.py, bat_telegram/loader.py, bat_telegram/control.py",
    "main.py, all bots (broker availability)",
    "ACTIVE",
    "DRISHTI is the ONLY bot that touches token management. /fleet_status is the canonical system health dashboard.",
)

_kb(
    "kavach-2.0/bat_telegram/bots/kavach2/bot.py",
    "Telegram Bots",
    "KAVACH Bot",
    "KAVACH — trading command bot: deploy wizard, ATO control, emergency exit, hedge confirm",
    "6-step /register wizard: (1) PE BUY strike, (2) PE SELL strike, (3) CE BUY strike, (4) CE SELL strike, (5) retrace_points (0/5/10/.../50), (6) ATO monitoring side (PE/CE/BOTH). Break-even confirm/edit flow. /exit market-order close (YES confirm, 30s timeout). /ato_status, /pause, /resume, /legs, /funds, /status, /batman_complete. Sends ATO trigger/exit notifications. Handles RATRIPAL hedge confirm/deny callbacks. Enforces paused-state read-only gating via control.py.",
    "User commands, deployment file, ATO state from core/state.py",
    "Deployment JSON (via batman_entry), ATO notifications, emergency orders",
    "core/state.py, core/broker.py, bat_telegram/loader.py, bat_telegram/control.py, modules/ato_protection.py",
    "modules/batman_entry.py, modules/emergency_exit.py, modules/ratripal.py",
    "ACTIVE",
    "Wizard 60s inactivity timeout. /exit requires explicit YES within 30s. /batman_complete archives deployment file.",
)

_kb(
    "bat_telegram/bots/lakshmi/bot.py",
    "Telegram Bots",
    "LAKSHMI Bot",
    "LAKSHMI — P&L and MTM reporting bot",
    "/pnl shows current mark-to-market P&L. Subscribes to POSITION_UPDATE events for alert-threshold notifications (profit/loss alerts). EOD P&L summary. Paused-state read-only gating. Currently wired but parked (optional phase).",
    "POSITION_UPDATE events from EventBus, broker MTM data",
    "Telegram P&L messages to LAKSHMI chat",
    "core/event_bus.py, core/state.py, bat_telegram/loader.py, bat_telegram/control.py",
    "modules/position_monitor.py",
    "ACTIVE",
    "/pnl is LAKSHMI-exclusive. KAVACH does NOT implement /pnl. Currently parked/optional.",
)

_kb(
    "bat_telegram/bots/saransh/bot.py",
    "Telegram Bots",
    "SARANSH Bot",
    "SARANSH — EOD analytics summary and digest bot",
    "Auto-generates EOD summary at configurable time (default 16:00 IST) and on /summary or /summary_eod commands. Summary 5 sections: (1) order count, (2) ATO impact (cycles, points lost, entry/re-entry impact), (3) daily P&L (one-lot + total-lot + %), (4) token status with guidance, (5) algo behaviour observations. Reads ato_execution_telemetry.csv for cycle metrics. Dual-delivery: Telegram + file to data/analytics/summaries/. Raises JAGRAN if either delivery fails.",
    "ATO telemetry CSV, State (positions, P&L), TokenStore age",
    "EOD summary Telegram message, data/analytics/summaries/YYYY-MM-DD_summary.txt",
    "core/state.py, core/token_store.py, bat_telegram/loader.py, bat_telegram/control.py, bat_telegram/incident_publisher.py",
    "data/analytics/summaries/, JAGRAN channel on failure",
    "ACTIVE",
    "Soft-fails ATO section if telemetry CSV is missing. /summary_eod triggers immediate full EOD run.",
)

_kb(
    "bat_telegram/bots/sanchalak/bot.py",
    "Telegram Bots",
    "SANCHALAK Bot",
    "SANCHALAK — global control plane bot with higher authority than KAVACH",
    "Commands: /start_all (starts all bots+modules), /stop_all (stops all; 60s confirm timeout), /pause_bot <name>, /resume_bot <name>, /set_mode live|mock|paper (60s confirm), /status_all (consolidated health of 5 bots + AlgoScheduler). Rejects overlapping confirmable actions. Writes to control.py. Optional startup — only if SANCHALAK token.env exists.",
    "SANCHALAK commands from authorised chat_id",
    "Control state changes via bat_telegram/control.py, Telegram confirmations",
    "bat_telegram/control.py, bat_telegram/loader.py",
    "All bots via control.py, main.py",
    "ACTIVE",
    "Optional startup. If token.env absent at launch, SANCHALAK is silently skipped.",
)

# ── BOT/ RETIRED ──────────────────────────────────────────────────────────────
_kb(
    "bot/__init__.py",
    "Bot Legacy",
    "Package Init",
    "Package marker for retired bot/ folder",
    "Empty __init__.py.",
    "N/A",
    "Package namespace (retired)",
    "N/A",
    "N/A",
    "RETIRED",
    "DO NOT add new code here. All runtime bot code is in bat_telegram/.",
)

_kb(
    "bot/algo_scheduler.py",
    "Bot Legacy",
    "Scheduler",
    "AlgoScheduler — starts/stops 7 trading modules on weekly schedule",
    "Schedules module start/stop by day-of-week and IST time. Default: Wed 09:00 start, Tue 15:30 stop. Accepts user-selected start time from DRISHTI 9AM prompt. Calls module.start() / module.stop() for each of the 7 modules. Still actively used by main.py despite being in retired folder.",
    "config/settings.json schedule keys, user-selected start time from DRISHTI",
    "Module lifecycle management (start/stop calls on all 7 modules)",
    "core/config.py, All modules/",
    "main.py, bat_telegram/bots/drishti/bot.py",
    "RETIRED",
    "File is in retired bot/ folder but still actively called from main.py. Future: move to bat_telegram/.",
)

_kb(
    "bot/auth.py",
    "Bot Legacy",
    "Authentication",
    "Legacy PIN/TOTP authentication helper — replaced by access_token mode",
    "Originally handled PIN+TOTP auth flow for Dhan broker. Fully replaced by JWT access_token mode via DRISHTI.",
    "N/A",
    "N/A",
    "N/A",
    "N/A",
    "RETIRED",
    "Not used. Delete safe.",
)

_kb(
    "bot/bot_manager.py",
    "Bot Legacy",
    "Bot Manager",
    "Legacy bot manager — replaced by main.py asyncio task launch",
    "Earlier version of multi-bot lifecycle management. Replaced by direct asyncio.create_task() pattern in main.py.",
    "N/A",
    "N/A",
    "N/A",
    "N/A",
    "RETIRED",
    "Not used. Delete safe.",
)

_kb(
    "bot/health_bot.py",
    "Bot Legacy",
    "Health Bot",
    "Legacy health monitoring bot — replaced by DRISHTI fleet_status + JAGRAN",
    "Earlier infrastructure health notification bot. Superseded by DRISHTI /fleet_status and incident_publisher.",
    "N/A",
    "N/A",
    "N/A",
    "N/A",
    "RETIRED",
    "Not used. Delete safe.",
)

_kb(
    "bot/handlers/__init__.py",
    "Bot Legacy",
    "Package Init",
    "Package marker for retired handlers/",
    "Empty __init__.py.",
    "N/A",
    "N/A",
    "N/A",
    "N/A",
    "RETIRED",
)

for _h in [
    "admin_handler.py",
    "ato_handler.py",
    "deploy_handler.py",
    "hedge_handler.py",
    "monitor_handler.py",
]:
    _kb(
        f"bot/handlers/{_h}",
        "Bot Legacy",
        "Handler (Retired)",
        f"Retired Telegram command handler: {_h}",
        "Legacy handler from pre-bat_telegram architecture. Not loaded by main.py or any active code.",
        "N/A",
        "N/A",
        "N/A",
        "N/A",
        "RETIRED",
        "Replaced by corresponding logic in bat_telegram/bots/.",
    )

# ── SIMULATOR ─────────────────────────────────────────────────────────────────
_kb(
    "simulator/app.py",
    "Simulator",
    "Backend",
    "Flask REST API backend — standalone Telegram simulator, no batman imports",
    "Serves localhost:5001. Simulates Telegram bot webhook endpoints for all 5 active bots (DRISHTI/KAVACH/SANCHALAK/SARANSH/JAGRAN). Routes /api/send, /api/state, /api/keyboard, /api/market/* endpoints. Maintains sim state in memory. Enforces paused-bot read-only mode. Uses testing/mocks/sim_access_token.json for token delivery simulation.",
    "HTTP requests from simulator UI, sim_access_token.json placeholder",
    "Simulated Telegram bot responses, sim state JSON",
    "testing/mocks/sim_access_token.json, simulator/index.html, simulator/market.html",
    "simulator/index.html, simulator/market.html, simulator/analyzer.html",
    "ACTIVE",
    "Completely standalone — does NOT import ANY batman runtime modules. Pure simulation layer.",
)

_kb(
    "simulator/index.html",
    "Simulator",
    "UI — Chat Interface",
    "Main simulator UI — multi-bot chat interface for all 5 bots",
    "Browser chat UI with tabs for each bot (DRISHTI/KAVACH/SANCHALAK/SARANSH/JAGRAN). Shows conversation history per bot, inline keyboard buttons, unread message badges. sendFakeToken() button inserts placeholder JWT. Calls simulator/app.py REST API for all interactions.",
    "User interactions (button clicks, text input), simulator/app.py API",
    "Browser-based Telegram-like chat simulation",
    "simulator/app.py",
    "Developer manual testing workflow",
    "ACTIVE",
    "JWT token replaced with placeholder. Real token must be pasted manually for live testing.",
)

_kb(
    "simulator/market.html",
    "Simulator",
    "UI — Market Controls",
    "Market simulator UI — NIFTY spot controls and ATO trigger panel",
    "Browser panel for simulating NIFTY spot movements. Adjust LTP up/down, trigger ATO breach/exit scenarios, view ATO ledger summary in real-time. Calls simulator/app.py /api/market/* endpoints.",
    "User LTP inputs, simulator/app.py market API",
    "Simulated market feed events driving ATO logic in simulator",
    "simulator/app.py",
    "ATO cycle testing without real market data",
    "ACTIVE",
)

_kb(
    "simulator/analyzer.html",
    "Simulator",
    "UI — Analytics Viewer",
    "ATO telemetry and ledger analytics viewer for simulator data",
    "Browser panel displaying ATO execution telemetry and consolidated trade ledger data from the simulator's in-memory state. Provides visual review of ATO cycle history during simulation runs.",
    "simulator/app.py state API",
    "Visual analytics display in browser",
    "simulator/app.py",
    "Post-simulation ATO review",
    "ACTIVE",
)

_kb(
    "simulator/hedge_box_simulator.py",
    "Simulator",
    "Hedge Box Logic",
    "Hedge Box zone matrix generator — exports zone strike grid",
    "Generates full Hedge Box decision matrix: for given spot and break-even, computes which strike to buy per zone (Green/Orange/Blue/Yellow) per side (CE/PE). Applies Tuesday 0DTE rule (hedge_strike blank on Tuesday). Exports to CSV. Used standalone and referenced by simulator/app.py.",
    "NIFTY spot, break-even levels, Hedge Box config (zone widths, box width)",
    "Hedge box zone matrix as dict/CSV — readable by simulator/app.py",
    "N/A",
    "simulator/app.py, modules/ratripal.py (design reference)",
    "ACTIVE",
)

_kb(
    "simulator/requirements_sim.txt",
    "Simulator",
    "Dependencies",
    "Simulator-specific Python package requirements",
    "Flask and any simulator-only packages not in root requirements.txt. Install separately for simulator-only environments.",
    "N/A",
    "pip install -r simulator/requirements_sim.txt",
    "N/A",
    "simulator/app.py",
    "CONFIG",
)

# ── TESTS ─────────────────────────────────────────────────────────────────────
_kb(
    "tests/__init__.py",
    "Tests",
    "Package Init",
    "Package marker for tests/",
    "Empty __init__.py.",
    "N/A",
    "N/A",
    "N/A",
    "N/A",
    "ACTIVE",
)

_kb(
    "tests/conftest.py",
    "Tests",
    "Fixtures",
    "Shared pytest fixtures and test configuration",
    "Provides: mock_broker (BatmanBroker in mock_mode), mock_state (clean StateManager), mock_config (test config dict), mock_event_bus (EventBus), sample_deployment_json (complete deployment fixture), tmp_path usage. All fixtures are function-scoped for isolation.",
    "pytest framework, core/*.py",
    "Fixtures available to all test_*.py files",
    "core/*.py",
    "tests/test_*.py",
    "ACTIVE",
)

_kb(
    "tests/test_core.py",
    "Tests",
    "Core Layer Tests",
    "Unit tests for all core/ shared service modules",
    "Tests: Config dot-path access and ${ENV_VAR} expansion; StateManager thread safety (concurrent read/write); EventBus pub/sub async dispatch; TokenStore save/load/is_expired; BatmanBroker mock_mode order guard; connect_with_token and hot_reload_token paths.",
    "tests/conftest.py fixtures",
    "pytest PASS/FAIL report",
    "core/*.py",
    "CI quality gate",
    "ACTIVE",
)

_kb(
    "tests/test_modules.py",
    "Tests",
    "Module Tests",
    "Unit tests for all 7 trading modules",
    "Tests: ATO breach detection (CE/PE sides); ATO retrace exit; duplicate-tail dedup guard; side gating (CE_ONLY/PE_ONLY/BOTH); batman_entry deployment file write; profit_trailing stop logic; position_monitor POSITION_UPDATE publish; emergency_exit market order placement; overnight_hedge skip on Tuesday.",
    "tests/conftest.py fixtures",
    "pytest PASS/FAIL report",
    "modules/*.py",
    "CI quality gate",
    "ACTIVE",
)

_kb(
    "tests/test_resilience.py",
    "Tests",
    "Resilience Tests",
    "Unit tests for core/resilience.py retry decorator and circuit breaker",
    "Tests: @retry with exponential backoff (correct delay progression); circuit breaker open → half-open → closed transitions; failure threshold enforcement; recovery timeout behaviour.",
    "tests/conftest.py fixtures",
    "pytest PASS/FAIL report",
    "core/resilience.py",
    "CI quality gate",
    "ACTIVE",
)

_kb(
    "tests/test_incident_publisher.py",
    "Tests",
    "Incident Publisher Tests",
    "Unit tests for bat_telegram/incident_publisher.py",
    "Tests: JAGRAN allowlist exact and wildcard matching; deduplication within time window; recovery transition (active → resolved); daily incident CSV creation; XLSX workbook export with Incidents/Recoveries/Combined sheets; repeat-event suppression vs capture.",
    "tests/conftest.py fixtures",
    "pytest PASS/FAIL report",
    "bat_telegram/incident_publisher.py",
    "CI quality gate",
    "ACTIVE",
)

_kb(
    "tests/test_runtime_logging.py",
    "Tests",
    "Logging Tests",
    "Unit tests for core/runtime_logging.py time-window logging",
    "Tests: time-window file rollover on window boundary; on-demand file creation (not pre-created); dual main/module sink write; export retry cap under simulated write-lock; IST timestamp format correctness.",
    "tests/conftest.py fixtures",
    "pytest PASS/FAIL report",
    "core/runtime_logging.py",
    "CI quality gate",
    "ACTIVE",
)

_kb(
    "tests/test_ratripal.py",
    "Tests",
    "RATRIPAL Tests",
    "Unit tests for modules/ratripal.py Hedge Box zone engine",
    "Tests: zone determination for all 5 zones (White/Green/Orange/Blue/Yellow); CE and PE side calculations; confirm/deny/timeout HITL flows; broker buy execution on confirm; PRABHAT MUKTI CSV write; JAGRAN incident on broker failure; Tuesday 0DTE SKIP return.",
    "tests/conftest.py fixtures",
    "pytest PASS/FAIL report",
    "modules/ratripal.py",
    "CI quality gate",
    "ACTIVE",
)

# ── CONFIG ────────────────────────────────────────────────────────────────────
_kb(
    "config/settings.json",
    "Config",
    "Runtime Config",
    "Master runtime configuration — ALL tunable parameters for the entire system",
    "Defines: broker section (client_code=${DHAN_CLIENT_CODE}), ATO parameters (retrace_points default, entry_buffer default, poll_interval_secs), schedule timing (start_day, stop_day, start_hour, stop_hour), logging (window_minutes, sink configs), incident retry settings, trailing stop parameters. ALL values use ${ENV_VAR} for secrets — never hard-coded.",
    "Environment variables (${DHAN_CLIENT_CODE}, ${DHAN_ACCESS_TOKEN}, etc.)",
    "Config singleton loaded by core/config.py at startup",
    "N/A",
    "core/config.py → all modules and bots",
    "CONFIG",
    "Credential fields use ${ENV_VAR}. Real values via environment or config/.env (gitignored).",
)

_kb(
    "config/.env.example",
    "Config",
    "Environment Template",
    "Environment variable template — copy to config/.env and fill in real values",
    "Documents all required env vars with <ENTER_...> placeholders: DHAN_CLIENT_CODE, DHAN_ACCESS_TOKEN_DEFAULT, telegram bot tokens and chat IDs. No real credentials here — copy to config/.env and fill in.",
    "N/A",
    "Developer-created config/.env (gitignored)",
    "N/A",
    "config/settings.json via core/config.py",
    "CONFIG",
    "config/.env is gitignored. NEVER commit real credentials. Always <ENTER_...> format in this file.",
)

_kb(
    ".gitignore",
    "Config",
    "Git Config",
    ".gitignore — files/folders excluded from version control",
    "Excludes: .venv/, __pycache__/, *.pyc, config/.env, **/token.env, data/, logs/, *.log, .DS_Store, .vscode/. The **/token.env catch-all is critical for bot credential safety.",
    "N/A",
    "git add/commit safety",
    "N/A",
    "config/.env, **/token.env, data/, logs/",
    "CONFIG",
    "**/token.env is the critical security catch-all — ensures no live bot token is ever committed.",
)

_kb(
    ".editorconfig",
    "Config",
    "Editor Config",
    "Cross-editor formatting standards",
    "Defines: indent_style=space, indent_size=4, charset=utf-8, trim_trailing_whitespace=true, insert_final_newline=true. Applies to all editors supporting .editorconfig.",
    "N/A",
    "Consistent formatting across editors",
    "N/A",
    "All source files",
    "CONFIG",
)

_kb(
    ".vscode/settings.json",
    "Config",
    "VS Code Config",
    "VS Code workspace settings — interpreter, formatter, linter, autosave",
    "Sets: Python interpreter (.venv/Scripts/python.exe), pytest discovery (tests/), Black formatter on save, Ruff lint on save with auto-fix, autosave on focus change, import organisation on save.",
    "N/A",
    "VS Code editor behaviour for this workspace",
    "N/A",
    "All Python files",
    "CONFIG",
)

_kb(
    ".vscode/tasks.json",
    "Config",
    "VS Code Tasks",
    "VS Code task definitions for quality gate commands",
    "Defines runnable tasks: Tests:pytest, Lint:ruff check, Format:black check, Types:mypy (runtime), OCR:Clipboard→Chat(Clean), OCR:Clipboard→Chat(High Recall). Run via Ctrl+Shift+P → Run Task.",
    "N/A",
    "VS Code task palette — one-click quality gates",
    "N/A",
    "tests/, core/, modules/, tools/",
    "CONFIG",
)

_kb(
    ".vscode/extensions.json",
    "Config",
    "VS Code Extensions",
    "VS Code recommended extension list for this workspace",
    "Recommends: ms-python.python, ms-python.pylance, charliermarsh.ruff, ms-python.black-formatter, Python Test Adapter, SonarLint, Even Better TOML, Code Spell Checker.",
    "N/A",
    "Extension installation prompt for new developers",
    "N/A",
    "All Python files",
    "CONFIG",
)

_kb(
    ".github/copilot-instructions.md",
    "Config",
    "AI Instructions",
    "GitHub Copilot session instructions — loaded automatically into every chat session",
    "Defines: project identity (Batman = NIFTY Iron Condor automation), pending work priority order, module-to-file map (blast radius guide), key invariants (NEVER violate), architecture summary, task-to-file routing. AI tools read this at session start for context loading.",
    "N/A",
    "AI tool session context, Copilot behaviour shaping",
    "N/A",
    "All files (meta-reference)",
    "CONFIG",
    "Keep in sync with CONTEXT.md. Both serve the same purpose for different AI surfaces.",
)

# ── TELEGRAM DESIGN & CONFIG ASSETS ───────────────────────────────────────────
for _bot, _desc in [
    ("drishti", "DRISHTI token/health bot"),
    ("kavach", "KAVACH trading bot"),
    ("lakshmi", "LAKSHMI P&L bot"),
    ("jagran", "JAGRAN incident channel"),
    ("sanchalak", "SANCHALAK global control"),
    ("saransh", "SARANSH summary bot"),
    ("_template", "Generic bot scaffold template"),
]:
    _kb(
        f"telegram/bots/{_bot}/token.env.example",
        "Config",
        "Bot Token Template",
        f"Token template for {_desc} — placeholder only, safe to commit",
        f"Shows required env vars for {_bot.upper()}: BOT_TOKEN and CHAT_ID with <ENTER_...> placeholder. Developer copies to token.env and fills in real values from Telegram BotFather.",
        "N/A",
        f"telegram/bots/{_bot}/token.env (gitignored, filled by developer)",
        "N/A",
        "bat_telegram/loader.py",
        "TEMPLATE",
        "token.env files are gitignored. Placeholder only in .example.",
    )
    _kb(
        f"telegram/bots/{_bot}/params.json",
        "Config",
        "Bot Parameters",
        f"Tunable parameters for {_desc.split(' ')[0]} bot — safe to commit",
        f"All non-secret config for {_bot.upper()}: quiet hours, retry settings, reminder intervals, thresholds, feature flags. No credentials here.",
        "N/A",
        "Merged with token.env by bat_telegram/loader.py",
        "N/A",
        "bat_telegram/loader.py",
        "CONFIG",
        "Safe to commit. Isolated from token.env to keep secrets separate.",
    )
    _kb(
        f"telegram/bots/{_bot}/config.json",
        "Config",
        "Bot Config",
        f"Bot-level config metadata for {_desc.split(' ')[0]}",
        "Contains bot display name, version, and feature flag registry for the bot. Read by loader.py for bot identification.",
        "N/A",
        "Bot metadata dict",
        "N/A",
        "bat_telegram/loader.py",
        "CONFIG",
    )

_kb(
    "telegram/bots/_template/README.md",
    "Design",
    "Bot Scaffold",
    "Bot scaffold template README — instructions for creating new bots",
    "Step-by-step guide for creating a new bot using the _template scaffold: copy folder, rename, fill in token.env, add commands to bot.py, register in main.py and loader.py.",
    "N/A",
    "Developer guide for new bot creation",
    "N/A",
    "bat_telegram/bots/ new bot development",
    "DESIGN",
)

_kb(
    "telegram/design/architecture.md",
    "Design",
    "Architecture",
    "Telegram subsystem architecture — bot responsibility matrix and two-file rule",
    "Documents: 5-bot architecture overview, two-file rule (token.env=secrets, params.json=config), bot responsibility matrix (DRISHTI/KAVACH/LAKSHMI/SANCHALAK/SARANSH/JAGRAN responsibilities), message routing policy, incident escalation flow, control plane interlocks.",
    "N/A",
    "Architecture reference for developers and AI tools",
    "N/A",
    "bat_telegram/ implementation",
    "DESIGN",
)

_kb(
    "telegram/design/kavach_design.md",
    "Design",
    "KAVACH Design",
    "KAVACH bot full design spec — wizard steps, command contracts, ATO control logic",
    "Specifies: all KAVACH commands, 6-step wizard step sequence, ATO trigger/retrace formula details, break-even confirm/edit/skip flow, deployment JSON schema, /exit confirm flow, RATRIPAL callback format.",
    "N/A",
    "Implementation reference for kavach-2.0/bat_telegram/bots/kavach2/bot.py",
    "N/A",
    "kavach-2.0/bat_telegram/bots/kavach2/bot.py",
    "DESIGN",
)

_kb(
    "telegram/design/drishti_design.md",
    "Design",
    "DRISHTI Design",
    "DRISHTI bot full design spec — token lifecycle, fleet status, health flow",
    "Specifies: DRISHTI command set, token validation sequence (NIFTY+GIFT dual-check rationale), /fleet_status table format, stale-token reminder schedule, 9AM and EOD prompt structure and bot interaction pattern.",
    "N/A",
    "Implementation reference for bat_telegram/bots/drishti/bot.py",
    "N/A",
    "bat_telegram/bots/drishti/bot.py",
    "DESIGN",
)

_kb(
    "telegram/design/drishti_flow.html",
    "Design",
    "DRISHTI Flow",
    "DRISHTI token delivery flow — interactive HTML flow diagram",
    "Browser-viewable step-by-step flow showing the daily DRISHTI token delivery sequence: user pastes JWT → validation → hot_reload → LTP checks → confirmation or rejection message.",
    "N/A",
    "Visual reference for DRISHTI token flow",
    "N/A",
    "bat_telegram/bots/drishti/bot.py",
    "DESIGN",
)

_kb(
    "telegram/design/lakshmi_design.md",
    "Design",
    "LAKSHMI Design",
    "LAKSHMI bot design spec — P&L reporting and MTM alert thresholds",
    "Specifies LAKSHMI commands, MTM polling integration with position_monitor, alert threshold configuration, EOD summary format, and paused-state gating.",
    "N/A",
    "Implementation reference for bat_telegram/bots/lakshmi/bot.py",
    "N/A",
    "bat_telegram/bots/lakshmi/bot.py",
    "DESIGN",
)

_kb(
    "telegram/design/hedge_box_design.md",
    "Design",
    "Hedge Box Design",
    "Hedge Box module full design — zone logic, RATRIPAL runtime, PRABHAT MUKTI handoff",
    "Defines: Hedge Box color zone map (White=break-even, Green=1 inside, Orange=2, Blue=3, Yellow=4 inside break-even), 75-point box width, DTE-layer activation schedule, 15:15 checkpoint timing, RATRIPAL broker-buy path, KAVACH HITL confirm prompt format, PRABHAT MUKTI morning sell flow design.",
    "N/A",
    "Implementation reference for modules/ratripal.py and modules/overnight_hedge.py",
    "N/A",
    "modules/ratripal.py, modules/overnight_hedge.py",
    "DESIGN",
)

_kb(
    "telegram/design/prabhat_mukti_design.md",
    "Design",
    "Prabhat Mukti Design",
    "PRABHAT MUKTI (morning hedge exit) design — parked, pending 9 open questions",
    "Design for morning hedge sell flow: 09:00–09:25 IST window, gap-breach ATO-first exception, per-side confirm, 6-button sell timing choice. STATUS: design partially locked but NOT coded — 9 open questions (PM-Q1 to PM-Q9) outstanding.",
    "N/A",
    "Future implementation reference — PRABHAT MUKTI module",
    "N/A",
    "modules/ratripal.py (RATRIPAL augmentation)",
    "DESIGN",
    "PARKED — not in active coding scope.",
)

_kb(
    "telegram/design/logging_design.md",
    "Design",
    "Logging Design",
    "Runtime logging architecture — IST milliseconds, time-window files, dual sinks, XLSX export",
    "Specifies: log line format (HH:MM:SS.mmm prefix only — no date), time-window file naming convention, dual main+module sink routing, post-market segmentation windows, repeated-event capture policy, XLSX workbook export with retry on lock.",
    "N/A",
    "Implementation reference for core/runtime_logging.py",
    "N/A",
    "core/runtime_logging.py",
    "DESIGN",
)

_kb(
    "telegram/design/batman_simulation.html",
    "Design",
    "Simulation Script",
    "End-to-end Batman simulation walkthrough — interactive HTML presentation",
    "Browser slide-show stepping through a complete Batman trading day: DRISHTI token delivery → KAVACH /register wizard → 9AM algo start → ATO cycle simulation → EOD SARANSH summary. Used for stakeholder demos and new developer onboarding. JWT sample replaced with placeholder.",
    "N/A",
    "Browser-viewable simulation demo",
    "N/A",
    "Developer/stakeholder onboarding",
    "DESIGN",
    "JWT token replaced with placeholder for security.",
)

# ── REFERENCE ─────────────────────────────────────────────────────────────────
_kb(
    "reference/REFERENCE_SYSTEM.md",
    "Reference",
    "Meta-Governance",
    "Describes the reference/ governance framework and update contract",
    "Explains purpose, usage, and update SLA for each reference/ artifact. Defines when to update each document and who owns each.",
    "N/A",
    "Developer workflow guide",
    "N/A",
    "All reference/ files",
    "DOCS",
)

_kb(
    "reference/FUNCTION_OWNERSHIP_INDEX.md",
    "Reference",
    "Change Routing",
    "Function-level ownership index — maps key functions to owning files",
    "Quick-reference table: function name → owning file → responsibility area. READ FIRST before any change request to route to the right file without full codebase scan. Reduces AI tool scanning overhead by 80%.",
    "Codebase analysis",
    "Fast change routing for AI tools and developers",
    "N/A",
    "All source files",
    "DOCS",
    "READ THIS FIRST before any change request. Updated every session.",
)

_kb(
    "reference/TECHNICAL_CHANGE_INDEX.md",
    "Reference",
    "Change Routing",
    "Technical change routing matrix — maps change type to files to edit",
    "Core ownership map and change routing: 'if you change X, always check Y, usually update Z'. Mandatory sidecar update list for every session. Prevents missed cross-file impact.",
    "N/A",
    "Change impact guide",
    "N/A",
    "All source files",
    "DOCS",
)

_kb(
    "reference/DECISION_REGISTER.md",
    "Reference",
    "Governance",
    "Timestamped register of all design decisions (D-xx series)",
    "Numbered decisions: date, decision text, rationale, impact on which files. Prevents re-litigating resolved design questions across sessions.",
    "Design sessions",
    "Decision audit trail",
    "N/A",
    "DESIGN.md, CONTEXT.md",
    "DOCS",
)

_kb(
    "reference/DISCUSSION_CAPTURE.md",
    "Reference",
    "Governance",
    "Session Q&A and design discussion capture",
    "Structured capture of design discussions: question, answer, date, affected files. Complements DECISION_REGISTER for nuanced trade-off context that doesn't fit a single decision entry.",
    "Design sessions",
    "Q&A audit trail",
    "N/A",
    "reference/DECISION_REGISTER.md",
    "DOCS",
)

_kb(
    "reference/CODING_HANDOFF_CHECKLIST.md",
    "Reference",
    "Governance",
    "Pre-coding handoff checklist for session quality and completeness",
    "Checklist items: design doc reviewed, acceptance criteria clear, test plan defined, sidecar files identified, quality gates (Ruff/Black/mypy/pytest) passing. Run at session start before implementation.",
    "N/A",
    "Session start checklist",
    "N/A",
    "Implementation work",
    "DOCS",
)

_kb(
    "reference/PRODUCTION_RELIABILITY_BLUEPRINT.md",
    "Reference",
    "Governance",
    "Production reliability guide — polling guardrails, failure policy, go/no-go checklist",
    "Covers: unattended runtime expectations, ATO polling throttle (min interval), failure containment behaviour (no cascade), service restart policy, EOD telemetry dependency, large-case test plan for go-live confidence.",
    "N/A",
    "Go-live readiness reference",
    "N/A",
    "VPS deployment, main.py",
    "DOCS",
)

_kb(
    "reference/TECHNICAL_IMPLEMENTATION_PLAYBOOK.md",
    "Reference",
    "Governance",
    "Technical methodology playbook — architecture patterns and replication blueprint",
    "Architecture methodology, module dependency map, toolchain stack, co-dependency patterns, and replication blueprint for building similar Copilot-assisted automated trading systems.",
    "N/A",
    "Methodology reference for AI tools and developers",
    "N/A",
    "All source files",
    "DOCS",
)

_kb(
    "reference/FEATURE_REFERENCE.csv",
    "Reference",
    "Governance",
    "CSV feature registry for filtering and external tooling",
    "Machine-readable feature list with columns: feature ID, name, status, owning bot/module, file references. Import to Excel/Sheets for portfolio tracking.",
    "IMPLEMENTATION_TRACKER.md",
    "Spreadsheet/tooling import",
    "N/A",
    "N/A",
    "DOCS",
)

# ── TOOLS ─────────────────────────────────────────────────────────────────────
_kb(
    "tools/vps-smoke-windows.ps1",
    "Tools",
    "Validation",
    "Windows PowerShell VPS smoke test automation",
    "Performs: preflight env var checks, config placeholder validation, runtime folder write-access probes, Batman startup health check (process launch + first-log evidence), log artifact inspection, controlled stop/restart. Emits report.json and report.txt to data/analytics/vps_validation/<timestamp>/.",
    "Environment variables (DHAN_ACCESS_TOKEN etc.), running or starting Batman process",
    "data/analytics/vps_validation/<timestamp>/report.json and report.txt",
    "main.py",
    "VPS go-live validation gate",
    "ACTIVE",
    "Run as VS Code task 'Ops: Windows VPS smoke' or directly from PowerShell on VPS.",
)

_kb(
    "tools/ocr-from-clipboard.ps1",
    "Tools",
    "OCR",
    "Clipboard screenshot → structured OCR text extraction",
    "Reads image from Windows clipboard, calls tools/read_image_ocr.py at multiple scales (best mode) or merged (merge mode), filters low-confidence segments, outputs structured JSON and plain text to logs/clipboard_ocr/<timestamp>.*. Powers VS Code OCR tasks.",
    "Clipboard image (screenshot pasted before running), mode parameter (best/merge)",
    "logs/clipboard_ocr/<timestamp>.json and <timestamp>.txt",
    "tools/read_image_ocr.py",
    "VS Code OCR tasks, hedge box zone extraction",
    "ACTIVE",
    "Used during hedge box image analysis sessions to extract zone level data.",
)

_kb(
    "tools/read_image_ocr.py",
    "Tools",
    "OCR",
    "Python OCR engine wrapper using pytesseract — file-path input, scored JSON output",
    "Accepts image file path as CLI argument. Runs pytesseract OCR at multiple scales and orientations. Scores each text segment by confidence. Returns structured JSON list with text, bounding box, and confidence score per segment.",
    "Image file path (CLI argument)",
    "JSON array of OCR segments with text/bbox/confidence",
    "pytesseract, PIL (Pillow)",
    "tools/ocr-from-clipboard.ps1, tools/read-image.ps1",
    "ACTIVE",
)

_kb(
    "tools/read-image.ps1",
    "Tools",
    "OCR",
    "PowerShell wrapper for file-based OCR via read_image_ocr.py",
    "Accepts image file path from CLI, calls tools/read_image_ocr.py, writes output JSON and TXT to logs/. Convenience wrapper for one-off image files (not clipboard-based).",
    "Image file path (CLI parameter)",
    "logs/<image-name>_ocr.json, logs/<image-name>_ocr.txt",
    "tools/read_image_ocr.py",
    "One-off image OCR analysis",
    "ACTIVE",
)

_kb(
    "tools/generate_file_inventory.py",
    "Tools",
    "Documentation",
    "THIS FILE — generates PROJECT_FILE_INVENTORY.xlsx from the built-in knowledge base",
    "Scans workspace, walks .venv for package summary, and writes a multi-sheet Excel workbook documenting every file in the project with category, purpose, inputs, outputs, dependencies, and status. Provides complete onboarding context for new developers or AI tools.",
    "Built-in knowledge base (KB dict) + .venv/Lib/site-packages directory scan",
    "PROJECT_FILE_INVENTORY.xlsx in workspace root",
    "openpyxl",
    "Developer/AI tool onboarding documentation",
    "ACTIVE",
    "Run: .venv\\Scripts\\python.exe tools\\generate_file_inventory.py",
)

# ── TESTING/ ──────────────────────────────────────────────────────────────────
_kb(
    "testing/CONTEXT.md",
    "Testing",
    "Test Strategy",
    "Testing strategy document for Batman v3",
    "Describes testing philosophy, simulator-first testing approach, mock wiring patterns (mock broker, mock state), coverage targets per module, and rationale for choosing unit tests over integration tests for broker calls.",
    "N/A",
    "Testing strategy reference",
    "N/A",
    "tests/*.py, simulator/",
    "DOCS",
)

_kb(
    "testing/SCENARIOS.md",
    "Testing",
    "Test Scenarios",
    "Detailed test scenario catalogue with pre/post conditions",
    "Numbered scenarios (S-xx) for: ATO trigger (CE/PE sides), ATO retrace exit, token delivery, hedge confirm, SANCHALAK stop_all, SARANSH summary run. Each scenario has: preconditions, step-by-step actions, expected outcome, affected files.",
    "N/A",
    "Test case implementation reference",
    "N/A",
    "tests/*.py",
    "DOCS",
)

_kb(
    "testing/TEST_INVENTORY.md",
    "Testing",
    "Test Coverage",
    "Test inventory mapping scenarios to pytest functions",
    "Table mapping each scenario ID to its pytest function name and test file. Used as coverage gap tracker — unlinked scenarios indicate missing tests.",
    "N/A",
    "Test coverage reference",
    "N/A",
    "tests/*.py",
    "DOCS",
)

_kb(
    "testing/mocks/sim_access_token.json",
    "Testing",
    "Mock Data",
    "Simulator mock access token — placeholder JWT for testing token delivery flow",
    "JSON file with a placeholder JWT value (not a real token) and saved_at timestamp. Used by simulator/app.py for /token command simulation. Real token can be pasted over this for live testing.",
    "Placeholder JWT (sanitized — not a real Dhan token)",
    "Simulator token state for /token command testing",
    "simulator/app.py",
    "Simulator token delivery workflow testing",
    "TEMPLATE",
    "Contains placeholder only. Never commit a real JWT here.",
)

_kb(
    "testing/mocks/broker_stub_positions.py",
    "Testing",
    "Mock Data",
    "Broker stub: hardcoded position responses for unit test mocking",
    "Python module returning static position dicts (ce_sell, pe_sell, ce_buy, pe_buy legs with mark-to-market values) for use in pytest fixtures when broker.get_positions() is mocked.",
    "Hardcoded position data",
    "Mock position dicts used in tests/conftest.py",
    "N/A",
    "tests/conftest.py, tests/test_modules.py",
    "MOCK",
)

_kb(
    "testing/mocks/deploy_log_sample.jsonl",
    "Testing",
    "Mock Data",
    "Sample deployment event log in JSONL format for replay testing",
    "Newline-delimited JSON records representing a sequence of deployment events: register, ATO trigger, ATO exit, etc. Used for event replay tests.",
    "Hardcoded JSONL event log",
    "Event sequence for replay-based testing",
    "N/A",
    "tests/test_modules.py",
    "MOCK",
)

_kb(
    "testing/mocks/deployment_apr7.json",
    "Testing",
    "Mock Data",
    "Sample deployment JSON from April 7 — used as test fixture",
    "Complete batman_*.json deployment file with realistic strike prices (NIFTY ~22,500 range), break-evens, retrace_points, and all leg details. Used as the canonical test deployment fixture.",
    "April 7 deployment data (representative)",
    "Fixture for tests expecting a complete deployment file",
    "N/A",
    "tests/conftest.py, tests/test_modules.py",
    "MOCK",
)

_kb(
    "testing/mocks/positions_apr7.json",
    "Testing",
    "Mock Data",
    "Sample live positions JSON from April 7 — used as test fixture",
    "Broker position response JSON matching the April 7 deployment: 4 legs with mark-to-market values, unrealised P&L per leg. Used to mock broker.get_positions() in unit tests.",
    "April 7 position data (representative)",
    "Mock position response for broker.get_positions() stub",
    "N/A",
    "tests/conftest.py, tests/test_modules.py",
    "MOCK",
)

# ── DATA/ ─────────────────────────────────────────────────────────────────────
_kb(
    "data/.gitkeep",
    "Data & Analytics",
    "Git Placeholder",
    "Keeps data/ folder in git without committing runtime data",
    "Empty file ensuring data/ directory exists in git checkout even though all actual data files are gitignored.",
    "N/A",
    "Empty directory in git",
    "N/A",
    "data/ folder",
    "GENERATED",
)

_kb(
    "data/deployments/.gitkeep",
    "Data & Analytics",
    "Git Placeholder",
    "Keeps data/deployments/ in git",
    "Empty placeholder.",
    "N/A",
    "Empty dir",
    "N/A",
    "data/deployments/",
    "GENERATED",
)

_kb(
    "data/deployments/archive/.gitkeep",
    "Data & Analytics",
    "Git Placeholder",
    "Keeps data/deployments/archive/ in git",
    "Empty placeholder.",
    "N/A",
    "Empty dir",
    "N/A",
    "data/deployments/archive/",
    "GENERATED",
)

_kb(
    "data/deployments/ (runtime files)",
    "Data & Analytics",
    "Deployment Files",
    "Active iron condor deployment JSON files (runtime, gitignored)",
    "Each batman_YYYY-MM-DD.json records: 4 legs (PE buy/sell, CE buy/sell), strike prices, expiry, break-even levels (pe_break_even, ce_break_even), retrace_points, entry_buffer_points, poll_interval_secs, ato_manage_sides, deployment_date, wizard_timestamp.",
    "KAVACH wizard → modules/batman_entry.py (writes on wizard completion)",
    "Runtime config consumed by all active trading modules",
    "modules/batman_entry.py",
    "modules/ato_protection.py, modules/overnight_hedge.py, modules/ratripal.py",
    "GENERATED",
    "Written by KAVACH wizard. Archived to data/deployments/archive/ on /batman_complete.",
)

_kb(
    "data/deployments/archive/ (runtime files)",
    "Data & Analytics",
    "Deployment Archive",
    "Archived deployment files from completed Batman sessions (runtime, gitignored)",
    "Completed batman_*.json files moved here by /batman_complete command. Historical record of all past deployments with full leg details.",
    "/batman_complete command in KAVACH bot",
    "Historical deployment archive",
    "kavach-2.0/bat_telegram/bots/kavach2/bot.py",
    "N/A",
    "GENERATED",
)

_kb(
    "data/analytics/ato_execution_telemetry.csv",
    "Data & Analytics",
    "ATO Telemetry",
    "ATO execution event log — every buy/exit event with full context",
    "Append-only CSV. Columns: timestamp_ist, deployment_file, side (CE/PE), action (BUY_ENTRY / SELL_EXIT), trigger_reason, nifty_ltp, sell_strike, trigger_level, protect_strike, protect_symbol, order_id, qty, poll_interval_secs. One row per ATO event. Duplicate-tail guard prevents double-writes on restart.",
    "modules/ato_protection.py (appends on each ATO event)",
    "ATO event history for SARANSH EOD digest and post-session analysis",
    "modules/ato_protection.py",
    "bat_telegram/bots/saransh/bot.py (EOD section 2)",
    "GENERATED",
    "SARANSH soft-fails ATO section if this file is missing. Grows across sessions.",
)

_kb(
    "data/analytics/ato/ato_trade_ledger.csv",
    "Data & Analytics",
    "ATO Ledger",
    "Consolidated ATO trade ledger — buy/sell cycle pairs with P&L impact",
    "Append-only CSV. One row per completed ATO cycle: entry timestamp, exit timestamp, entry LTP, exit LTP, side, points_lost, lot_size, total_impact_inr. Duplicate-tail guard applied. Source for XLSX snapshots.",
    "modules/ato_protection.py (appends on cycle completion)",
    "Cycle-level P&L data for EOD analysis and XLSX snapshots",
    "modules/ato_protection.py",
    "bat_telegram/bots/saransh/bot.py, data/analytics/ato/snapshots/",
    "GENERATED",
    "Source CSV stays writable even when a snapshot XLSX is open in Excel.",
)

_kb(
    "data/analytics/ato/snapshots/ (runtime files)",
    "Data & Analytics",
    "ATO Snapshots",
    "Lock-safe ATO ledger XLSX snapshots — timestamped copies for Excel viewing",
    "Timestamped XLSX workbooks (ato_trade_ledger_snapshot_YYYYMMDD_HHMMSS.xlsx) copied from ato_trade_ledger.csv at configurable intervals. User can open in Excel without locking the live source CSV. Written by modules/ato_protection.py via openpyxl.",
    "data/analytics/ato/ato_trade_ledger.csv (copy at snapshot time)",
    "XLSX workbooks readable in Excel while live trading continues",
    "modules/ato_protection.py",
    "EOD analysis, SARANSH digest reference",
    "GENERATED",
    "Snapshot count in VPS report indicates ATO cycles have been executed.",
)

_kb(
    "data/analytics/incidents/ (runtime files)",
    "Data & Analytics",
    "Incident Ledger",
    "Daily JAGRAN incident ledger files — CSV and XLSX (runtime, gitignored)",
    "Per-day YYYY-MM-DD_incidents.csv appending all incidents with: scenario_id, source_bot, routed_to_jagran, message_preview, timestamp, dedup_key, status (ACTIVE/RESOLVED). Per-day XLSX workbook (Incidents/Recoveries/Combined sheets) exported on retry schedule.",
    "bat_telegram/incident_publisher.py",
    "Incident audit trail, post-session analysis",
    "bat_telegram/incident_publisher.py",
    "SARANSH EOD summary (optional)",
    "GENERATED",
)

_kb(
    "data/analytics/runtime_smoke/ (runtime files)",
    "Data & Analytics",
    "Runtime Logs",
    "Time-windowed runtime log files from all modules and bots (runtime, gitignored)",
    "Structure: data/analytics/runtime_smoke/YYYY-MM/YYYY-MM-DD/logs/<bot>_YYYYMMDD_<window>.log. Each file contains timestamped lines for the window. Dual-sink: main runtime log + bot/module-specific log.",
    "core/runtime_logging.py (writes on every log call)",
    "Searchable time-segmented log files",
    "core/runtime_logging.py",
    "Post-session debugging, VPS smoke test evidence",
    "GENERATED",
)

_kb(
    "data/analytics/vps_validation/ (runtime files)",
    "Data & Analytics",
    "VPS Reports",
    "VPS smoke test reports — timestamped PASS/WARN/FAIL evidence artifacts",
    "Per-run folder: report.json (machine-readable gate results), report.txt (human-readable summary), main_first_stdout.log / main_first_stderr.log (first-start output capture). Created by tools/vps-smoke-windows.ps1.",
    "tools/vps-smoke-windows.ps1",
    "Go-live evidence artifacts",
    "tools/vps-smoke-windows.ps1",
    "VPS deployment go/no-go decision",
    "GENERATED",
)

_kb(
    "data/analytics/summaries/ (runtime files)",
    "Data & Analytics",
    "EOD Summaries",
    "SARANSH EOD summary text files (runtime, gitignored)",
    "Per-day YYYY-MM-DD_summary.txt files written by SARANSH on every summary run (manual /summary or auto 16:00 EOD). Contains all 5 summary sections formatted as plain text.",
    "bat_telegram/bots/saransh/bot.py",
    "EOD summary file archive",
    "bat_telegram/bots/saransh/bot.py",
    "Post-session review",
    "GENERATED",
)

_kb(
    "data/analytics/hedge_box/core_22apr_matrix.csv",
    "Data & Analytics",
    "Hedge Box Analysis",
    "Hedge Box zone matrix for April 22 NIFTY core position — analysis artifact",
    "CSV export of the Hedge Box zone matrix for the April 22 trading session. Contains per-zone strike recommendations based on NIFTY spot and break-even levels from that date.",
    "simulator/hedge_box_simulator.py (export function)",
    "Reference data for hedge box zone calibration verification",
    "simulator/hedge_box_simulator.py",
    "telegram/design/hedge_box_design.md reference",
    "GENERATED",
)

# ── ASSETS ────────────────────────────────────────────────────────────────────
_kb(
    "Prod Data/Hedge Box/22 Apr 26 - 28 Apr 26/Core Position.png",
    "Assets",
    "Production Data",
    "Core position screenshot from April 22–28, 2026 trading session",
    "Screenshot of live NIFTY core position (4 legs of iron condor) from April 22 trading session. Used as reference data for validating hedge box logic and break-even calculations.",
    "Live trading platform screenshot",
    "Reference for hedge box calibration and P&L validation",
    "N/A",
    "telegram/design/hedge_box_design.md, logs/core_position_22apr26_ocr.*",
    "ASSET",
)

_kb(
    "Prod Data/Hedge Box/22 Apr 26 - 28 Apr 26/Hedge Box 24450 Centre.png",
    "Assets",
    "Production Data",
    "Hedge Box screenshot centred at 24450 — April 22 session reference",
    "Live Hedge Box grid screenshot with NIFTY around 24450. Shows all zone boundaries, current spot, hedge strike recommendations. Authoritative visual for zone logic verification.",
    "Live trading platform screenshot",
    "Reference for hedge box zone boundary verification",
    "N/A",
    "modules/ratripal.py, telegram/design/hedge_box_design.md",
    "ASSET",
)

_kb(
    "Prod Data/Hedge Box/29 Apr 26 - 1 Day Holiday/29 Apr 26 to 05 May 26 Hedge Box 1 day Holiday.png",
    "Assets",
    "Production Data",
    "Hedge Box screenshot for May week — includes 1-day holiday adjustment",
    "Live Hedge Box grid for the week of April 29 – May 5. Documents the holiday adjustment for NIFTY weekly options expiry when a trading day falls on a holiday.",
    "Live trading platform screenshot",
    "Reference for holiday DTE adjustment logic",
    "N/A",
    "modules/overnight_hedge.py, telegram/design/hedge_box_design.md",
    "ASSET",
)

_kb(
    "screenshots/hedge box/hedge_box_image.jpg",
    "Assets",
    "Reference Image",
    "AUTHORITATIVE Hedge Box baseline image — canonical zone rule source",
    "JPEG screenshot of the Hedge Box overlay showing all color zones (White=BE, Green=1 inside, Orange=2, Blue=3, Yellow=4), entry/exit times (15:25 entry, 09:20 exit), zone action rules, amendment rules, and NIFTY scale from ~24550–25550. This is the PRIMARY reference artifact for all hedge box logic derivation.",
    "Captured from trading platform",
    "Canonical hedge box baseline — feeds all zone logic design and OCR extraction",
    "N/A",
    "telegram/design/hedge_box_design.md, modules/ratripal.py, tools/read_image_ocr.py",
    "ASSET",
    "Authoritative per user memory. All hedge box zone logic derived from this image.",
)

_kb(
    "image/flowchart/1777030458357.png",
    "Assets",
    "Visual",
    "Architecture flowchart image",
    "PNG export of Batman v3 architecture flowchart. Used in batman_flowchart.html and design documentation.",
    "N/A",
    "Visual reference in documentation and presentations",
    "N/A",
    "batman_flowchart.html",
    "ASSET",
)

_kb(
    "logs/.gitkeep",
    "Assets",
    "Git Placeholder",
    "Keeps logs/ folder in git",
    "Empty placeholder.",
    "N/A",
    "Empty dir",
    "N/A",
    "logs/",
    "GENERATED",
)

_kb(
    "logs/clipboard_ocr/ (runtime files)",
    "Assets",
    "OCR Outputs",
    "Clipboard OCR extraction history — PNG captures and JSON/TXT outputs",
    "Contains: clipboard_<timestamp>.png (screenshot captures), ocr_<timestamp>.json (structured OCR with confidence), ocr_<timestamp>.txt (plain text extraction), latest.json/.txt/.source.txt (most recent run outputs). Generated by tools/ocr-from-clipboard.ps1.",
    "tools/ocr-from-clipboard.ps1",
    "OCR text extraction files for hedge box zone analysis",
    "tools/ocr-from-clipboard.ps1",
    "Hedge box design, testing reference",
    "GENERATED",
)

for _log_name in [
    "core_position_22apr26_ocr.json",
    "core_position_22apr26_ocr.txt",
    "hedge_box_24450_centre_ocr.json",
    "hedge_box_24450_centre_ocr.txt",
    "hedge_box_ocr_best_latest.json",
    "hedge_box_ocr_best_latest.txt",
    "hedge_box_ocr_merge.json",
    "hedge_box_ocr_merge.txt",
    "hedge_box_ocr.json",
    "hedge_box_ocr.txt",
    "testdata_10_mar_26_ocr.json",
    "testdata_10_mar_26_ocr.txt",
]:
    _is_json = _log_name.endswith(".json")
    _kb(
        f"logs/{_log_name}",
        "Assets",
        "OCR Output",
        f"OCR extraction output — {'structured JSON' if _is_json else 'plain text'} from hedge box image analysis",
        f"{'Structured JSON with text segments, bounding boxes, and confidence scores' if _is_json else 'Plain text extraction'} from a hedge box or position screenshot. Generated by tools/read_image_ocr.py via tools/read-image.ps1.",
        "Corresponding screenshot file",
        f"{'JSON OCR data' if _is_json else 'Plain text OCR data'} for hedge box design reference",
        "tools/read_image_ocr.py",
        "telegram/design/hedge_box_design.md, modules/ratripal.py reference",
        "GENERATED",
    )

# ─────────────────────────────────────────────────────────────────────────────
# EXCEL BUILDER
# ─────────────────────────────────────────────────────────────────────────────

MAIN_COLUMNS = [
    ("File Path", 38),
    ("Category", 15),
    ("Sub-Category", 20),
    ("File / Folder Name", 24),
    ("Purpose", 42),
    ("What It Does", 58),
    ("Inputs", 36),
    ("Outputs", 36),
    ("Depends On", 36),
    ("Supports", 36),
    ("Status", 12),
    ("Notes", 42),
]

SHEET_DEFS = [
    # (sheet_title, category_filter)  — filter can be str, list, or None (= Overview)
    ("Overview", None),
    ("Core Runtime", "Core Runtime"),
    ("Modules", "Modules"),
    ("Telegram Bots", "Telegram Bots"),
    ("Simulator", "Simulator"),
    ("Tests", "Tests"),
    ("Config", "Config"),
    ("Design & Docs", ["Design", "Docs"]),
    ("Reference", "Reference"),
    ("Tools", "Tools"),
    ("Bot Legacy", "Bot Legacy"),
    ("Data & Analytics", "Data & Analytics"),
    ("Testing Mocks", "Testing"),
    ("Assets", "Assets"),
]


def get_kb_rows(cat_filter) -> list:
    rows = []
    for path, info in KB.items():
        cat = info["category"]
        match = (cat in cat_filter) if isinstance(cat_filter, list) else (cat == cat_filter)
        if match:
            rows.append(
                [
                    path,
                    info["category"],
                    info["sub"],
                    Path(path).name,
                    info["purpose"],
                    info["what_it_does"],
                    info["inputs"],
                    info["outputs"],
                    info["depends_on"],
                    info["supports"],
                    info["status"],
                    info["notes"],
                ]
            )
    rows.sort(key=lambda r: r[0].lower())
    return rows


def write_data_sheet(wb, title: str, cat_filter) -> None:
    rows = get_kb_rows(cat_filter)
    if not rows:
        return
    ws = wb.create_sheet(title=title)
    write_header_row(ws, MAIN_COLUMNS)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(MAIN_COLUMNS))}1"
    for i, row in enumerate(rows, start=2):
        status = row[10] if len(row) > 10 else "ACTIVE"
        write_data_row(ws, i, row, status)


def write_overview_sheet(wb) -> None:
    ws = wb.create_sheet(title="Overview", index=0)

    # ── Title ──────────────────────────────────────────────────────
    ws.merge_cells("A1:L1")
    c = ws["A1"]
    c.value = (
        f"Batman v3 — Complete Project File Inventory   |   "
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} IST"
    )
    c.fill = fill(HDR_NAVY)
    c.font = Font(name="Calibri", color="FFFFFF", bold=True, size=14)
    c.alignment = c_align()
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:L2")
    c = ws["A2"]
    c.value = (
        "Single-process asyncio runtime  |  Python 3.12.10  |  "
        "Dhan-Tradehull v3.2.0  |  python-telegram-bot v20+  |  "
        "NIFTY Weekly Iron Condor strategy  |  Telegram-controlled from mobile"
    )
    c.fill = fill(HDR_BLUE)
    c.font = Font(name="Calibri", color="FFFFFF", size=10)
    c.alignment = c_align()
    ws.row_dimensions[2].height = 20

    # ── Legend ─────────────────────────────────────────────────────
    ws.merge_cells("A3:L3")
    c = ws["A3"]
    c.value = (
        "STATUS LEGEND:  "
        "ACTIVE=Live runtime code   RETIRED=Legacy/unused   "
        "CONFIG=Configuration/template   TEMPLATE=Fill-in placeholder   "
        "DESIGN=Architecture/design doc   DOCS=Governance doc   "
        "GENERATED=Runtime-created (gitignored)   MOCK=Test fixture data   "
        "ASSET=Image/data reference"
    )
    c.fill = fill("FFF8E7")
    c.font = Font(name="Calibri", size=9, italic=True)
    c.alignment = Alignment(horizontal="left", wrap_text=True)
    ws.row_dimensions[3].height = 22

    # ── Module summary table ───────────────────────────────────────
    ws.merge_cells("A4:L4")  # spacer
    ws["A4"].value = ""

    summ_headers = [
        ("Module / Category", 28),
        ("Sheet Name", 22),
        ("KB Entries", 12),
        ("Primary Purpose", 52),
        ("Key Files", 46),
        ("Status", 12),
    ]
    write_header_row(ws, summ_headers, row=5, bg=HDR_BLUE)

    _summary_rows = [
        (
            "Core Runtime",
            "Core Runtime",
            "Core Runtime",
            "Shared services: broker, state, event bus, config, resilience, runtime logging",
            "core/broker.py, core/state.py, core/event_bus.py, core/config.py, core/runtime_logging.py",
            "ACTIVE",
        ),
        (
            "Trading Modules (7)",
            "Modules",
            "Modules",
            "ATO protection, trade entry, profit trailing, overnight hedge, position monitor, emergency exit, RATRIPAL",
            "modules/ato_protection.py, modules/ratripal.py, modules/overnight_hedge.py",
            "ACTIVE",
        ),
        (
            "Telegram Bots (5+1)",
            "Telegram Bots",
            "Telegram Bots",
            "DRISHTI (token/health), KAVACH (trading), SANCHALAK (control), SARANSH (summary), JAGRAN (incidents), LAKSHMI (P&L)",
            "bat_telegram/bots/drishti/bot.py, kavach-2.0/bat_telegram/bots/kavach2/bot.py, bat_telegram/bots/sanchalak/bot.py",
            "ACTIVE",
        ),
        (
            "Simulator",
            "Simulator",
            "Simulator",
            "Flask localhost:5001 standalone Telegram simulator — no batman imports; full 5-bot test harness",
            "simulator/app.py, simulator/index.html, simulator/market.html",
            "ACTIVE",
        ),
        (
            "Tests (144 passing)",
            "Tests",
            "Tests",
            "pytest suite covering core, modules, resilience, incidents, logging, RATRIPAL",
            "tests/conftest.py, tests/test_modules.py, tests/test_core.py",
            "ACTIVE",
        ),
        (
            "Config & Templates",
            "Config",
            "Config",
            "settings.json, .env.example, token.env templates, VS Code tasks, .gitignore, AI instructions",
            "config/settings.json, config/.env.example, telegram/bots/*/token.env.example",
            "CONFIG",
        ),
        (
            "Design & Docs",
            "Design & Docs",
            "Design & Docs",
            "Bot design specs, architecture docs, CONTEXT.md, DESIGN.md, session logs, open questions",
            "CONTEXT.md, DESIGN.md, telegram/design/*.md, SESSION_CAPTURE_LOG.md",
            "DESIGN",
        ),
        (
            "Reference & Governance",
            "Reference",
            "Reference",
            "Function ownership index, change routing matrix, decision register, technical playbook",
            "reference/FUNCTION_OWNERSHIP_INDEX.md, reference/TECHNICAL_CHANGE_INDEX.md",
            "DOCS",
        ),
        (
            "Tools & Scripts",
            "Tools",
            "Tools",
            "VPS smoke test, clipboard OCR extractor, image OCR engine, this inventory generator",
            "tools/vps-smoke-windows.ps1, tools/ocr-from-clipboard.ps1, tools/read_image_ocr.py",
            "ACTIVE",
        ),
        (
            "Bot Legacy (Retired)",
            "Bot Legacy",
            "Bot Legacy",
            "Retired bot/ folder — AlgoScheduler still called by main.py; all handlers retired",
            "bot/algo_scheduler.py (still active), bot/handlers/* (retired)",
            "RETIRED",
        ),
        (
            "Data & Analytics",
            "Data & Analytics",
            "Data & Analytics",
            "Runtime data: deployment files, ATO telemetry/ledger/snapshots, incident ledgers, smoke reports",
            "data/analytics/ato_execution_telemetry.csv, data/analytics/ato/ato_trade_ledger.csv",
            "GENERATED",
        ),
        (
            "Testing Mocks",
            "Testing Mocks",
            "Testing Mocks",
            "Simulator mock data, broker stubs, sample deployments, test scenario catalogue",
            "testing/mocks/sim_access_token.json, testing/mocks/deployment_apr7.json",
            "MOCK",
        ),
        (
            "Assets",
            "Assets",
            "Assets",
            "Hedge box screenshots (authoritative zone baseline), production data images, flowchart PNGs, OCR outputs",
            "screenshots/hedge box/hedge_box_image.jpg, Prod Data/Hedge Box/*.png, logs/",
            "ASSET",
        ),
    ]

    for i, (module, sheet_name, cat_filter_key, purpose, key_files, status) in enumerate(
        _summary_rows, start=6
    ):
        count = len(
            get_kb_rows(cat_filter_key if cat_filter_key != "Design & Docs" else ["Design", "Docs"])
        )
        bg_hex = STATUS_BG.get(status, ALT_ROW if i % 2 == 0 else "FFFFFF")
        if i % 2 == 0 and bg_hex == "FFFFFF":
            bg_hex = ALT_ROW
        row_vals = [module, sheet_name, str(count), purpose, key_files, status]
        for j, val in enumerate(row_vals, 1):
            c = ws.cell(row=i, column=j, value=val)
            c.fill = fill(bg_hex)
            c.font = body_font(bold=(j == 1))
            c.alignment = l_align(wrap=(j in [4, 5]))
            c.border = thin_border()
        ws.row_dimensions[i].height = 32

    note_row = len(_summary_rows) + 8
    ws.merge_cells(f"A{note_row}:L{note_row}")
    c = ws[f"A{note_row}"]
    c.value = (
        "ARCHITECTURE:  main.py → asyncio.run(batman_main())  "
        "→  Task: DRISHTI (token delivery, fleet health, 9AM/EOD prompts)  "
        "→  Task: KAVACH (deploy wizard, ATO control, hedge confirm)  "
        "→  Task: SANCHALAK (global control plane)  "
        "→  Task: SARANSH (EOD analytics digest)  "
        "→  Task: JAGRAN (incident alert channel, startup gate)  "
        "→  Task: LAKSHMI (P&L/MTM reporting, optional)  "
        "→  Task: AlgoScheduler → starts/stops 7 modules (ATO, Entry, Trailing, Hedge, Monitor, EmergencyExit, RATRIPAL)  "
        "|  Shared: BatmanBroker, StateManager, EventBus, Config"
    )
    c.fill = fill("FFF8E7")
    c.font = Font(name="Calibri", size=9, italic=True)
    c.alignment = Alignment(horizontal="left", wrap_text=True)
    ws.row_dimensions[note_row].height = 52

    for i, (_, w) in enumerate(summ_headers, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def write_venv_sheet(wb) -> None:
    """Summarise .venv installed packages — key ones with full annotation."""
    ws = wb.create_sheet(title="Python Packages (.venv)")
    pkg_cols = [
        ("Package Name", 26),
        ("Install Path", 46),
        ("Category", 18),
        ("Purpose / Used For", 54),
        ("Key Internal Files", 36),
        ("Used By (Batman)", 42),
        ("Status", 12),
    ]
    write_header_row(ws, pkg_cols)
    ws.freeze_panes = "A2"

    annotated = [
        (
            "python-telegram-bot",
            "Telegram SDK",
            "Async Telegram Bot API framework (v20+). Provides Application, CommandHandler, CallbackQueryHandler, InlineKeyboardMarkup, Bot.send_message. Used by all 5 active bots.",
            "telegram/ext/application.py, telegram/bot.py, telegram/ext/filters.py",
            "bat_telegram/bots/*.py",
            "ACTIVE",
        ),
        (
            "dhan-tradehull",
            "Broker SDK",
            "Dhan-Tradehull v3.2.0 wrapper. Provides access_token auth mode, place_order(), get_positions(), get_ltp(). Used exclusively by core/broker.py.",
            "Dhan_Tradehull/Dhan_Tradehull.py",
            "core/broker.py",
            "ACTIVE",
        ),
        (
            "dhanhq",
            "Broker SDK",
            "Official Dhan HQ Python SDK (v2.2.0). Market feed (DhanFeed), order updates, DhanContext auth. Used indirectly via dhan-tradehull.",
            "dhanhq/dhan_http.py, dhanhq/marketfeed.py, dhanhq/dhan_context.py",
            "core/broker.py (indirect)",
            "ACTIVE",
        ),
        (
            "flask",
            "Web Framework",
            "WSGI micro web framework. Used exclusively by simulator/app.py to serve REST API endpoints at localhost:5001. NOT in production runtime.",
            "flask/app.py, flask/wrappers.py, flask/routing.py",
            "simulator/app.py only",
            "ACTIVE",
        ),
        (
            "openpyxl",
            "Excel I/O",
            "Read/write .xlsx files. Used for ATO ledger XLSX snapshot export and JAGRAN incident workbook export.",
            "openpyxl/workbook/workbook.py, openpyxl/styles/*.py, openpyxl/utils.py",
            "modules/ato_protection.py, bat_telegram/incident_publisher.py, tools/generate_file_inventory.py",
            "ACTIVE",
        ),
        (
            "pandas",
            "Data Processing",
            "DataFrame library. Used for CSV read/merge in ATO telemetry and summary analytics paths.",
            "pandas/core/frame.py, pandas/io/parsers.py",
            "modules/ato_protection.py, bat_telegram/bots/saransh/bot.py",
            "ACTIVE",
        ),
        (
            "pytz",
            "Timezone",
            "IANA timezone library. Used for all IST (Asia/Kolkata) datetime conversions throughout runtime and logging.",
            "pytz/__init__.py, pytz/tzinfo.py",
            "core/utils.py, core/runtime_logging.py, modules/*.py",
            "ACTIVE",
        ),
        (
            "aiohttp",
            "Async HTTP",
            "Async HTTP client/server. Used internally by python-telegram-bot for all Telegram API calls (polling and webhook modes).",
            "aiohttp/client.py, aiohttp/connector.py",
            "bat_telegram/bots/*.py (indirect via python-telegram-bot)",
            "ACTIVE",
        ),
        (
            "requests",
            "Sync HTTP",
            "Synchronous HTTP client. Used by Dhan SDK (dhan-tradehull) for broker REST API calls.",
            "requests/api.py, requests/sessions.py",
            "core/broker.py (indirect via Dhan SDK)",
            "ACTIVE",
        ),
        (
            "websockets",
            "WebSocket",
            "WebSocket client. Used by Dhan market feed (dhanhq) for live NIFTY LTP streaming.",
            "websockets/client.py, websockets/connection.py",
            "core/broker.py (indirect via dhanhq)",
            "ACTIVE",
        ),
        (
            "pytest",
            "Test Framework",
            "Python test runner. Discovers and runs tests/ suite. Used only in dev/CI — not in production runtime.",
            "pytest/main.py, _pytest/fixtures.py, _pytest/python.py",
            "tests/*.py (dev/CI only)",
            "ACTIVE",
        ),
        (
            "ruff",
            "Linter",
            "Fast Python linter (Rust-based). Enforces code quality rules per pyproject.toml on all .py files. CI gate.",
            "ruff (binary executable)",
            "All .py files (CI gate — not imported at runtime)",
            "ACTIVE",
        ),
        (
            "black",
            "Formatter",
            "Python code formatter. Enforces consistent style (100 char line length) per pyproject.toml. CI gate.",
            "black/__main__.py, black/linegen.py",
            "All .py files (CI gate — not imported at runtime)",
            "ACTIVE",
        ),
        (
            "mypy",
            "Type Checker",
            "Static type checker. Validates type annotations in core/, modules/, bat_telegram/, main.py. CI gate.",
            "mypy/__main__.py, mypy/checker.py",
            "core/*.py, modules/*.py, bat_telegram/*.py (CI gate)",
            "ACTIVE",
        ),
        (
            "pytesseract",
            "OCR",
            "Python wrapper for Tesseract OCR engine. Used by tools/read_image_ocr.py to extract text from hedge box screenshots.",
            "pytesseract/pytesseract.py",
            "tools/read_image_ocr.py only",
            "ACTIVE",
        ),
        (
            "Pillow",
            "Image Processing",
            "Python Imaging Library fork. Used by tools/read_image_ocr.py to load and preprocess images before OCR.",
            "PIL/Image.py, PIL/ImageOps.py",
            "tools/read_image_ocr.py only",
            "ACTIVE",
        ),
    ]

    venv_site = ROOT / ".venv" / "Lib" / "site-packages"
    annotated_names = {a[0].lower().replace("-", "_") for a in annotated}

    for i, (pkg, cat, purpose, key_files, used_by, status) in enumerate(annotated, start=2):
        pkg_path = f".venv/Lib/site-packages/{pkg.replace('-','_')}/"
        bg_hex = STATUS_BG.get(status, ALT_ROW if i % 2 == 0 else "FFFFFF")
        row_vals = [pkg, pkg_path, cat, purpose, key_files, used_by, status]
        for j, val in enumerate(row_vals, 1):
            c = ws.cell(row=i, column=j, value=val)
            c.fill = fill(bg_hex)
            c.font = body_font(bold=(j == 1))
            c.alignment = l_align()
            c.border = thin_border()

    # Add unlisted packages as generic entries
    if venv_site.exists():
        extra_row = len(annotated) + 2
        for item in sorted(venv_site.iterdir()):
            if not item.is_dir():
                continue
            if item.name.startswith(("_", ".")):
                continue
            if item.suffix in (".dist-info", ".data"):
                continue
            if item.name.lower().replace("-", "_") in annotated_names:
                continue
            bg_hex = ALT_ROW if extra_row % 2 == 0 else "FFFFFF"
            row_vals = [
                item.name,
                f".venv/Lib/site-packages/{item.name}/",
                "Indirect Dependency",
                "Transitive or build-time dependency. See package PyPI page for details.",
                "-",
                "Indirect (via pip dependency chain)",
                "GENERATED",
            ]
            for j, val in enumerate(row_vals, 1):
                c = ws.cell(row=extra_row, column=j, value=val)
                c.fill = fill(STATUS_BG["GENERATED"])
                c.font = body_font()
                c.alignment = l_align()
                c.border = thin_border()
            extra_row += 1

    for i, (_, w) in enumerate(pkg_cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def write_cache_sheet(wb) -> None:
    ws = wb.create_sheet(title="Cache & Generated")
    cache_cols = [
        ("Path / Pattern", 42),
        ("Type", 18),
        ("Generated By", 32),
        ("Purpose", 50),
        ("Safe to Delete?", 18),
        ("Status", 12),
    ]
    write_header_row(ws, cache_cols)
    ws.freeze_panes = "A2"

    entries = [
        (
            ".venv/",
            "Virtual Environment",
            "pip install -r requirements.txt",
            "Isolated Python environment with all runtime + dev dependencies. Interpreter: .venv/Scripts/python.exe (Windows) or .venv/bin/python (Linux). Gitignored.",
            "YES — regenerate with: pip install -r requirements.txt",
            "GENERATED",
        ),
        (
            ".mypy_cache/",
            "Type Check Cache",
            "mypy type checker",
            "Incremental mypy cache. Speeds up repeated type-check runs by caching inferred types.",
            "YES — auto-regenerated",
            "CACHE",
        ),
        (
            ".pytest_cache/",
            "Test Runner Cache",
            "pytest",
            "pytest run metadata: test IDs, last-failed list, random seeds. Enables --last-failed reruns.",
            "YES — auto-regenerated",
            "CACHE",
        ),
        (
            ".ruff_cache/",
            "Linter Cache",
            "ruff linter",
            "Ruff incremental lint cache. Binary hash files per source file for fast re-lint.",
            "YES — auto-regenerated",
            "CACHE",
        ),
        (
            "**/__pycache__/",
            "Bytecode Cache",
            "Python interpreter",
            "Compiled .pyc bytecode files for faster module imports. Auto-created on first import.",
            "YES — auto-regenerated",
            "CACHE",
        ),
        (
            "**/*.pyc",
            "Bytecode File",
            "Python interpreter",
            "Individual compiled bytecode files in __pycache__ directories.",
            "YES",
            "CACHE",
        ),
        (
            "data/access_token.json",
            "Runtime Secret",
            "core/token_store.py (written daily by DRISHTI)",
            "Persisted Dhan JWT access token with saved_at timestamp. Read at startup to restore token after reboot. GITIGNORED — never commit.",
            "NO — contains live broker credentials",
            "GENERATED",
        ),
        (
            "data/deployments/batman_YYYY-MM-DD.json",
            "Runtime Data",
            "modules/batman_entry.py (KAVACH wizard)",
            "Active iron condor deployment file. Written on /register wizard completion. Read by all 7 trading modules as shared contract.",
            "NO — active trading state",
            "GENERATED",
        ),
        (
            "data/deployments/archive/*.json",
            "Runtime Archive",
            "/batman_complete command in KAVACH",
            "Completed session deployment files. Historical record. Archived after /batman_complete.",
            "YES if session fully complete",
            "GENERATED",
        ),
        (
            "data/analytics/ato_execution_telemetry.csv",
            "Runtime Analytics",
            "modules/ato_protection.py",
            "Append-only ATO event log. One row per ATO buy/exit event. SARANSH reads for EOD section 2.",
            "NO — active telemetry source",
            "GENERATED",
        ),
        (
            "data/analytics/ato/ato_trade_ledger.csv",
            "Runtime Analytics",
            "modules/ato_protection.py",
            "Consolidated ATO cycle pairs (buy+exit). Source for XLSX snapshots. SARANSH reads for P&L impact.",
            "NO — active trading record",
            "GENERATED",
        ),
        (
            "data/analytics/ato/snapshots/*.xlsx",
            "Runtime Analytics",
            "modules/ato_protection.py (openpyxl)",
            "Lock-safe XLSX copies of ato_trade_ledger.csv for Excel viewing while trading continues.",
            "YES — re-created on next cycle",
            "GENERATED",
        ),
        (
            "data/analytics/incidents/",
            "Runtime Analytics",
            "bat_telegram/incident_publisher.py",
            "Daily JAGRAN incident CSV + XLSX ledger files. Incident audit trail.",
            "YES after review",
            "GENERATED",
        ),
        (
            "data/analytics/runtime_smoke/",
            "Runtime Logs",
            "core/runtime_logging.py",
            "Time-windowed bot/module runtime log files. Structure: YYYY-MM/YYYY-MM-DD/logs/*.log.",
            "YES after review",
            "GENERATED",
        ),
        (
            "data/analytics/summaries/",
            "Runtime Analytics",
            "bat_telegram/bots/saransh/bot.py",
            "SARANSH EOD summary text files (YYYY-MM-DD_summary.txt). One per summary run.",
            "YES after review",
            "GENERATED",
        ),
        (
            "data/analytics/vps_validation/",
            "Validation Reports",
            "tools/vps-smoke-windows.ps1",
            "VPS smoke test reports (report.json, report.txt, first-start stdout/stderr). Go-live evidence.",
            "YES after go-live",
            "GENERATED",
        ),
        (
            "logs/clipboard_ocr/",
            "OCR Outputs",
            "tools/ocr-from-clipboard.ps1",
            "Clipboard OCR extraction history: PNG captures + structured JSON/TXT outputs.",
            "YES",
            "GENERATED",
        ),
        (
            ".editorconfig",
            "Editor Config",
            "Developer-maintained",
            "Cross-editor formatting standards. Not a cache — intentional config file.",
            "NO — editor configuration",
            "CONFIG",
        ),
        (
            ".vscode/",
            "Editor Config",
            "Developer-maintained",
            "VS Code settings, tasks, and extension recommendations. Gitignored (no secrets here).",
            "NO — workspace configuration",
            "CONFIG",
        ),
    ]

    for i, row_data in enumerate(entries, start=2):
        status = row_data[5]
        bg_hex = STATUS_BG.get(status, ALT_ROW if i % 2 == 0 else "FFFFFF")
        for j, val in enumerate(row_data, 1):
            c = ws.cell(row=i, column=j, value=val)
            c.fill = fill(bg_hex)
            c.font = body_font(bold=(j == 1))
            c.alignment = l_align()
            c.border = thin_border()

    for i, (_, w) in enumerate(cache_cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default empty sheet

    print("Building Overview sheet ...")
    write_overview_sheet(wb)

    for sheet_title, cat_filter in SHEET_DEFS:
        if sheet_title == "Overview":
            continue
        print(f"Building sheet: {sheet_title} ...")
        write_data_sheet(wb, sheet_title, cat_filter)

    print("Building Python Packages (.venv) sheet ...")
    write_venv_sheet(wb)

    print("Building Cache & Generated sheet ...")
    write_cache_sheet(wb)

    out_path = ROOT / "PROJECT_FILE_INVENTORY.xlsx"
    wb.save(str(out_path))

    total = len(KB)
    sheets = [ws.title for ws in wb.worksheets]
    print(f"\n[DONE] Saved: {out_path}")
    print(f"  First-party KB entries : {total}")
    print(f"  Sheets ({len(sheets)})            : {', '.join(sheets)}")


if __name__ == "__main__":
    main()

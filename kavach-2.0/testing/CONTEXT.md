# Batman v3 — Testing Context
## Read this first at the start of every testing session.
## Last updated: 2026-04-04  |  Baseline: 129/129 tests passing

---

## 1. Quick Start

```powershell
# From batman_v3/ root — always run from here
cd "c:\Users\rkhataw\OneDrive - Franklin Templeton\Documents\Copilot\TR\Batman\batman_v3"

# Full suite (fast, ~3.5s)
python -m pytest tests/ -q --tb=short

# Single module only
python -m pytest tests/test_core.py -q --tb=short
python -m pytest tests/test_modules.py -q --tb=short
python -m pytest tests/test_resilience.py -q --tb=short

# Single class
python -m pytest tests/test_modules.py::TestATOProtection -q --tb=short

# Single test
python -m pytest tests/test_core.py::TestTokenStore::test_save_and_load_roundtrip -v

# With coverage
python -m pytest tests/ --cov=core --cov=modules --cov=bot --cov-report=term-missing
```

---

## 2. Current Baseline (2026-04-04)

| File                     | Tests   | Classes | Status        |
| ------------------------ | ------- | ------- | ------------- |
| tests/test_core.py       | 40      | 6       | ✅ all pass    |
| tests/test_modules.py    | 71      | 12      | ✅ all pass    |
| tests/test_resilience.py | 18      | 3       | ✅ all pass    |
| **TOTAL**                | **129** | **21**  | **129/129 ✅** |

Python: 3.12.10 · pytest: 9.0.2 · anyio: 4.11.0

---

## 3. Testing Architecture

### What we mock (never touch real broker / Telegram)

```
tests/conftest.py
  └── MockBroker                     ← drop-in for BatmanBroker
        ├── _nifty_ltp               ← set this to control spot price
        ├── _orders                  ← list of placed orders (inspect after calls)
        ├── _positions               ← pd.DataFrame (set for position tests)
        ├── get_ltp(names)           ← returns dict {name: _nifty_ltp}
        ├── get_nifty_ltp()          ← returns _nifty_ltp float
        ├── place_market_order(...)  ← records into _orders, returns "ORD-000N"
        └── get_order_status()       ← always returns "TRADED"

  Fixtures (pytest fixtures at function scope):
    config      ← BatmanConfig loaded from config/settings.json
    state       ← StateManager writing to tmp_path/state.json
    event_bus   ← fresh EventBus()
    mock_broker ← fresh MockBroker()
```

### Key mock patterns used in tests

```python
# Control spot price
mock_broker._nifty_ltp = 25505.0   # CE breach (sell at 25500 + 5 retrace buffer)

# Inject open positions for wizard / startup scan
mock_broker._positions = pd.DataFrame([...])   # see testing/mocks/ for sample DataFrames

# Inspect what orders were placed
assert len(mock_broker._orders) == 1
assert mock_broker._orders[0]["symbol"] == "NIFTY25APR25550CE"

# Capture EventBus events
received = []
event_bus.subscribe(Event.ATO_TRIGGERED, lambda e, d: received.append(d))
# ... run action ...
assert received[0]["side"] == "CE"
```

### Telegram is fully mocked (no real bot needed)

```
conftest.py stubs out all of:
  telegram, telegram.ext, telegram.error, telegram.constants
→ Bot modules can be imported without credentials
→ Handler tests use MagicMock for Update/Context objects
```

---

## 4. Testing Batches — What's Done, What's Next

### BATCH 1 — Core Framework ✅ DONE (129 tests)

| Domain         | Class                       | Tests | Notes                                  |
| -------------- | --------------------------- | ----- | -------------------------------------- |
| Config         | TestConfig                  | 4     | dot-notation get, defaults, sections   |
| State          | TestState                   | 4     | persistence, reset, defaults           |
| EventBus       | TestEventBus                | 3     | pub/sub, unsubscribe, history          |
| Utils          | TestUtils                   | 5     | strike rounding, P&L format            |
| Entry window   | TestEntryWindow             | 5     | holiday-aware Wednesday logic          |
| Symbols        | TestOptionSymbolUtils       | 10    | parse_option_symbol, build_ato_symbols |
| TokenStore     | TestTokenStore              | 10    | save/load, expiry, clear, atomic write |
| ATO protect    | TestATOProtection           | 8     | CE/PE breach trigger & retrace         |
| ATO startup    | TestATOStartupScan          | 15    | adopt manual, auto-place, stale reset  |
| Entry          | TestBatmanEntry             | 1     | deploy iron condor                     |
| Trailing       | TestProfitTrailing          | 1     | hard stop detection                    |
| Emergency      | TestEmergencyExit           | 2     | execute, reset ATO state               |
| Lifecycle      | TestModuleLifecycle         | 2     | disable via config, status dict        |
| Config val     | TestConfigValidation        | 4     | missing keys, bad values               |
| Auto-restart   | TestModuleAutoRestart       | 1     | crash → restart                        |
| Entry date     | TestNextEntryDate           | 4     | next Wednesday skip holiday            |
| Deploy helpers | TestDeployHandlerHelpers    | 9     | parse symbol, classify legs            |
| Scheduler      | TestAlgoSchedulerState      | 8     | tick logic, time selection             |
| Deploy state   | TestDeploymentStateDefaults | 5     | defaults, set, reset                   |
| ATO cycles     | TestATOMaxCycles            | 4     | block after max, unlimited, event      |
| EOD prompt     | TestAlgoSchedulerEODPrompt  | 5     | fire on expiry, no double fire         |
| Retry          | TestRetry                   | 6     | first try, retries, max, callback      |
| Circuit        | TestCircuitBreaker          | 9     | open/close/half-open, decorator        |
| Confirm        | TestConfirmOrder            | 4     | TRADED, rejected, timeout              |

---

### BATCH 2 — KAVACH Bot (deploy wizard + command handlers) 🔲 NEXT

**Target file:** `tests/test_kavach.py`  
**Target module:** `telegram/bots/kavach/bot.py` + `deploy_wizard.py`

| Test Class              | Tests planned | Focus                                                       |
| ----------------------- | ------------- | ----------------------------------------------------------- |
| TestDeployWizardFlow    | ~12           | Full 4-step wizard happy path using real Apr 7 positions    |
| TestDeployWizardCancel  | ~4            | Cancel at each step, verify no file written                 |
| TestDeployWizardTimeout | ~2            | Idle > 120s → cancelled, log entry written                  |
| TestDeployFilePersist   | ~5            | File written correctly, schema matches deployment_apr7.json |
| TestKavachCommands      | ~8            | /pause, /resume, /start_now, /ato, /legs, /status           |
| TestBatmanComplete      | ~4            | Cleanup: archive file, state reset, log entry               |
| TestEmergencyExitWizard | ~4            | Confirmation inline keyboard, 30s timeout, cleanup          |

**Mock data to use:** `testing/mocks/positions_apr7.json` (real broker positions from screenshot)

---

### BATCH 3 — DRISHTI Bot (token + health) 🔲 FUTURE

**Target file:** `tests/test_drishti.py`  
**Target module:** `telegram/bots/drishti/bot.py`

| Test Class                | Tests planned | Focus                                                              |
| ------------------------- | ------------- | ------------------------------------------------------------------ |
| TestTokenReceipt          | ~6            | Receive JWT → hot_reload_token() called → TokenStore.save() called |
| TestTokenValidation       | ~4            | NIFTY LTP fetch OK → ✅ / fetch fails → ⚠️                           |
| TestTokenReminderSchedule | ~6            | Fires at 09:00/15:30/23:00, suppressed when valid                  |
| TestSilentNotifications   | ~4            | disable_notification=True for messages after 15:30 IST             |
| TestHealthAlert           | ~4            | Immediate alert when broker call fails (Type 2 alert)              |
| TestTokenStatusCommand    | ~2            | /token_status shows expiry time                                    |
| TestNoReminderOnHoliday   | ~2            | Reminder scheduler skips NSE holidays                              |

---

### BATCH 4 — LAKSHMI Bot (MTM + P&L) 🔲 FUTURE

**Target file:** `tests/test_lakshmi.py`  
**Target module:** `telegram/bots/lakshmi/bot.py`

| Test Class             | Tests planned | Focus                                             |
| ---------------------- | ------------- | ------------------------------------------------- |
| TestMTMAlerts          | ~6            | -₹5k alert, -₹8k alert, alert not fired twice     |
| TestProfitAlert        | ~3            | Target hit → immediate notification               |
| TestPnlCommand         | ~4            | /pnl returns calculated MTM from broker           |
| TestEODSummary         | ~3            | EOD snap at 15:30, formatted P&L table            |
| TestTrailingActivation | ~3            | Trailing start/stop events → LAKSHMI notification |

---

### BATCH 5 — Integration (cross-module) 🔲 FUTURE

**Target file:** `tests/test_integration.py`

| Test Class                 | Tests planned | Focus                                                  |
| -------------------------- | ------------- | ------------------------------------------------------ |
| TestATOReadsDeploymentFile | ~5            | ato_protection.py reads batman_*.json, not state.json  |
| TestDeployWizardArmsATO    | ~3            | Wizard write → ATO module picks up file on next tick   |
| TestBatmanCompleteFullFlow | ~4            | /batman_complete → file archived → ATO enters WAIT     |
| TestVPSRestartFlow         | ~3            | TokenStore load → broker connect → ATO armed from file |

---

### BATCH 6 — End-to-End Simulation 🔲 FUTURE

**Target file:** `tests/test_e2e_simulation.py`  
Uses real Apr 7 positions. Drives all 3 bots + algo modules together in a single test run.

The interactive visual simulation is at:
`telegram/design/batman_simulation.html` — open in browser for the full walkthrough.

---

## 5. Mock Data Reference

All mock fixtures live in `testing/mocks/`.

| File                       | What it represents                                                          |
| -------------------------- | --------------------------------------------------------------------------- |
| `positions_apr7.json`      | Real Dhan broker open positions (Apr 7 expiry, from 04-Apr-2026 screenshot) |
| `deployment_apr7.json`     | batman_*.json deployment file that KAVACH would write for those positions   |
| `deploy_log_sample.jsonl`  | Sample audit log (wizard_started → confirmed → batman_complete)             |
| `broker_stub_positions.py` | Pandas DataFrame builder matching Dhan API response shape                   |

---

## 6. Conventions & Rules

### File placement
```
tests/              ← pytest test files ONLY (test_*.py)
tests/conftest.py   ← shared fixtures (MockBroker, config, state, event_bus)
testing/            ← documentation, mock data, scenario specs
testing/mocks/      ← JSON/jsonl fixture data + DataFrame builders
```

### Naming
- Test files: `test_<domain>.py`
- Test classes: `Test<FeatureName>`
- Test methods: `test_<what>_<expected_result>`

### One assertion domain per test
Each test proves one behaviour. Do not combine "wizard step 1 + file written" into one test.

### Always use `tmp_path` for file I/O
```python
def test_something(self, tmp_path):
    store = TokenStore(path=tmp_path / "access_token.json")
```
Never write to `data/` in tests.

### Never use real broker credentials
MockBroker in conftest.py is sufficient for everything in Batches 1–5.

### Check `_orders` to assert order placement
```python
assert mock_broker._orders[0]["symbol"] == expected_symbol
assert mock_broker._orders[0]["side"]   == "BUY"
```

---

## 7. Simulation Model

The Telegram interaction simulation is documented in `testing/SCENARIOS.md`.  
The interactive visual is at `telegram/design/batman_simulation.html`.

The simulation uses **real April 7, 2026 positions**:

```
Spot: ₹22,713  |  Expiry: 07-Apr-2026 (Tuesday, 3 DTE from 04-Apr)

PE BUY  NIFTY07APR22050PE  LONG   780  avg ₹95.19  LTP ₹79.05  P&L −₹12,587
PE SELL NIFTY07APR22000PE  SHORT 1560  avg ₹87.00  LTP ₹72.00  P&L +₹23,400
CE SELL NIFTY07APR23200CE  SHORT 1560  avg ₹76.00  LTP ₹71.10  P&L  +₹7,644
CE BUY  NIFTY07APR23150CE  LONG   780  avg ₹88.09  LTP ₹83.50  P&L  −₹3,578
─────────────────────────────────────────────────
Total P&L: +₹14,878.50  🟢
```

ATO auto-calculated from these:
```
PE ATO: NIFTY07APR21950PE  (22000 − 50)
CE ATO: NIFTY07APR23250CE  (23200 + 50)
Margin: 763 pts (PE side) / 537 pts (CE side)
```

---

## 8. Pending Code (Test Targets Not Yet Written)

| Module          | File                                    | Status                            | Blocks Batch |
| --------------- | --------------------------------------- | --------------------------------- | ------------ |
| KAVACH bot      | `telegram/bots/kavach/bot.py`           | ❌ Not written                     | Batch 2      |
| KAVACH wizard   | `telegram/bots/kavach/deploy_wizard.py` | ❌ Not written                     | Batch 2      |
| DRISHTI bot     | `telegram/bots/drishti/bot.py`          | ❌ Not written                     | Batch 3      |
| LAKSHMI bot     | `telegram/bots/lakshmi/bot.py`          | ❌ Not written                     | Batch 4      |
| ATO file read   | `modules/ato_protection.py` (partial)   | 🔄 Needs `_load_deployment_file()` | Batch 5      |
| main.py asyncio | `main.py`                               | 🔄 Needs rewrite                   | Batch 5      |

---

## 9. Session Handoff Notes

When resuming a testing session, check:
1. `python -m pytest tests/ -q` — confirm baseline still 129/129
2. This file (CONTEXT.md) — which batch we are working on
3. `testing/TEST_INVENTORY.md` — fine-grained test status
4. `testing/SCENARIOS.md` — scenario specs for the batch in progress

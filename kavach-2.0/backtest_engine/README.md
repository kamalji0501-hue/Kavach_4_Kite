# Shadow Engine (backtest_engine)

Live **NIFTY** from DRISHTI, **Sensibull-shaped** position book, **production** KAVACH/ATO code paths, **virtual** orders in **UAT** mode.

The legacy `simulator/` Flask app is **not** used. Use **`Mode/`** bats to switch `dev` | `uat` | `prod`.

## Locked rules

| Rule | Value |
|------|--------|
| NIFTY lot size | **65** (NSE; all brokers) |
| Initial shadow book | **4 iron-condor legs only** |
| Protect legs (e.g. 23150 PE, 23850 CE) | Appear only after ATO **simulated** BUY |
| Symbols / `securityId` | Dhan **instrument master** (+ JWT gate) |
| Expiry | Taken from fixture (`expiry_date` / `expiry_label`) |

## Phase P0 — validate fixture (today)

Confirms Sensibull screenshot legs resolve to the same symbols/IDs production would use.

```bat
cd /d "H:\RK Data\Algo Trading Parent\DEV Batman Algo"
.venv\Scripts\python.exe backtest_engine\tools\validate_fixture.py
```

Requires:

- `config/.env` → `DHAN_CLIENT_CODE`
- Fresh JWT in `data/access_token.json` (via DRISHTI)

Output:

- Console report (same helpers as KAVACH: `filter_nifty_positions`, `validate_side_ratio`, `build_ato_protect_symbol`)
- `backtest_engine/fixtures/resolved/jun9_2026_sensibull_resolved.json`

Option chain API is attempted for cross-check; if empty (e.g. after market close), **instrument master** remains authoritative.

## Current fixture

`fixtures/sensibull/jun9_2026_sensibull.json` — 09 Jun 2026 weekly, spot 23483.55 at capture.

## Roadmap

| Phase | Deliverable |
|-------|-------------|
| **P0** | `validate_fixture.py` (this) |
| **P1** | `ShadowBroker` + order ledger |
| **P2** | `run_shadow_stack` — DRISHTI + KAVACH + ATO, manual `/register` |
| **P3** | Gate 5 runbook + evidence |

Automated Telegram wizard replay is **out of scope** until you request it.

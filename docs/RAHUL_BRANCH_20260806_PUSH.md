# Rahul branch push — 2026-08-06

## What this branch contains

Phase-1 Rahul track on Kamalji VPS (`/home/ubuntu/rahul_Changes`), isolated from Kamalji `kamalji` branch / `batman-algo`.

### Architecture
- **Code** in `rahul_Changes` (light package)
- **Runtime data/logs/credentials** in `/home/ubuntu/Trading_Runtime_Rahul` (not in git)
- Symlinks for heavy MarketData / backtest cache → Trading_Runtime_Rahul

### Market Order (Place Order) integration
- Place Order bot remains at `/home/ubuntu/place-order-bot` (backend punch, not Telegram Q&A in master flow)
- `core/order_manager.py` — paper punch via `BackendOrderWorkflow.for_paper`
- ATO `_place_ato_aggressive_limit` uses OrderManager when attached; live clears OM → existing broker path
- Register-first question: **Paper vs Live** (`order_mode` on deployment)

### Observability
- `core/money_audit.py` — JSONL money audit (secrets redacted)
- `core/ato_nifty_tick_csv.py` — NIFTY + ATO CE/PE tick CSV
- DEBUG logging + detail JSONL
- `scripts/robot_verify_phase1.py`, `scripts/run_five_scenario_hardening.py`

### Telegram credentials
- Prefer `Trading_Runtime_Rahul/Credentials/telegram/bots.env` (never committed)
- Example only: `telegram/bots.env.example`

### Baselines (read-only on VPS)
- Working Batman: `/home/ubuntu/batman-algo`
- Working Place Order: `/home/ubuntu/place-order-bot`

### Not in this commit
- Secrets (`.env`, `token.env`, `bots.env`, PEMs, Credentials/)
- Large Dependencies / instrument CSVs (runtime MarketData)
- Live Logs / Cache dumps from Trading_Runtime_Rahul

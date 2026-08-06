# Phase 1 — storage map & folder sizes

Generated on VPS for Rahul track wrap-up.

## Folder sizes

| Area | Size | Path |
|------|------|------|
| rahul_Changes (code) | 250.4 MB | `/home/ubuntu/rahul_Changes` |
| rahul_Changes excl .venv/.git | 22.1 MB | `/home/ubuntu/rahul_Changes` |
| Trading_Runtime_Rahul (data+logs) | 926.5 MB | `/home/ubuntu/Trading_Runtime_Rahul` |
| Runtime Data | 1.2 MB | `/home/ubuntu/Trading_Runtime_Rahul/Data` |
| Runtime Logs | 301.1 KB | `/home/ubuntu/Trading_Runtime_Rahul/Logs` |
| Runtime Credentials | 6.8 KB | `/home/ubuntu/Trading_Runtime_Rahul/Credentials` |
| place-order-bot | 448.6 MB | `/home/ubuntu/place-order-bot` |
| batman-algo baseline | 1.2 GB | `/home/ubuntu/batman-algo` |
| Trading_Runtime (Kamalji) | 435.5 MB | `/home/ubuntu/Trading_Runtime` |
|   · uat (/home/ubuntu/Trading_Runtime_Rahul/Data/data/uat) | 56.5 KB | `/home/ubuntu/Trading_Runtime_Rahul/Data/data/uat` |
|   · uat (/home/ubuntu/Trading_Runtime_Rahul/Logs/uat) | 301.1 KB | `/home/ubuntu/Trading_Runtime_Rahul/Logs/uat` |
|   · ato_tick_csv (/home/ubuntu/Trading_Runtime_Rahul/Data/data/uat/ato_tick_csv) | 960 B | `/home/ubuntu/Trading_Runtime_Rahul/Data/data/uat/ato_tick_csv` |
|   · order_manager (/home/ubuntu/Trading_Runtime_Rahul/Data/data/uat/order_manager) | 0 B | `/home/ubuntu/Trading_Runtime_Rahul/Data/data/uat/order_manager` |
|   · deployments (/home/ubuntu/Trading_Runtime_Rahul/Data/data/uat/deployments) | 0 B | `/home/ubuntu/Trading_Runtime_Rahul/Data/data/uat/deployments` |
| batman data_root() | 56.5 KB | `/home/ubuntu/Trading_Runtime_Rahul/Data/data/uat` |
| batman log_root() | 301.1 KB | `/home/ubuntu/Trading_Runtime_Rahul/Logs/uat` |
| batman deployments_dir() | 0 B | `/home/ubuntu/Trading_Runtime_Rahul/Data/data/uat/deployments` |

## Where things live (Rahul)

| Kind | Location |
|------|----------|
| Releasable code | `/home/ubuntu/rahul_Changes` |
| Runtime data + logs (80GB disk) | `/home/ubuntu/Trading_Runtime_Rahul` |
| Deployments (`batman_*.json`) | `data_root()/deployments` (under Trading_Runtime_Rahul) |
| Money audit JSONL | `Logs/uat/YYYY-MM/YYYY-MM-DD/{bot}/audit/` |
| NIFTY + ATO tick CSV | `Data/.../ato_tick_csv/YYYY-MM/` |
| Paper position book | `Data/.../paper_position_book.json` |
| OrderManager paper ledger | `Data/.../order_manager/` |
| Telegram bots.env | `Trading_Runtime_Rahul/Credentials/telegram/` |
| Place Order backend | `/home/ubuntu/place-order-bot` |
| Kamalji baseline (do not mix) | `/home/ubuntu/batman-algo` + `Trading_Runtime` |

## Phase 1 complete features

- Code lightening (data on runtime disk)
- Consolidated Telegram credentials
- Detailed money audit + DEBUG trading logs
- ATO+NIFTY tick CSV
- Paper vs Live first question on `/register`
- Order sink: paper=FakeBroker+book, live=existing broker path

## Before Phase 2

1. Restart Kavach/Drishti after deploy
2. Dry-run `/register` → Paper end-to-end in UAT
3. Live only after Dhan IP whitelist + checklist
4. Git push when Rahul says


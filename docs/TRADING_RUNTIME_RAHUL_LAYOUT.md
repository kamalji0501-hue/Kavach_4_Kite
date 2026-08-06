# Trading_Runtime_Rahul layout (reference — not full data dump)

Path on VPS: `/home/ubuntu/Trading_Runtime_Rahul`

```
Trading_Runtime_Rahul/
  Archives/
  Backups/
  Cache/                 # backtest cache, etc. (large — not git)
  Config/
  Credentials/           # SECRETS — never git (telegram/bots.env)
  Data/data/uat/         # deployments, ato_tick_csv, paper book, order_manager, analytics
  Database/
  Exports/
  Health/
  Logs/uat/              # money_audit.jsonl, bot all.log, detail_debug.jsonl
  MarketData/            # Dependencies, security_id_list.csv (large — not git)
  Screenshots/
  Temp/
  User/
```

Code tree points here via `core/batman_mode.py` (`data_root`, `log_root`).
Do not commit Credentials, Logs with tokens, or full MarketData.

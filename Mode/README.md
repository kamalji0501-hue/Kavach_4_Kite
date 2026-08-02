# Batman mode launchers (desktop shortcuts)

| Bat file | Effect |
|----------|--------|
| **Set-Dev.bat** | `mode=dev` — live NIFTY, logs in `logs_dev/`, data in `data/dev/`, orders blocked |
| **Set-UAT.bat** | `mode=uat` — virtual broker, `logs_uat/`, `data/uat/` |
| **Set-Prod.bat** | `mode=prod` — config for VPS (`logs_prod/`, `data/prod/`) |
## UAT workflow

1. Double-click **Set-UAT.bat**
2. Paste Sensibull screenshot in `uat/deployed_positions/` (any filename)
3. Start DRISHTI + KAVACH + JAGRAN from `Execution/Start Bots/`
4. KAVACH auto-reads screenshot on start (and again on **Register**)
5. Telegram **Register** — confirm legs in wizard (same as production)

You never edit `config/batman_mode.json` by hand.

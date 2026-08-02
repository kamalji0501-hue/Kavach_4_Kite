# Multi-developer setup — Batman v3

**Goal:** Git repo = **code only**. Each developer’s machine keeps **logs, data, reports, and secrets** outside the repo (Desktop by default).

---

## Folder layout (per laptop)

```
%USERPROFILE%\Desktop\Batman Executed Data\
├── Logs\
│   ├── uat\runtime\YYYY-MM\YYYY-MM-DD\...
│   ├── dev\...
│   └── prod\...
└── Data and Reports\
    ├── data\
    │   ├── shared\          ← JWT, NIFTY cache, DRISHTI/JAGRAN locks
    │   ├── uat\             ← state, deployments, UAT positions, analytics
    │   ├── dev\
    │   └── prod\
    └── reports\
        ├── daily_test_execution\   ← Excel matrix, suite logs
        ├── reliability\
        └── feedback_loop\

%USERPROFILE%\Desktop\Batman-Secrets\
├── config\.env                 ← Dhan credentials (per developer)
└── telegram\bots\<bot>\token.env   ← separate Telegram bots per developer
```

Override paths via `config/local_runtime.json` (gitignored) or env vars:

- `BATMAN_LOGS_ROOT`
- `BATMAN_DATA_REPORTS_ROOT`
- `BATMAN_SECRETS_ROOT`
- `BATMAN_RUNTIME_ROOT` — legacy single-folder layout only

Defaults are in `config/batman_mode.json` (`%USERPROFILE%/Desktop/...`).

---

## First-time setup (new clone)

1. Clone repo, create venv, `pip install -r requirements.txt`
2. Copy secrets ( **your own bots** — do not share Telegram tokens):
   - `telegram/bots/*/token.env.example` → `Desktop/Batman-Secrets/telegram/bots/*/token.env`
   - `config/.env.example` → `Desktop/Batman-Secrets/config/.env`
3. Migrate existing data (if upgrading this laptop):
   ```powershell
   .venv\Scripts\python.exe scripts\migrate_runtime_off_repo.py
   ```
   If you still have the old `Desktop\Batman-Runtime` folder:
   ```powershell
   .venv\Scripts\python.exe scripts\migrate_to_executed_data.py
   ```
4. `Mode\Set-UAT.bat` · start bots via `Execution\Start Bots\`

---

## Git workflow

- **`main`** — Rahul merges tested changes only
- Feature branches → PR → merge after pytest + UAT checks
- **Never commit:** `token.env`, `.env`, logs, data, Excel reports

---

## Where to look (operator)

| Need | Path |
|------|------|
| Today’s KAVACH log | `Desktop\Batman Executed Data\Logs\uat\runtime\YYYY-MM\YYYY-MM-DD\kavach\logs\all.log` |
| UAT state / deployment | `Desktop\Batman Executed Data\Data and Reports\data\uat\` |
| Sensibull book | `Desktop\Batman Executed Data\Data and Reports\data\uat\deployed_positions\` |
| Daily test Excel | `Desktop\Batman Executed Data\Data and Reports\reports\daily_test_execution\` |
| JWT | `Desktop\Batman Executed Data\Data and Reports\data\shared\access_token.json` |

Code repo: implementation, tests, docs, `Execution/` launchers only.

---

## VPS later

Copy the `Data and Reports` + `Logs` layout to the VPS (e.g. `/opt/batman/`) and set `BATMAN_LOGS_ROOT` / `BATMAN_DATA_REPORTS_ROOT` in systemd or `local_runtime.json`. Same code clone; different roots.

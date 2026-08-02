# Folder Maintenance — DEV Batman Algo

Last updated: 2026-06-01

---

## Size snapshot (top-level)

| Folder | ~Size | Action |
|--------|-------|--------|
| `.venv/` | 586 MB | **Keep** — project Python env |
| `Dhan/` | 140 MB | **Reference only** — nested `.venv` inside reference LTP project; excluded from Cursor index |
| `Dependencies/` | 27 MB | Tradehull token cache — keep |
| `.mypy_cache/` | 11 MB | **Safe to delete** — regenerates; gitignored |
| `logs/` | 5 MB | Reorganized — see `LOGGING_LAYOUT.md` |
| `Screenshots from FT Complete Code/` | 3 MB | Reference screenshots — optional archive |
| Source code (`core/`, `bat_telegram/`, …) | < 1 MB each | **Keep** |

**Total repo without `.venv`:** ~180 MB (mostly `Dhan/` reference venv).

---

## Performance / IDE indexing

Already in `.cursorignore`:

- `.venv/`, `logs/`, `data/`, `Dhan/`, caches

This keeps Cursor fast. Do **not** remove `Dhan/` from disk if you still use reference LTP code — it is only excluded from AI indexing.

Optional local cleanup (safe):

```powershell
Remove-Item -Recurse -Force .mypy_cache, .pytest_cache, .ruff_cache -ErrorAction SilentlyContinue
```

---

## What not to delete

| Path | Why |
|------|-----|
| `data/access_token.json` | Dhan JWT |
| `data/nifty_ltp_cache.json` | Live LTP for KAVACH |
| `data/*.lock` | Single-instance locks while bots run |
| `telegram/bots/*/token.env` | Bot credentials |
| `config/.env` | Dhan client code |

---

## Log retention policy (recommended)

| Area | Retention |
|------|-----------|
| `logs/bots/*/startup.log` | Rotating — 5 backups (~2.5 MB max per bot) |
| `logs/runtime/` | 30 days — `scripts/prune_logs.py --days 30` |
| `logs/bots/drishti/nifty_ltp/` | 30 days manual or extend prune script |
| `logs/archive/ocr/` | Delete when no longer needed |

---

## One-time log migration

If you still have flat files under `logs/` root:

```powershell
.venv\Scripts\python.exe scripts/migrate_logs_layout.py
```

---

## Future VPS

- Point log root at same layout under project directory
- Schedule weekly `prune_logs.py` via Task Scheduler
- Optional: ship `logs/runtime/` to external storage for long history

---

*See also `LOGGING_LAYOUT.md`, `telegram/design/logging_design.md`.*

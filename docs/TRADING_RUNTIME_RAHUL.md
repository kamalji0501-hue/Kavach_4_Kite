# Trading_Runtime_Rahul — isolation detail

**Updated:** 2026-08-06 13:35 IST  
**Host:** KamaljiAlgo (`13.126.134.192`)

## Why this exists

Rahul’s architecture work runs the **same Kamalji-baseline code** in `rahul_Changes`.  
Sharing `/home/ubuntu/Trading_Runtime` would mix Kamalji’s live logs, state, deployments, and Telegram/broker side effects.  
Hence a dedicated runtime umbrella: `/home/ubuntu/Trading_Runtime_Rahul`.

## Layout (same names as Kamalji runtime — not Year/Month/Date)

```text
/home/ubuntu/Trading_Runtime_Rahul/
├── Credentials/     # seeded once from Kamalji Trading_Runtime/Credentials
├── Logs/            # fresh — Logs/{uat|prod}/runtime/YYYY-MM/YYYY-MM-DD/{bot}/
├── Data/            # fresh — Data/data/{mode}/...
├── Backups/ Health/ Temp/ Cache/ Screenshots/ Exports/ Database/ Config/ User/
```

## Wired from

| File | Points to |
|------|-----------|
| `config/local_runtime.json` | Rahul runtime roots |
| `kavach-2.0/config/local_runtime.json` | same |
| `config/batman_mode.json` path keys | retargeted to Rahul |
| `kavach-2.0/config/batman_mode.json` path keys | retargeted to Rahul |

Kamalji live `/home/ubuntu/batman-algo/config/local_runtime.json` still uses `/home/ubuntu/Trading_Runtime`.

## Rollback

1. Stop sandbox bots.  
2. Set sandbox path keys back to `/home/ubuntu/Trading_Runtime/...`.  
3. Optionally archive/remove `Trading_Runtime_Rahul`.

## Related

- Audit: `docs/RUNTIME_AUDIT_20260806.txt`  
- Context: `../runtime_context.md`  
- Direction: `docs/PROJECT_DIRECTION.md`

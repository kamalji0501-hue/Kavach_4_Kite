# Session handoff — current (Rahul architecture track)

**Updated:** 2026-08-06 ~14:45 IST  
**Host:** Kamalji EC2 only · `13.126.134.192` (KamaljiAlgo)  

**Full day context (read this):** [`SESSION_CONTEXT_2026-08-06_FULL.md`](SESSION_CONTEXT_2026-08-06_FULL.md)

## Paths (locked — siblings)

| Role | Path |
|------|------|
| **Rahul code** | `/home/ubuntu/rahul_Changes` (~29 MB excl. `.venv`) |
| **Rahul runtime** | `/home/ubuntu/Trading_Runtime_Rahul` (~895 MB) |
| **Kamalji Batman** | `/home/ubuntu/batman-algo` → `/home/ubuntu/Trading_Runtime` |
| **Place Order VPS** | `/home/ubuntu/place-order-bot` |
| **Drive package** | `H:\RK Data\Algo Trading Parent\Market Order Algo from VPS 31 July 26 8.27 PM` |
| **Merge docs** | `Future Plan/place_order_merge/` |

## Perspective

Kamalji Batman = functional baseline. Rahul improves architecture in `rahul_Changes`.  
Place Order = **backend punch library** (not a Telegram Q&A bot). ATO engage → OrderManager → paper chase today; live later.

## Done today (high level)

1. Code vs desktop split + verification vs `batman-algo`  
2. Telegram `bots.env` + smoke (4 bots)  
3. Place Order clean Drive package + merge bible  
4. `backend_workflow` + `OrderManager` + ATO/`run_kavach` paper wire — tested  

## Next

1. Register Paper vs Live question + paper position book  
2. Live ExecutionEngine behind checklist  
3. Dhan whitelist `13.126.134.192`  

**Hold:** git push · LIVE money · GO out of scope  

## Quick smoke

```bash
cd /home/ubuntu/rahul_Changes && .venv/bin/python scripts/smoke_telegram_bots.py
cd /home/ubuntu/place-order-bot && .venv/bin/python -m pytest -q tests/test_backend_workflow.py
```

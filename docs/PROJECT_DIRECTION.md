> **2026-08-06:** Rahul restructuring complete. **Kamalji owns day-forward work** on `rahul_Changes`. See `context/KAMALJI_HANDOFF.md`.

# Project direction — Rahul Changes track

**Updated:** 2026-08-06 13:35 IST

## North star

Ship a production-ready **Algo** platform: Kamalji’s proven Batman behaviour + Rahul’s engineering (runtime hygiene, Order Manager, live fills, deployability).

## How the two codebases relate

```text
Kamalji Batman (tested)
        │
        │  copy / baseline (already done)
        ▼
rahul_Changes  ──architecture──►  Trading_Runtime_Rahul
        │
        │  integrate execution (Place Order capability)
        ▼
Order Manager + Broker Adapter
        │
        ▼
paper → (later) live Dhan
        │
        ▼
kamalji branch UAT → main → deploy
```

**Place Order bot** remains a separate harness for reference and smoke tests. Its **order-placement behaviour** is absorbed into Batman; the standalone bot is not the long-term product.

## Architecture principles (active)

See also Future Plan `ARCHITECTURE_GUIDELINES.md`.

1. Strategy never calls Dhan directly.  
2. Separate code / config / credentials / runtime data.  
3. Paper and live share strategy; Order Manager switches mode.  
4. Restart-safe state; no duplicate orders.  
5. Deploy only from `main` when stable.

## What “improving architecture” means here

| Done | Next |
|------|------|
| Isolated `Trading_Runtime_Rahul` | Paper bot startup from sandbox |
| Docs / audit / context for agents | Execution interface map |
| Gold VPS harden on Kamalji EC2 | Incremental Place Order integration |
| Rejected log-tree redesign | Credentials/`.env` layout per Rahul |

## Explicit non-goals right now

- Rewriting Kamalji strategy math  
- GO bot  
- Customer Nuitka packaging  
- Merging entire Place Order tree into Batman as a dump  

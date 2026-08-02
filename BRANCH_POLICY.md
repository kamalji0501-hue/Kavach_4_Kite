# Branch policy — batman-algo

**Product / commercial track (later):** Algo — private Git for developers only; customers get compiled releases later (see Market Order Algo docs).  
**This repo:** internal source for Batman / Algo development.

## Roles

| Person | Role | GitHub branch |
|--------|------|----------------|
| **Rahul (RK)** | Software engineer — infrastructure, Lightsail, GitHub, licensing/subscription roadmap, architecture, white-coding / engineering | `rahul` → promote to `main` when stable |
| **Kamalji** | Trader / domain — algo functionality, strategy inputs, UAT/testing feedback | `kamalji` → promote to `main` when stable (via PR preferred) |

Rahul owns the repo and invite/collaborator access. Kamalji is **not** expected to manage infra or GitHub structure.

## Branches

| Branch | Purpose |
|--------|---------|
| **`main`** | Always the **stable, working** algo. What Lightsail / production-oriented runs should track. |
| **`kamalji`** | Intermediate / evolving work from Kamalji (functionality + testing). |
| **`rahul`** | Intermediate / evolving engineering work from Rahul (infra, structure, tooling). |

Do **not** push secrets, tokens, `.env`, ledgers, logs, or `Dependencies/` dumps (see Ops `03_SECRETS_AND_GITIGNORE.md`).

## Flow

```text
kamalji  ──PR/merge──┐
                     ├──►  main  (stable)  ──►  Lightsail / later Nuitka customers
rahul    ──PR/merge──┘
```

1. Develop on `kamalji` or `rahul`.  
2. When both agree it is stable → merge into **`main`** (PR recommended).  
3. Lightsail pulls **`main`**.  
4. Commercial packaging / license checks stay parked until Rahul reopens Algo phases.

## Naming note

Legacy branch `Batman-Algo-Kamalji` was retired (2026-08-02) in favor of `main` / `kamalji` / `rahul`.

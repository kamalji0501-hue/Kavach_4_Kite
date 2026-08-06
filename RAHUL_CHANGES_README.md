# rahul_Changes — now owned by Kamalji (2026-08-06)

> **Ownership transfer:** Rahul (architect) finished restructuring. **Kamalji** owns day-forward work.  
> **Cursor AI:** read `context/KAMALJI_HANDOFF.md` before any multi-file work.  
> **Branch:** `rahul` · **Runtime:** `/home/ubuntu/Trading_Runtime_Rahul` only.

# rahul_Changes — Rahul architecture track (Kamalji baseline)

> **Location (sibling, not inside Batman):** `/home/ubuntu/rahul_Changes`  
> **Runtime:** `/home/ubuntu/Trading_Runtime_Rahul`  
> **Kamalji Batman:** `/home/ubuntu/batman-algo` + `/home/ubuntu/Trading_Runtime`


**Updated:** 2026-08-06 13:35 IST  
**Host:** KamaljiAlgo · `13.126.134.192`  
**Code:** `/home/ubuntu/rahul_Changes`  
**Runtime:** `/home/ubuntu/Trading_Runtime_Rahul`

---

## Perspective (locked)

Kamalji developed and UAT-tested the **Batman** trading system (DRISHTI / KAVACH / JAGRAN / SARANSH) with live market data and dummy/shadow orders. That product behaviour is the **baseline we go forward with**.

This folder is **not** a throwaway fork. It is that same codebase, accommodated here so Rahul can:

1. Improve **architecture** (runtime separation, config/credentials layout, Order Manager layers).  
2. Integrate **Place Order** live-execution capability (replace dummy execution only).  
3. Run and validate in **paper** first, then live — without breaking Kamalji’s live tree.

| Tree | Owner | Runtime | Role |
|------|--------|---------|------|
| `/home/ubuntu/batman-algo` | Kamalji | `/home/ubuntu/Trading_Runtime` | Live/tested baseline — **do not casually modify** |
| `/home/ubuntu/rahul_Changes` | Rahul | `/home/ubuntu/Trading_Runtime_Rahul` | Architecture + integration + paper runs |

---

## Read first (agents)

1. This file (`RAHUL_CHANGES_README.md`)  
2. `NEW_CHAT_HANDOFF.md`  
3. `docs/PROJECT_DIRECTION.md`  
4. `runtime_context.md` + `docs/TRADING_RUNTIME_RAHUL.md`  
5. Windows SoT: `H:\RK Data\Algo Trading Parent\Future Plan\` especially `ARCHITECTURE_GUIDELINES.md` + `CURRENT_STATE.md`

---

## Scope

| In scope | Out of scope (for now) |
|----------|-------------------------|
| DRISHTI, KAVACH, JAGRAN, SARANSH | GO bot |
| Paper mode runs from this sandbox | Live money until explicit authorize |
| Runtime isolation (done) | ChatGPT Year/Month/Date log redesign |
| Place Order execution integration (next) | Nuitka / license / customer package |
| Architecture layers: Strategy → Order Manager → Broker Adapter → Dhan | Copy-merging whole Place Order repo |

---

## Git

- Target branch when pushing: **`rahul`**  
- Flow later: `rahul` → `kamalji` (Kamalji validates) → `main` (deploy)  
- **Hold push** until Rahul says more integration is ready  
- Parent repo gitignores `rahul_Changes/`

---

## Hard rules

1. Preserve Kamalji strategy / trading behaviour unless Rahul explicitly asks to change it.  
2. Never point this sandbox at Kamalji’s `Trading_Runtime` again.  
3. Never commit secrets, tokens, logs, instrument dumps.  
4. Do not recreate `.venv` or upgrade packages unless asked.  
5. Do not run the enterprise “Desktop/Year/Month/Date” runtime prompt verbatim.

---

## Verification snapshot (2026-08-06T08:05Z)

- `config/local_runtime.json` → Trading_Runtime_Rahul  
- Kamalji `batman-algo/config/local_runtime.json` → Trading_Runtime (unchanged)  


## Latest session context (2026-08-06)

See `docs/SESSION_CONTEXT_2026-08-06_FULL.md`.

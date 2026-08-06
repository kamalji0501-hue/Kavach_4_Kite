# New Chat Handoff — Kamalji owns this track (2026-08-06)

> **OWNERSHIP:** Kamalji (+ Cursor AI). Rahul’s restructuring pass is **complete**.  
> **START HERE:** [`context/KAMALJI_HANDOFF.md`](context/KAMALJI_HANDOFF.md)  
> **Cursor guide:** [`context/CURSOR_AI_GUIDE_FOR_KAMALJI.md`](context/CURSOR_AI_GUIDE_FOR_KAMALJI.md)  
> **Code:** `/home/ubuntu/rahul_Changes` · **Runtime:** `/home/ubuntu/Trading_Runtime_Rahul` · **Branch:** `rahul`

<!-- RAHUL SANDBOX BANNER -->
> Work only in this tree + `Trading_Runtime_Rahul`. Do not mix with `/home/ubuntu/batman-algo` / `/home/ubuntu/Trading_Runtime` unless Kamalji explicitly asks.

---

## Quick status at handoff

| Item | State |
|------|--------|
| GitHub branch | `rahul` |
| Phase-1 bots | Drishti / Kavach2 / Jagran / Saransh (Rahul supervisor) |
| Paper/Live register | Shipped |
| Place Order backend sink | Shipped (paper OM; live broker path preserved) |
| PIN/TOTP capability | Shipped (optional; secrets_root) |
| Robot verify | Use `scripts/robot_verify_phase1.py` |

---

## Older session notes (historical)

The content below is older (backtest / July handoff). Prefer `context/KAMALJI_HANDOFF.md` for current ownership.

---

# New Chat Handoff — Rahul sandbox (read first)

**Updated:** 2026-08-06 13:35 IST  
**VPS:** `ubuntu@13.126.134.192` (KamaljiAlgo)  
**PEM:** `H:\RK Data\Algo Trading Parent\VPS Infra\AWS Key\Kamalji\Kamalji_EC_2.pem`  
**Work only in:** `/home/ubuntu/rahul_Changes`

---

## One paragraph

We keep **Kamalji’s Batman** as the functional baseline (tested with live data, dummy orders). Rahul’s track improves architecture and will integrate Place Order live execution into that baseline. All of that work happens in **`rahul_Changes`** with isolated runtime **`Trading_Runtime_Rahul`**. Paper now; live later. GO bot out of scope.

---

## Current status

| Item | State |
|------|--------|
| Runtime isolation | **Done** — `Trading_Runtime_Rahul` |
| Log layout | Keep `Logs/{uat\|prod}/runtime/YYYY-MM/YYYY-MM-DD/{bot}/` |
| Enterprise prompt Year/Month/Date | **Rejected** |
| Place Order on this VPS | Installed at `/home/ubuntu/place-order-bot` (stopped) |
| Four bots from sandbox | Not started yet (next when Rahul asks) |
| Git push to `rahul` | Hold until Rahul says |
| Dhan IP `13.126.134.192` | Whitelist when ready for live |

---

## Next work (when asked)

1. Paper-mode flow + start DRISHTI/KAVACH/JAGRAN/SARANSH from this sandbox.  
2. Map dummy/shadow execution → Order Manager.  
3. Integrate Place Order execution module (incremental; no full-repo copy).  
4. `.env` / credentials architecture (Rahul to explain).  

---

## Do not

- Edit `/home/ubuntu/batman-algo` (Kamalji live) unless explicitly asked.  
- Share `Trading_Runtime` between Kamalji and Rahul sandboxes.  
- Enable LIVE orders without explicit authorize.  
- Push to GitHub until Rahul approves.

---

## Deep docs

- `RAHUL_CHANGES_README.md`  
- `docs/PROJECT_DIRECTION.md`  
- `runtime_context.md`  
- `docs/TRADING_RUNTIME_RAHUL.md`  
- `docs/RUNTIME_AUDIT_20260806.txt`  
- Future Plan: `ARCHITECTURE_GUIDELINES.md`, `CURRENT_STATE.md`

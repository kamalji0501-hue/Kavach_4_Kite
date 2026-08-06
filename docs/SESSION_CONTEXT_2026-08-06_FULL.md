# Session context — 2026-08-06 (full day)

**Host:** Kamalji EC2 `13.126.134.192` (KamaljiAlgo)  
**Updated:** 2026-08-06 ~14:45 IST  
**Status:** Saved handoff — code lightening, Telegram desktop credentials, Place Order backend punch, merge package.

Use this file + `SESSION_HANDOFF_2026-08-06_NIGHT.md` + `place_order_merge/` when opening a new chat.

---

## 1. Paths (locked)

| Role | Path |
|------|------|
| Rahul code (sandbox) | `/home/ubuntu/rahul_Changes` |
| Rahul runtime (desktop) | `/home/ubuntu/Trading_Runtime_Rahul` |
| Kamalji Batman (baseline) | `/home/ubuntu/batman-algo` → `/home/ubuntu/Trading_Runtime` |
| Place Order (VPS) | `/home/ubuntu/place-order-bot` |
| Place Order Drive package | `H:\RK Data\Algo Trading Parent\Market Order Algo from VPS 31 July 26 8.27 PM` |
| Merge docs (Future Plan) | `H:\RK Data\Algo Trading Parent\Future Plan\place_order_merge\` |
| Architecture SoT | `Future Plan\ARCHITECTURE_GUIDELINES.md` |

Nested `batman-algo/rahul_Changes` was **removed**. Do not point Rahul at Kamalji’s `Trading_Runtime`.

---

## 2. Release / desktop split (done)

- Code tree lightened: dumps/caches/media → `Trading_Runtime_Rahul` (~29 MB code excl. `.venv` vs ~895 MB runtime).
- Symlinks: `Dependencies`, `security_id_list.csv`, `backtest_engine/cache` → runtime.
- Docs on VPS: `rahul_Changes/docs/RELEASE_PACKAGE.md`, `VERIFICATION_LIGHTEN_20260806.md`, `PATH_AND_RELEASE_LAYOUT.md`, `BASELINE_PARITY_20260806.md`.
- Logic vs Kamalji: **126/132** shared py identical; hot paths match; runners identical.

---

## 3. Telegram credentials (done)

- Consolidated file: `Trading_Runtime_Rahul/Credentials/telegram/bots.env`
- Loader prefers `bots.env` → per-bot token.env → repo legacy.
- Smoke: `cd /home/ubuntu/rahul_Changes && .venv/bin/python scripts/smoke_telegram_bots.py`
- Four phase-1 bots getMe + Application started: **PASS** (serial retest).
- Helper: `core/telegram_credentials.py`

---

## 4. Place Order = backend workflow (done — critical)

**Product rule:** Place Order Telegram bot was only a **test harness** for slippage/chase. In master product it must **not** ask users placement questions. When **ATO engages → punch in backend**.

| Piece | Location |
|-------|----------|
| Backend API | `place-order-bot/place_order_bot/backend_workflow.py` (`BackendOrderWorkflow.punch`) |
| Tests | `place-order-bot/tests/test_backend_workflow.py` (**4 passed** local + VPS) |
| Batman OrderManager | `rahul_Changes/core/order_manager.py` |
| ATO seam | `modules/ato_protection.py` → `_place_ato_aggressive_limit` uses `order_manager` if attached |
| Startup wire | `run_kavach2.py` → attaches **paper** OrderManager after ATO construct |
| Drive copy | same `backend_workflow.py` in package + `docs/BACKEND_NOT_A_BOT.md` |

**Verified:**

- Paper punch fills qty 65 via FakeBroker chase; no Telegram.
- With OM attached, legacy `place_aggressive_limit` / `place_market_order` **not** called.
- Without OM, legacy path still works.
- `ORDER_MODE=live` on OrderManager **blocked** until explicitly wired + authorized.

---

## 5. Handoff package for Google Drive / master team

Folder: `Market Order Algo from VPS 31 July 26 8.27 PM` (~1 MB clean; no `.venv`, logs, dumps, real secrets).

Read order:

1. `README_FOR_MASTER_TEAM.md`
2. `docs/BACKEND_NOT_A_BOT.md`
3. `docs/MERGE_WITH_MASTER_KAVACH.md`
4. `docs/PAPER_VS_LIVE_DESIGN.md`
5. `docs/KAVACH_HOOK_MAP.md`
6. `docs/CURSOR_PROMPT_MERGE_PLACE_ORDER_INTO_BATMAN.md`

Copies also under `Future Plan/place_order_merge/`.

---

## 6. Still open (next chats)

1. Kavach Register **first question**: Paper vs Live (persist `order_mode` on deployment).  
2. Paper **position book** for UI buttons (live quotes, no exchange).  
3. Live `ExecutionEngine` + real Dhan broker behind checklist / `LIVE_ORDERS`.  
4. Dhan whitelist Kamalji IP `13.126.134.192` (human).  
5. Git push `rahul` only when Rahul says.  
6. Do not disturb Kamalji live `batman-algo` casually.

---

## 7. Holds

- No git push until Rahul says  
- No live money until authorize  
- GO bot out of scope  
- Lightsail sacred unless asked  

---

## 8. Agent quick commands

```bash
cd /home/ubuntu/rahul_Changes && .venv/bin/python scripts/smoke_telegram_bots.py
cd /home/ubuntu/place-order-bot && .venv/bin/python -m pytest -q tests/test_backend_workflow.py
```

Architecture layers (mandatory):

```text
Telegram → Strategy → Order Manager → Broker Adapter → Dhan
```

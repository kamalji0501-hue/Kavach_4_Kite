# Kamalji ownership handoff — START HERE

**Date:** 2026-08-06  
**From:** Rahul (architect / restructuring)  
**To:** Kamalji (Algo / options-selling flow owner) + Cursor AI  
**Git branch:** `rahul` @ tip after this docs commit  
**Code folder:** `/home/ubuntu/rahul_Changes`  
**Runtime:** `/home/ubuntu/Trading_Runtime_Rahul`

> **Read this file first in every new Cursor chat on this tree.**  
> Rahul’s restructuring work on this track is **complete**. You own day-forward work here.

---

## 1. Who does what now

| Person | Role |
|--------|------|
| **Kamalji** | Product / options-selling flow / Telegram UX decisions / live ops judgment |
| **Cursor AI** | Code changes, tests, git, log reading, bot restart — under your direction |
| **Rahul** | Architect who finished Phase-1 restructuring; not the day-to-day owner of this folder anymore |

You do **not** need to be a Python expert. Tell Cursor what should happen in trading terms; ask it to change code, verify, and document.

---

## 2. Two trees on the same VPS (do not mix)

| Tree | Path | Runtime | Role |
|------|------|---------|------|
| **This track (you own going forward)** | `/home/ubuntu/rahul_Changes` | `/home/ubuntu/Trading_Runtime_Rahul` | Architecture + Paper/Live + Place Order sink + deep logs |
| **Your older baseline** | `/home/ubuntu/batman-algo` | `/home/ubuntu/Trading_Runtime` | Known-good Kamalji Batman — **recovery reference** |

**Hard rules for Cursor AI:**

1. Work only under `/home/ubuntu/rahul_Changes` unless you explicitly ask otherwise.  
2. Never write data/logs/secrets into Kamalji’s `/home/ubuntu/Trading_Runtime`.  
3. Never destroy `/home/ubuntu/batman-algo` or `/home/ubuntu/place-order-bot`.  
4. Lightsail is sacred — do not touch unless you explicitly order it.  
5. Never commit secrets, PEMs, `Credentials/`, live `.env`, or `access_token.json`.

---

## 3. What Rahul already finished (do not redo)

- Code light / runtime heavy layout (`Trading_Runtime_Rahul`)  
- Place Order as **backend punch** (not Telegram Q&A inside ATO)  
- Paper vs Live as **first** `/register` question  
- Money-safe audit JSONL + ATO NIFTY/CE/PE tick CSV  
- Robot verify + five-scenario hardening harness  
- Dhan **PIN/TOTP capability** structured like Telegram secrets (optional enable later)  
- GitHub `rahul` branch cleaned + handover commits  

Details: `docs/RAHUL_TO_KAMALJI_HANDOVER.md`, `docs/PROJECT_DIRECTION.md`, `context/MLG_DHAN_PIN_TOTP_INTEGRATION.md`.

---

## 4. How trading auth & orders work (mental model)

```text
Telegram (Kavach2 / Drishti / …)
    → Strategy (ATO etc.)
    → order_mode = paper | live   (chosen at Register)
         ├─ paper → Order Manager → FakeBroker / paper book (no exchange)
         └─ live  → existing broker punch path (preserved)
    → Dhan

Auth (JWT):
  TokenStore (daily JWT) ← DRISHTI paste and/or DHAN_ACCESS_TOKEN
  Optional later: PIN+TOTP from secrets_root → same TokenStore
```

**Paper first for money safety.** Live only when you whitelist and intend real punches.

---

## 5. Secrets map (desktop / runtime — outside git)

`secrets_root` = `/home/ubuntu/Trading_Runtime_Rahul/Credentials`

```text
Credentials/
  telegram/bots.env          ← Telegram bot tokens (all bots)
  config/.env                ← Dhan client + optional JWT (exists today)
  config/dhan.env            ← RECOMMENDED for PIN+TOTP when you enable it
  Tokens/
```

Templates in git (no secrets):

- `telegram/bots.env.example`  
- `config/dhan.env.example`  
- `config/.env.example`

Docs: `docs/TELEGRAM_CREDENTIALS.md`, `docs/DHAN_PIN_TOTP_AUTH.md`.

---

## 6. Bots on this track (Phase-1)

Typical running set (Rahul supervisor — **not** Kamalji systemd pointing at `batman-algo`):

| Bot | Script | Notes |
|-----|--------|-------|
| Drishti | `run_drishti.py` | Token / LTP |
| Kavach2 | `run_kavach2.py` | Main register / ATO Phase-1 |
| Jagran | `run_jagran.py` | |
| Saransh | `run_saransh.py` | |
| Classic Kavach | often stopped | Phase-1 uses Kavach2 |

Check:

```bash
cd /home/ubuntu/rahul_Changes
ps aux | grep -E 'run_kavach2|run_drishti|run_jagran|run_saransh' | grep -v grep
```

Restart via your usual supervisor / start scripts in this folder (ask Cursor to use Rahul supervisor, not Kamalji systemd, unless you intend to change that).

---

## 7. First commands for a new Cursor chat

```bash
cd /home/ubuntu/rahul_Changes
source .venv/bin/activate   # or: .venv/bin/python ...
git status -sb
git log -5 --oneline --decorate
.venv/bin/python scripts/smoke_dhan_pin_totp_capability.py
.venv/bin/python scripts/robot_verify_phase1.py
```

If robot verify is green, the Phase-1 execution/logging stack is healthy.

---

## 8. Where to look when something breaks

| Symptom | Look here |
|---------|-----------|
| Register / Paper-Live | `docs/PAPER_LIVE_REGISTER.md`, `bat_telegram/bots/kavach2/`, `core/order_mode.py` |
| Orders / paper punch | `core/order_manager.py`, `place-order-bot` on VPS (sibling), `docs/DETAILED_MONEY_LOGGING.md` |
| Tick CSV | `docs/ATO_NIFTY_TICK_CSV.md`, runtime `Data/.../ato_tick_csv/` |
| Audit JSONL | `Logs/.../audit/` under `Trading_Runtime_Rahul` |
| Telegram tokens | `docs/TELEGRAM_CREDENTIALS.md` |
| Dhan JWT / PIN-TOTP | `docs/DHAN_PIN_TOTP_AUTH.md`, `context/MLG_DHAN_PIN_TOTP_INTEGRATION.md` |
| Paths / sizes | `docs/PATH_AND_RELEASE_LAYOUT.md`, `docs/TRADING_RUNTIME_RAHUL_LAYOUT.md` |
| Tester checklist | `docs/EVIDENCE_CHECKLIST_TESTER.md` |

**Money-safe rule for Cursor:** prefer more logs / docs / wiring over rewriting ATO math unless you explicitly ask for strategy changes.

---

## 9. GitHub

- Repo: `rahulkrkhatwani-prog/batman-algo`  
- Branch: **`rahul`**  
- Do not force-push `main`.  
- Prefer small commits with clear messages.  
- Never commit Credentials or tokens.

---

## 10. Recovery if this tree breaks

1. Stop Rahul bots.  
2. Confirm Kamalji baseline still intact: `/home/ubuntu/batman-algo` + `/home/ubuntu/Trading_Runtime`.  
3. Ask Cursor to compare / restore from baseline **only** with your approval.  
4. Place Order backend lives at `/home/ubuntu/place-order-bot` (sibling — not inside this git tree).

---

## 11. Suggested next work for you (product, not architecture)

1. Paper Telegram testing with a friend (use evidence checklist).  
2. Decide when to fill `DHAN_PIN` / `DHAN_TOTP_SECRET` in secrets (optional efficiency).  
3. Live money only after your whitelist + checklist.  
4. Flow/design improvements in Kavach2 — Cursor implements; you approve behaviour.

---

## 12. Doc index for Cursor AI (priority order)

1. **This file** — `context/KAMALJI_HANDOFF.md`  
2. `RAHUL_CHANGES_README.md`  
3. `NEW_CHAT_HANDOFF.md`  
4. `docs/RAHUL_TO_KAMALJI_HANDOVER.md`  
5. `docs/PROJECT_DIRECTION.md`  
6. `AGENTS.md`  
7. Topic docs as needed (Paper/Live, credentials, PIN/TOTP, runtime layout)

Thank you note from Rahul: restructuring on this track is done — build the Algo flow forward from here.

## Flow parity vs batman-algo

See `docs/FLOW_PARITY_VS_BATMAN_ALGO.md`. ATO breach/exit conditions match OLD; Paper/Live + Place Order backend are intentional. Kavach2 `/register` now asks Paper/Live first (same as root Kavach), then continues the classic wizard.

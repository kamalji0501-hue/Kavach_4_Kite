# Parked: Dhan → Zerodha / multi-broker (resume from here)

> **Status:** DECISION PENDING — user will think and command later. Do **not** implement until explicitly asked.  
> **Saved:** 2026-07-15 (chat session)  
> **Project:** DEV Batman Algo (Dhan-only today)

---

## What was discussed

1. User asked for broker choice (**Dhan + Zerodha**) and file/time estimates — **no code changes** for that estimate pass.
2. User then asked about **full dual-broker** agent time vs **switching completely to Zerodha**.
3. User decided to **think and decide later**; continue from this note when ready.

---

## Current state (readonly findings)

- Live broker is **Dhan only** (`core/broker.py` → Tradehull / `dhanhq`).
- `core/broker_factory.py` switches **UAT ShadowBroker vs live Dhan** — **not** Dhan vs Zerodha.
- **No** Zerodha / KiteConnect implementation exists.
- Auth today: Dhan JWT pasted via **DRISHTI** → `TokenStore` / `access_token.json`.
- Credentials: `DHAN_CLIENT_CODE`, `DHAN_ACCESS_TOKEN` in `config/.env` or `~/Batman-Secrets`.

---

## Options when user resumes

| Option | Scope | Est. files | Est. agent coding time |
|--------|--------|------------|-------------------------|
| **A. Dual broker + selector** | Keep Dhan, add Zerodha, UI/config to choose | ~45–60 full / ~25–30 MVP | ~12–20 hours coding; 2–4 calendar days with live verify |
| **B. Switch to Zerodha only** | Replace Dhan with Zerodha | similar core rewrite | ~10–16 hours coding; 1–2 calendar days with live verify |

Hard parts either way: Kite auth/token flow, instrument mapping (`securityId` → `instrument_token`), NIFTY LTP/WS parity, position field mapping.

### Blocked until user provides

- Zerodha API key / secret
- First successful access token / login flow
- Live smoke test (LTP, positions; orders when ready)
- Any IP whitelist needs on VPS

---

## Recommended resume command (for user)

When ready, say one of:

- `Implement Option A: Dhan + Zerodha with broker selector (full parity)`  
- `Implement Option A MVP: selector + auth + orders + positions + NIFTY LTP`  
- `Implement Option B: switch entirely from Dhan to Zerodha`

Do not start coding until that explicit command.

---

## Related chat themes (same session)

- BTC 15m chart read: short-term bias long, prefer pullback not chase; not financial advice.
- Career: prefer developer path; trading as controlled side experiment if desired.

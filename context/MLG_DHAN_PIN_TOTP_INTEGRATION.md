# MLG handoff — Dhan PIN/TOTP capability (Rahul track)

**Audience:** MLG (integrator)  
**Date:** 2026-08-06  
**Branch:** `rahul` · folder: `/home/ubuntu/rahul_Changes`  
**Intent:** Capability is in the tree and wired to the **desktop/runtime secrets root**.  
Telegram register/wizard flows were **not** redesigned — turn this on when ready.

---

## 1. Why this exists

Fetch Historical Data already authenticates Dhan with Tradehull:

```python
Tradehull(client_id, mode="pin_totp", pin=..., totp_secret=...)
```

That is more efficient for automation than pasting a daily JWT every morning.
Rahul Changes now has the **same capability**, structured like Telegram credentials
(secrets on disk outside git; code only reads them).

---

## 2. What was integrated (capability inventory)

| Piece | Path | Role |
|-------|------|------|
| Secrets loader | `core/dhan_credentials.py` | Maps `<secrets_root>/config/dhan.env` or `.env` → env |
| PIN/TOTP login | `core/dhan_pin_totp.py` | `pin_totp` login, JWT extract, env helpers |
| Broker factory | `core/broker.py` → `connect_with_pin_totp` | Same for `kavach-2.0/core/broker.py` |
| DRISHTI seed (optional) | `run_drishti.py` | If JWT missing/expired and PIN/TOTP ready → seed TokenStore |
| Orchestrator fallback | `main.py` | If no JWT, try PIN/TOTP before stub broker |
| Refresh CLI | `scripts/refresh_dhan_token_pin_totp.py` | Manual JWT refresh |
| Capability smoke | `scripts/smoke_dhan_pin_totp_capability.py` | Paths/keys status, **no live login** |
| Unit tests | `tests/test_dhan_pin_totp.py` | Mocked Tradehull; no secrets |
| Docs | `docs/DHAN_PIN_TOTP_AUTH.md` | Operator-facing |
| Example (no secrets) | `config/dhan.env.example` | Copy into secrets_root |

**Not changed:** Kavach/Drishti Telegram conversation UX, register wizard questions,
Paper/Live flows, ATO strategy logic.

---

## 3. Credentials layout (must match Telegram pattern)

```text
<secrets_root>/
  telegram/
    bots.env                 # Telegram bot tokens (existing)
  config/
    dhan.env                 # RECOMMENDED — Dhan only
    .env                     # ALSO OK — legacy combined Dhan file
  Tokens/                    # existing
```

### Rahul VPS

`secrets_root` from `config/local_runtime.json`:

`/home/ubuntu/Trading_Runtime_Rahul/Credentials`

So Dhan file should be:

`/home/ubuntu/Trading_Runtime_Rahul/Credentials/config/dhan.env`  
(or keep using `.../config/.env`)

### Desktop (default when secrets_root not overridden)

`%USERPROFILE%\Desktop\Batman-Secrets\config\dhan.env`

### Example contents (placeholders only in git)

See `config/dhan.env.example`:

```env
DHAN_CLIENT_CODE=
DHAN_PIN=
DHAN_TOTP_SECRET=
# DHAN_ACCESS_TOKEN=   # optional
```

`DHAN_TOTP_SECRET` = Base32 **seed** from Dhan TOTP setup, **not** the rotating 6-digit code.

---

## 4. How MLG should integrate later (safe sequence)

1. **Copy template** → secrets_root `config/dhan.env` and fill real values (never commit).
2. **Smoke structure** (no network login):

   ```bash
   cd /home/ubuntu/rahul_Changes
   .venv/bin/python scripts/smoke_dhan_pin_totp_capability.py
   ```

   Expect `pin_totp_ready=True` when client+pin+totp are set.

3. **Optional live refresh** (calls Dhan once; writes JWT only to TokenStore):

   ```bash
   .venv/bin/python scripts/refresh_dhan_token_pin_totp.py
   ```

4. **Keep Telegram JWT path** as fallback — DRISHTI paste still works if PIN/TOTP unset.
5. **Do not** put Telegram tokens into `dhan.env`; keep `telegram/bots.env`.
6. When ready for product default: decide whether Drishti should prefer PIN/TOTP
   over manual JWT (code already seeds when JWT missing — policy choice only).

---

## 5. Runtime behaviour today

```text
TokenStore has valid JWT? ──yes──► use access_token (unchanged)
         │
         no
         ▼
DHAN_ACCESS_TOKEN in secrets? ──yes──► seed TokenStore
         │
         no
         ▼
PIN+TOTP in secrets_root? ──yes──► pin_totp → JWT → TokenStore
         │
         no
         ▼
wait for DRISHTI Telegram JWT (unchanged UX)
```

---

## 6. Verification already done on Rahul track

- Unit tests: `tests/test_dhan_pin_totp.py`
- Phase-1 robot verify still green after capability add
- No secrets in git (PIN/TOTP/JWT gitignored via secrets_root / `.env` rules)

Suggested MLG check after filling secrets:

```bash
.venv/bin/python -m pytest -q tests/test_dhan_pin_totp.py
.venv/bin/python scripts/smoke_dhan_pin_totp_capability.py
.venv/bin/python scripts/robot_verify_phase1.py
```

---

## 7. Source reference (Fetch Historical Data)

- `historical/fetch.py` → `load_tradehull` uses `mode="pin_totp"`
- `config/config.py` → requires `DHAN_PIN` + `DHAN_TOTP_SECRET` from env
- `tests/unit/test_totp_auth.py` → asserts pin_totp-only Tradehull call

Rahul port keeps **both** pin_totp and access_token (Batman still supports DRISHTI JWT).

---

## 8. Security rules for MLG

- Never commit `Credentials/`, `config/.env`, `dhan.env` with real values, or TokenStore JWT files.
- Never log PIN / TOTP seed / JWT (status helpers expose key names / booleans only).
- Clock sync matters for TOTP (NTP).
- Paper/Live order modes are separate from this auth capability.

---

## 9. One-line summary for MLG

> **Capability is in `rahul`:** read Dhan PIN/TOTP from the same desktop/runtime
> `secrets_root` as Telegram, obtain daily JWT via Tradehull `pin_totp`, keep
> Telegram UX unchanged until you choose to default to this path.

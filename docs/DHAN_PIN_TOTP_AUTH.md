# Dhan PIN / TOTP authentication (Rahul track)

**Source pattern:** Fetch Historical Data (`historical/fetch.py` → Tradehull `mode="pin_totp"`).

**Status:** Capability integrated in `rahul_Changes`. Telegram bot Q&A flows are **unchanged**.
MLG can flip this on later using secrets on the desktop/runtime — see
[`context/MLG_DHAN_PIN_TOTP_INTEGRATION.md`](../context/MLG_DHAN_PIN_TOTP_INTEGRATION.md).

## Secrets map (desktop / runtime — outside git)

Same idea as Telegram credentials:

| Kind | Path |
|------|------|
| Secrets root | `<secrets_root>` (Rahul VPS: `Trading_Runtime_Rahul/Credentials`) |
| Telegram bots | `<secrets_root>/telegram/bots.env` |
| Dhan (recommended) | `<secrets_root>/config/dhan.env` |
| Dhan (legacy OK) | `<secrets_root>/config/.env` |

Code helpers:

- `core/dhan_credentials.py` — load/status for Dhan secrets (no values logged)
- `core/dhan_pin_totp.py` — Tradehull `pin_totp` login + JWT extract
- `BatmanBroker.connect_with_pin_totp(...)` — broker factory
- `scripts/refresh_dhan_token_pin_totp.py` — optional JWT refresh
- `scripts/smoke_dhan_pin_totp_capability.py` — structure smoke (no live login)

Template (safe to commit): `config/dhan.env.example`

## Flow

```text
secrets_root/config/dhan.env  (DHAN_CLIENT_CODE + DHAN_PIN + DHAN_TOTP_SECRET)
        → apply_dhan_secrets_env()
        → Tradehull(mode="pin_totp")
        → daily JWT (token_id)
        → TokenStore (JWT only; never PIN/TOTP)
        → BatmanBroker / REST
```

Existing DRISHTI JWT paste / `DHAN_ACCESS_TOKEN` remains fully supported.

## Env keys

| Variable | Meaning |
|----------|---------|
| `DHAN_CLIENT_CODE` or `DHAN_CLIENT_ID` | Dhan client id |
| `DHAN_PIN` | Lifetime PIN |
| `DHAN_TOTP_SECRET` | Base32 TOTP **seed** (not 6-digit OTP) |
| `DHAN_ACCESS_TOKEN` | Optional manual JWT |

## Security

- Never commit PIN, TOTP seed, or live JWT.
- Modules never write PIN/TOTP to disk.
- Placeholders like `<ENTER_...>` are ignored.

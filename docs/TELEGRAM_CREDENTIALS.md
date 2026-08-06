# Telegram credentials (desktop / runtime)

## Idea

Code stays clean. **Each user’s bot tokens live on their machine** under the secrets root:

```
<secrets_root>/telegram/bots.env
```

On this VPS that is:

`/home/ubuntu/Trading_Runtime_Rahul/Credentials/telegram/bots.env`

## One file for all bots

```env
DRISHTI_BOT_TOKEN=...
DRISHTI_CHAT_ID=...
KAVACH_BOT_TOKEN=...
KAVACH_CHAT_ID=...
JAGRAN_BOT_TOKEN=...
JAGRAN_CHAT_ID=...
SARANSH_BOT_TOKEN=...
SARANSH_CHAT_ID=...
```

Template in the code tree (no secrets): `telegram/bots.env.example`

## Resolution order

1. `bots.env` (consolidated — preferred)
2. `<secrets_root>/telegram/bots/<name>/token.env`
3. Repo `telegram/bots/<name>/token.env` (legacy)
4. Process environment

## Smoke test

```bash
cd /home/ubuntu/rahul_Changes
.venv/bin/python scripts/smoke_telegram_bots.py
```

Reports which bots were **read successfully** and confirms Telegram `getMe` without starting polling.

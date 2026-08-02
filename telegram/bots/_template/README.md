# Telegram Bot Folder Template

Purpose: Standard scaffold for adding a new bot without writing runtime logic yet.

## Required files

1. __init__.py
2. token.env.example
3. params.json
4. config.json (deprecated stub that points to params.json)

## Notes

- Real secrets go in token.env (gitignored), not token.env.example.
- Add bot name to telegram/loader.py _KNOWN_BOTS after creating folder.
- Do not wire into main.py until design and mapping are validated.

"""
Batman v3 — Telegram subsystem.

Three dedicated bots, each fully isolated:

  DRISHTI (दृष्टि)  — infra health + access token management
  KAVACH  (कवच)    — core positions, ATO, deployment
  LAKSHMI (लक्ष्मी) — MTM alerts, profit targets, P&L

Each bot lives in telegram/bots/<name>/ and has TWO config files:
  token.env          — SECRETS ONLY  (BOT_TOKEN, CHAT_ID)  — gitignored
  token.env.example  — safe template to copy from          — committed
  params.json        — ALL tunable parameters              — committed

Quick import:

  from bat_telegram.loader import load_bot_config
    cfg = load_bot_config("drishti")
    cfg.params["retry"]["max_attempts"]   # access any parameter

    # Hot-reload after editing token.env (token update only):
    cfg = load_bot_config("drishti", reload_token=True)

    # Hot-reload after editing params.json (parameter tuning only):
    cfg = load_bot_config("drishti", reload_params=True)
"""

from bat_telegram.loader import load_bot_config

__all__ = ["load_bot_config"]

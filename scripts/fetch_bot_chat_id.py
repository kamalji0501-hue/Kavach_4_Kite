#!/usr/bin/env python3
"""Fetch Telegram chat ID from recent bot messages (getUpdates) and optionally update token.env."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bat_telegram.loader import load_bot_config
from telegram import Bot


def _chat_label(info: dict) -> str:
    if info.get("title"):
        return str(info["title"])
    parts = [info.get("first_name"), info.get("last_name")]
    name = " ".join(p for p in parts if p)
    if info.get("username"):
        return f"{name} (@{info['username']})".strip()
    return name or "unknown"


async def _fetch(bot_name: str) -> None:
    cfg = load_bot_config(bot_name, reload_token=True)
    bot = Bot(token=cfg.bot_token)
    me = await bot.get_me()
    updates = await bot.get_updates(limit=30, timeout=0)

    print(f"=== {bot_name.upper()} (@{me.username}) ===")
    print(f"Current token.env chat_id: {cfg.chat_id}")
    print(f"Recent updates: {len(updates)}")

    if not updates:
        print("\nNo updates found. Message the bot (/start) then run this script again.")
        return

    seen: dict[int, dict] = {}
    for u in reversed(updates):
        msg = u.message or u.edited_message
        if u.callback_query and u.callback_query.message:
            msg = u.callback_query.message
        if not msg:
            continue
        c = msg.chat
        seen[c.id] = {
            "id": c.id,
            "type": c.type,
            "title": c.title,
            "username": c.username,
            "first_name": c.first_name,
            "last_name": c.last_name,
            "last_text": (msg.text or "")[:120],
        }

    latest_id = list(seen.keys())[-1]
    group_ids = [cid for cid, info in seen.items() if info.get("type") in ("group", "supergroup")]
    suggested = group_ids[-1] if group_ids else latest_id
    for cid, info in seen.items():
        marker = " <-- suggested" if cid == suggested else ""
        print(f"\n  chat_id={cid}  type={info['type']}  label={_chat_label(info)}{marker}")
        if info.get("last_text"):
            print(f"    last: {info['last_text']!r}")

    print(f"\nSuggested chat_id: {suggested}")


def _update_token_env(bot_name: str, chat_id: str) -> None:
    env_path = ROOT / "telegram" / "bots" / bot_name / "token.env"
    if not env_path.exists():
        raise FileNotFoundError(env_path)
    text = env_path.read_text(encoding="utf-8")
    key = f"{bot_name.upper()}_CHAT_ID"
    if re.search(rf"^{re.escape(key)}=.*$", text, flags=re.MULTILINE):
        text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={chat_id}", text, flags=re.MULTILINE)
    else:
        text = text.rstrip() + f"\n{key}={chat_id}\n"
    env_path.write_text(text, encoding="utf-8")
    print(f"Updated {env_path} → {key}={chat_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch chat ID from Telegram getUpdates")
    parser.add_argument(
        "bot",
        choices=["drishti", "kavach", "jagran", "lakshmi", "saransh"],
        help="Bot name",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write suggested chat_id to token.env (uses most recent chat)",
    )
    args = parser.parse_args()

    async def run() -> None:
        await _fetch(args.bot)
        if args.write:
            cfg = load_bot_config(args.bot, reload_token=True)
            bot = Bot(token=cfg.bot_token)
            updates = await bot.get_updates(limit=30, timeout=0)
            group_chat = None
            private_chat = None
            for u in reversed(updates):
                msg = u.message or u.edited_message
                if u.callback_query and u.callback_query.message:
                    msg = u.callback_query.message
                if not msg:
                    continue
                cid = str(msg.chat.id)
                if msg.chat.type in ("group", "supergroup"):
                    group_chat = cid
                elif msg.chat.type == "private":
                    private_chat = cid
            latest_chat = group_chat or private_chat
            if latest_chat:
                _update_token_env(args.bot, latest_chat)
            else:
                print("Nothing to write — no messages found.")

    asyncio.run(run())


if __name__ == "__main__":
    main()

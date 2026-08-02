#!/usr/bin/env python3
"""Upload per-bot profile photos to Telegram (setMyProfilePhoto)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram import Bot, InputProfilePhotoStatic

from bat_telegram.alive_branding import find_brand_logo, prepare_logo_jpeg
from bat_telegram.loader import load_bot_config

DEFAULT_BOTS = ("drishti", "kavach2", "jagran")


async def _set_one(bot_name: str) -> bool:
    logo = find_brand_logo(bot_name)
    if logo is None:
        print(f"SKIP {bot_name.upper()}: no image under image/robot/")
        return False

    cfg = load_bot_config(bot_name)
    payload = prepare_logo_jpeg(logo)
    photo = InputProfilePhotoStatic(photo=payload)
    bot = Bot(cfg.bot_token)
    me = await bot.get_me()
    await bot.set_my_profile_photo(photo)
    print(f"OK {bot_name.upper()} (@{me.username}) ← {logo.name}")
    return True


async def _run(bot_names: tuple[str, ...]) -> int:
    ok = 0
    for name in bot_names:
        try:
            if await _set_one(name):
                ok += 1
        except Exception as exc:
            print(f"FAIL {name.upper()}: {exc}")
    print(f"Done — {ok}/{len(bot_names)} profile photos updated.")
    return 0 if ok == len(bot_names) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "bots",
        nargs="*",
        default=list(DEFAULT_BOTS),
        help=f"Bot names (default: {' '.join(DEFAULT_BOTS)})",
    )
    args = parser.parse_args()
    return asyncio.run(_run(tuple(args.bots)))


if __name__ == "__main__":
    raise SystemExit(main())

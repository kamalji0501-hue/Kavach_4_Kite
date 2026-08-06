#!/usr/bin/env python3
"""Phase 1 overnight bot/credential smoke check (no secrets printed)."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def mask(s: str, show: int = 6) -> str:
    if not s or "your_" in s.lower() or "here" in s.lower():
        return "(PLACEHOLDER or empty)"
    if len(s) <= show * 2:
        return "***"
    return f"{s[:show]}...{s[-4:]}"


def _token_env_path(name: str) -> Path:
    """Resolve credentials file for Phase 1 bots (desktop bots.env preferred)."""
    from core.batman_mode import secrets_bot_dir
    from core.telegram_credentials import secrets_telegram_bots_env_path

    candidates = [
        secrets_telegram_bots_env_path(ROOT),
        secrets_bot_dir(name, ROOT) / "token.env",
        ROOT / "telegram" / "bots" / name / "token.env",
    ]
    if name == "kavach2":
        candidates.insert(
            2, ROOT / "kavach-2.0" / "telegram" / "bots" / "kavach2" / "token.env"
        )
    return next((p for p in candidates if p.is_file()), candidates[0])


async def check_telegram_bot(name: str) -> dict:
    from bat_telegram.loader import load_bot_config
    from core.telegram_credentials import get_bot_credentials

    token_path = _token_env_path(name)
    tok, chat, src = get_bot_credentials(name, ROOT)
    out: dict = {"bot": name.upper(), "token_env": bool(tok), "source": src}
    if not tok:
        out["status"] = "MISSING credentials (bots.env / token.env)"
        return out

    try:
        cfg = load_bot_config(name, reload_token=True, reload_params=True)
    except Exception as exc:
        out["status"] = f"CONFIG FAIL: {exc}"
        return out

    placeholder = "your_" in cfg.bot_token.lower() or "here" in cfg.bot_token.lower()
    out["token"] = mask(cfg.bot_token)
    out["chat_id"] = mask(str(cfg.chat_id), 3)
    out["placeholder"] = placeholder

    if placeholder:
        out["status"] = "NOT CONFIGURED (placeholder values)"
        return out

    from telegram import Bot

    bot = Bot(token=cfg.bot_token)
    try:
        me = await bot.get_me()
        out["telegram"] = f"OK @{me.username}"
    except Exception as exc:
        out["status"] = f"TELEGRAM FAIL: {exc}"
        return out

    try:
        msg = await bot.send_message(
            chat_id=cfg.chat_id,
            text=f"[Batman dev check] {name.upper()} bot connectivity OK.",
        )
        out["send_test"] = f"OK message_id={msg.message_id}"
        out["status"] = "PASS"
    except Exception as exc:
        out["send_test"] = f"FAIL: {exc}"
        out["status"] = "TELEGRAM OK but send failed (check CHAT_ID?)"

    return out


async def send_drishti_health() -> dict:
    from bat_telegram.loader import load_bot_config
    from core.token_store import TokenStore
    from telegram import Bot

    cfg = load_bot_config("drishti", reload_token=True)
    from core.batman_mode import access_token_path, secrets_bot_dir

    store = TokenStore(path=access_token_path(ROOT))
    tok, saved_at = store.load()
    age_h = store.token_age_hours()
    expires_in = max(0.0, 24.0 - (age_h or 0))

    if tok and expires_in > 0:
        broker_status = "Connected"
    elif tok:
        broker_status = "Expired Token"
    else:
        broker_status = "No Token"

    now = datetime.now().strftime("%d-%b-%Y %H:%M:%S IST")
    lines = [
        "[Batman dev pre-check] DRISHTI health snapshot",
        "",
        f"Timestamp: {now}",
        f"Broker: {broker_status}",
    ]
    if age_h is not None:
        lines.extend(
            [
                f"Token age: {age_h:.1f} h",
                f"Token expires in: {expires_in:.1f} h",
            ]
        )
    if saved_at:
        lines.append(f"Token saved at: {saved_at.strftime('%d-%b %H:%M IST')}")

    dhan_line = "Dhan REST: not tested"
    if tok and tok.count(".") == 2:
        try:
            payload = tok.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            exp = datetime.fromtimestamp(claims.get("exp", 0), tz=UTC).astimezone()
            dhan_line = f"JWT exp: {exp.strftime('%d-%b-%Y %H:%M %Z')}"
        except Exception as exc:
            dhan_line = f"JWT decode error: {exc}"

        try:
            import httpx

            client_id = ""
            env_path = ROOT / "config" / ".env"
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("DHAN_CLIENT_CODE="):
                        client_id = line.split("=", 1)[1].strip().strip('"').strip("'")
            headers = {"access-token": tok, "Content-Type": "application/json"}
            if client_id:
                headers["client-id"] = client_id
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get("https://api.dhan.co/v2/fundlimit", headers=headers)
            if resp.status_code == 200:
                dhan_line += " | fundlimit: OK"
            else:
                dhan_line += f" | fundlimit: HTTP {resp.status_code}"
        except Exception as exc:
            dhan_line += f" | REST error: {exc}"

    lines.extend(
        [
            dhan_line,
            "",
            _ltp_cache_health_lines(),
        ]
    )
    text = "\n".join(lines)

    bot = Bot(token=cfg.bot_token)
    msg = await bot.send_message(chat_id=cfg.chat_id, text=text)
    return {"health_message_id": msg.message_id, "summary": text}


def _ltp_cache_health_lines() -> str:
    from core.nifty_ltp_feed import load_feed_config, read_nifty_ltp_cache

    cfg = load_feed_config()
    if cfg is None:
        return "LTP feed: not configured (auto-created on next token save)"

    snap = read_nifty_ltp_cache()
    if snap is None:
        return f"LTP feed: configured poll={cfg.poll_interval_seconds}s · cache empty"

    max_age = float(cfg.poll_interval_seconds * 3)
    fresh = snap.is_fresh(max_age)
    return (
        f"LTP feed: poll={cfg.poll_interval_seconds}s · "
        f"LTP={snap.ltp:,.2f} · age={snap.age_seconds():.0f}s · "
        f"healthy={'yes' if fresh and snap.feed_healthy else 'no'}"
    )


def _print_process_status() -> None:
    try:
        from core.bot_process_status import PHASE1_BOTS, BotRunState, classify_bot, format_status_line

        print("--- Bot process status (background) ---")
        for name in sorted(PHASE1_BOTS):
            status = classify_bot(name, root=ROOT)
            print(format_status_line(status))
            if status.state is BotRunState.ORPHAN:
                print("  >>> Run stop .bat before trusting STOPPED")
        print()
    except Exception as exc:
        print(f"  process status unavailable: {exc}\n")


async def main() -> None:
    print("=== Phase 1 bot credential check ===\n")
    _print_process_status()
    for name in ("drishti", "kavach2", "jagran", "saransh"):
        result = await check_telegram_bot(name)
        print(f"--- {result['bot']} ---")
        for key, val in result.items():
            if key != "bot":
                print(f"  {key}: {val}")
        print()

    drishti = await check_telegram_bot("drishti")
    if drishti.get("status") == "PASS":
        print("--- DRISHTI health report ---")
        health = await send_drishti_health()
        print(f"  message_id: {health['health_message_id']}")
        print(health["summary"])
        print()


if __name__ == "__main__":
    asyncio.run(main())

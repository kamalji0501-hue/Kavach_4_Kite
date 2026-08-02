#!/usr/bin/env python3
"""Audit token.env files — reports status without printing secrets."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _audit_bot(name: str) -> dict[str, str]:
    f = ROOT / "telegram" / "bots" / name / "token.env"
    prefix = name.upper()
    tk = f"{prefix}_BOT_TOKEN"
    ck = f"{prefix}_CHAT_ID"
    out: dict[str, str] = {"bot": name, "file": str(f), "token": "missing", "chat": "missing"}

    if not f.exists():
        out["file_status"] = "missing"
        return out

    vals = dotenv_values(f)
    token = (vals.get(tk) or "").strip()
    chat = (vals.get(ck) or "").strip()

    if token and not token.startswith("your_") and "token_here" not in token:
        out["token"] = f"ok ({len(token)} chars)"
    elif token:
        out["token"] = "placeholder"

    if chat and not chat.startswith("your_") and "chat_id" not in chat.lower():
        out["chat"] = f"ok ({len(chat)} chars)"
    elif chat:
        out["chat"] = "placeholder"

    return out


def main() -> int:
    print("Bot token audit (secrets not shown)\n")
    ok = True
    for name in ("drishti", "kavach", "jagran", "saransh"):
        r = _audit_bot(name)
        print(f"{r['bot'].upper()}:")
        print(f"  file:   {r['file']}")
        if r.get("file_status") == "missing":
            print("  status: FILE MISSING")
            ok = False
            continue
        print(f"  token:  {r['token']}")
        print(f"  chat:   {r['chat']}")
        if r["token"] != "ok" or not r["chat"].startswith("ok"):
            if "placeholder" in r["token"] or "placeholder" in r["chat"] or r["token"] == "missing":
                ok = False
        print()

    # config/.env for Dhan
    env = ROOT / "config" / ".env"
    print("config/.env (Dhan):")
    if env.exists():
        vals = dotenv_values(env)
        cc = (vals.get("DHAN_CLIENT_CODE") or "").strip()
        print(f"  DHAN_CLIENT_CODE: {'ok' if cc and '<ENTER' not in cc else 'missing/placeholder'}")
        if not cc or "<ENTER" in cc:
            ok = False
    else:
        print("  MISSING")
        ok = False

    print()
    if ok:
        print("All checks passed.")
        return 0
    print("Some credentials need attention.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

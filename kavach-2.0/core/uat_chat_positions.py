"""UAT positions from Cursor chat (agent reads Sensibull screenshot — no OCR)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from core.uat_positions import positions_json_path

logger = logging.getLogger("batman.uat_chat_positions")

SOURCE_CURSOR_CHAT = "cursor_chat"

# Optional role_hint values (non-unique for buys — operator picks Core BUY in Register).
_ALLOWED_ROLE_HINTS = frozenset({"pe_sell", "pe_buy", "ce_buy", "ce_sell"})
_ROLE_TYPE_SIDE = {
    "pe_sell": ("PE", "SELL"),
    "pe_buy": ("PE", "BUY"),
    "ce_buy": ("CE", "BUY"),
    "ce_sell": ("CE", "SELL"),
}

EXPECTED_LEG_COUNT = 8
EXPECTED_BUY_COUNT = 6
EXPECTED_SELL_COUNT = 2


class UATChatPositionsError(Exception):
    """Invalid or incomplete positions fixture."""


def _infer_spot(legs: list[dict[str, Any]] | None = None) -> float:
    stub = {"legs": legs or [], "spot_at_capture": 0}
    from core.nifty_option_expiry import infer_spot_from_fixture

    return infer_spot_from_fixture(stub)


def validate_fixture(data: dict[str, Any]) -> None:
    """Validate UAT chat book: 8 legs = 6 BUY + 2 SELL (1 PE SELL + 1 CE SELL).

    Core PE/CE BUY are **not** pre-marked — Register shows all BUY candidates
    and the operator chooses. ``role_hint`` is optional and may repeat for buys.
    """
    legs = data.get("legs")
    if not isinstance(legs, list) or len(legs) != EXPECTED_LEG_COUNT:
        raise UATChatPositionsError(
            f"Fixture must have exactly {EXPECTED_LEG_COUNT} legs "
            f"(6 BUY + 2 SELL), got {len(legs) if isinstance(legs, list) else type(legs).__name__}"
        )

    buy_n = sell_n = 0
    pe_sell = ce_sell = pe_buy = ce_buy = 0

    for i, leg in enumerate(legs):
        if not isinstance(leg, dict):
            raise UATChatPositionsError(f"Each leg must be an object (index {i})")

        opt = str(leg.get("type", "")).upper().strip()
        side = str(leg.get("side", "")).upper().strip()
        if opt not in ("PE", "CE"):
            raise UATChatPositionsError(f"Leg {i}: type must be PE or CE, got {leg.get('type')!r}")
        if side not in ("BUY", "SELL"):
            raise UATChatPositionsError(f"Leg {i}: side must be BUY or SELL, got {leg.get('side')!r}")

        role = str(leg.get("role_hint", "")).strip()
        if role:
            if role not in _ALLOWED_ROLE_HINTS:
                raise UATChatPositionsError(f"Unknown role_hint: {role!r}")
            expected_opt, expected_side = _ROLE_TYPE_SIDE[role]
            if opt != expected_opt or side != expected_side:
                raise UATChatPositionsError(
                    f"Leg {role} must be {expected_opt} {expected_side}, got {opt} {side}"
                )

        try:
            strike = int(leg["strike"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UATChatPositionsError(f"Leg {i}: invalid strike") from exc
        if not (10000 <= strike <= 80000):
            raise UATChatPositionsError(f"Strike out of NIFTY range: {strike}")

        try:
            lots = int(leg["lots"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UATChatPositionsError(f"Leg {i}: invalid lots") from exc
        if lots < 1:
            raise UATChatPositionsError(f"Invalid lots for leg {i}: {lots}")

        try:
            price = float(leg["avg_price"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UATChatPositionsError(f"Leg {i}: invalid avg_price") from exc
        if price <= 0:
            raise UATChatPositionsError(f"Invalid avg_price for leg {i}: {price}")

        if side == "BUY":
            buy_n += 1
            if opt == "PE":
                pe_buy += 1
            else:
                ce_buy += 1
        else:
            sell_n += 1
            if opt == "PE":
                pe_sell += 1
            else:
                ce_sell += 1

    if buy_n != EXPECTED_BUY_COUNT or sell_n != EXPECTED_SELL_COUNT:
        raise UATChatPositionsError(
            f"Fixture must have {EXPECTED_BUY_COUNT} BUY + {EXPECTED_SELL_COUNT} SELL, "
            f"got BUY={buy_n} SELL={sell_n}"
        )
    if pe_sell != 1 or ce_sell != 1:
        raise UATChatPositionsError(
            f"Fixture must have exactly 1 PE SELL and 1 CE SELL, "
            f"got PE_SELL={pe_sell} CE_SELL={ce_sell}"
        )
    if pe_buy < 1 or ce_buy < 1:
        raise UATChatPositionsError(
            f"Fixture must have at least 1 PE BUY and 1 CE BUY candidate, "
            f"got PE_BUY={pe_buy} CE_BUY={ce_buy}"
        )

    expiry = str(data.get("expiry_date", "")).strip()
    if len(expiry) != 10 or expiry[4] != "-":
        raise UATChatPositionsError(f"expiry_date must be ISO YYYY-MM-DD, got {expiry!r}")


def build_fixture(
    *,
    expiry_date: str,
    legs: list[dict[str, Any]],
    spot_at_capture: float | None = None,
    source_image: str = "cursor-chat",
    underlying: str = "NIFTY",
) -> dict[str, Any]:
    """Build a validated positions.json dict (8-leg UAT book: 6 BUY + 2 SELL)."""
    from core.nifty_option_expiry import expiry_label_from_date, parse_expiry_label

    exp = parse_expiry_label(expiry_date)
    expiry_iso = exp.isoformat()
    spot = spot_at_capture if spot_at_capture and spot_at_capture > 0 else _infer_spot(legs)
    fixture: dict[str, Any] = {
        "source": SOURCE_CURSOR_CHAT,
        "source_image": source_image,
        "underlying": underlying,
        "spot_at_capture": round(float(spot), 2) if spot and spot > 0 else 0.0,
        "expiry_label": expiry_label_from_date(exp),
        "expiry_date": expiry_iso,
        "captured_at": datetime.now().astimezone().isoformat(),
        "legs": legs,
    }
    validate_fixture(fixture)
    return fixture


def write_positions_json(
    fixture: dict[str, Any],
    root: Path | None = None,
) -> Path:
    validate_fixture(fixture)
    out = positions_json_path(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(fixture, fh, indent=2)
        fh.write("\n")
    logger.info("UAT cursor_chat positions.json written (%s)", out)
    return out


def load_positions_json(root: Path | None = None) -> dict[str, Any] | None:
    path = positions_json_path(root)
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return None
    return data


def is_cursor_chat_positions(data: dict[str, Any]) -> bool:
    return data.get("source") == SOURCE_CURSOR_CHAT


def is_valid_positions_file(root: Path | None = None) -> bool:
    data = load_positions_json(root)
    if not data:
        return False
    try:
        validate_fixture(data)
        return True
    except UATChatPositionsError:
        return False

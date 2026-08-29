"""Expiry payoff curve from cached broker positions + NIFTY spot.

Read-only. No option chain, no extra broker WS/REST.
"""

from __future__ import annotations

import re
from typing import Any

_SYM_RE = re.compile(
    r"NIFTY.*?(\d{4,6}).*?(CE|PE)\b",
    re.IGNORECASE,
)
_SYM_RE2 = re.compile(
    r"NIFTY[^0-9]*(\d{5,6})(CE|PE)\s*$",
    re.IGNORECASE,
)
_SYM_DASH = re.compile(
    r"NIFTY[- ].*?[- ](\d{4,6})[- ](CE|PE)\b",
    re.IGNORECASE,
)


def parse_nifty_option(symbol: str) -> tuple[int, str] | None:
    """Parse Zerodha-style NIFTY option symbols.

    Examples:
      NIFTY26AUG24900CE
      NIFTY26N0324500CE
      NIFTY-Aug2026-24900-CE
    """
    s = str(symbol or "").strip().upper().replace(" ", "")
    if not s or "NIFTY" not in s:
        return None
    if s.endswith("CE"):
        opt = "CE"
        body = s[:-2]
    elif s.endswith("PE"):
        opt = "PE"
        body = s[:-2]
    else:
        return None

    # Prefer trailing 5-digit strike (common NIFTY), else 4-6.
    m = re.search(r"(\d{5})$", body)
    if not m:
        m = re.search(r"(\d{4,6})$", body)
    if not m:
        # dashed forms already stripped CE/PE
        for rx in (_SYM_DASH, _SYM_RE2, _SYM_RE):
            mm = rx.search(s)
            if not mm:
                continue
            try:
                strike = int(mm.group(1))
            except (TypeError, ValueError):
                continue
            if 1000 <= strike <= 100000:
                return strike, opt
        return None
    try:
        strike = int(m.group(1))
    except (TypeError, ValueError):
        return None
    if 1000 <= strike <= 100000:
        return strike, opt
    return None


def _intrinsic(spot: float, strike: int, opt: str) -> float:
    if opt == "CE":
        return max(float(spot) - float(strike), 0.0)
    return max(float(strike) - float(spot), 0.0)


def _leg_pnl(spot: float, *, strike: int, opt: str, qty: float, avg: float) -> float:
    return (_intrinsic(spot, strike, opt) - float(avg)) * float(qty)


def build_payoff(
    positions: list[dict[str, Any]] | None,
    *,
    spot: float | None,
    step: int = 50,
    pad: int = 800,
) -> dict[str, Any]:
    legs_in: list[dict[str, Any]] = []
    for row in positions or []:
        if not isinstance(row, dict):
            continue
        qty = float(row.get("qty") or 0)
        if qty == 0:
            continue
        parsed = parse_nifty_option(str(row.get("symbol") or ""))
        if not parsed:
            continue
        strike, opt = parsed
        avg = float(row.get("avg") or 0)
        legs_in.append(
            {
                "symbol": str(row.get("symbol") or ""),
                "qty": qty,
                "avg": avg,
                "ltp": row.get("ltp"),
                "strike": strike,
                "option_type": opt,
                "side": "BUY" if qty > 0 else "SELL",
            }
        )

    if not legs_in:
        return {
            "ok": True,
            "spot": spot,
            "atm": None,
            "legs": [],
            "points": [],
            "breakevens": [],
            "max_profit": None,
            "max_loss": None,
            "strikes_each_side": 10,
            "text": "No NIFTY option legs in broker positions.",
        }

    # Chart window: ATM ± 10 NIFTY strikes (step 50), spot near center.
    side = 10
    if spot is not None and float(spot) > 0:
        atm = int(round(float(spot) / float(step)) * step)
    else:
        strikes = [int(l["strike"]) for l in legs_in]
        atm = int(round(sum(strikes) / len(strikes) / float(step)) * step)
    lo = int(atm - side * step)
    hi = int(atm + side * step)

    points: list[dict[str, float]] = []
    xs = list(range(int(lo), int(hi) + step, int(step)))
    for x in xs:
        y = 0.0
        for leg in legs_in:
            y += _leg_pnl(
                float(x),
                strike=int(leg["strike"]),
                opt=str(leg["option_type"]),
                qty=float(leg["qty"]),
                avg=float(leg["avg"] or 0),
            )
        points.append({"x": float(x), "y": round(y, 2)})

    breakevens: list[float] = []
    for i in range(1, len(points)):
        y0, y1 = points[i - 1]["y"], points[i]["y"]
        if y0 == 0:
            breakevens.append(points[i - 1]["x"])
        elif y0 * y1 < 0:
            x0, x1 = points[i - 1]["x"], points[i]["x"]
            # linear interpolate
            be = x0 + (0 - y0) * (x1 - x0) / (y1 - y0)
            breakevens.append(round(be, 1))

    ys = [p["y"] for p in points]
    return {
        "ok": True,
        "spot": float(spot) if spot else None,
        "atm": float(atm),
        "legs": legs_in,
        "points": points,
        "breakevens": breakevens[:6],
        "max_profit": max(ys) if ys else None,
        "max_loss": min(ys) if ys else None,
        "step": step,
        "strikes_each_side": side,
        "x_min": float(lo),
        "x_max": float(hi),
        "text": f"Expiry payoff · ATM {atm} · ±{side} strikes.",
    }


def payoff_snapshot() -> dict[str, Any]:
    from core.day_pnl_cache import cached_positions
    from web.arm import nifty_ltp

    spot = None
    try:
        px = nifty_ltp()
        if px is not None and float(px) > 0:
            spot = float(px)
    except Exception:
        spot = None
    return build_payoff(cached_positions() or [], spot=spot)

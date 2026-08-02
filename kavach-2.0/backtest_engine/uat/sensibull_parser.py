"""Parse Sensibull strategy-builder screenshots into UAT positions JSON."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_NIFTY_SPOT_RE = re.compile(r"(?:NIFTY|QNIFTY)\s*(\d{4,5}(?:\.\d+)?)", re.I)
_EXPIRY_RE = re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", re.I)
_STRIKE_RE = re.compile(r"\b(2\d{4})\b")
_PRICE_RE = re.compile(r"\b(\d{2,3}(?:\.\d{1,2})?)\b")
_MONTH_MAP = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


class SensibullParseError(Exception):
    """Screenshot could not be parsed into four legs."""


@dataclass
class ParsedLeg:
    side: str
    strike: int
    option_type: str
    lots: int
    avg_price: float


def _infer_expiry_iso(text: str) -> str:
    from core.nifty_option_expiry import parse_expiry_label

    m = _EXPIRY_RE.search(text)
    if not m:
        raise SensibullParseError("Could not find expiry (e.g. '16 Jun') in screenshot OCR text")
    try:
        return parse_expiry_label(m.group(0)).isoformat()
    except ValueError as exc:
        raise SensibullParseError(f"Invalid expiry in OCR: {m.group(0)!r}") from exc


def _infer_spot(text: str) -> float:
    m = _NIFTY_SPOT_RE.search(text.replace(",", ""))
    if m:
        return float(m.group(1))
    for token in _STRIKE_RE.findall(text):
        v = int(token)
        if 22000 <= v <= 26000 and "." in text:
            pass
    nums = [float(x) for x in re.findall(r"\b(2[12]\d{3}\.\d{2})\b", text)]
    if nums:
        return nums[0]
    raise SensibullParseError("Could not find NIFTY spot in screenshot")


def _extract_rows_from_ocr(ocr_lines: list[Any]) -> list[tuple[int, float]]:
    """Group OCR tokens by row (y) and pair strike + premium in the same row."""
    from tools.read_image_ocr import OcrLine

    rows: dict[int, list[tuple[float, str]]] = {}
    for line in ocr_lines:
        if not isinstance(line, OcrLine):
            continue
        _, cy = _center_xy(line.box)
        bucket = int(cy // 22)
        rows.setdefault(bucket, []).append((cy, line.text))

    pairs: list[tuple[int, float]] = []
    for bucket in sorted(rows.keys()):
        text = " ".join(t for _, t in sorted(rows[bucket]))
        strikes = [int(s) for s in _STRIKE_RE.findall(text) if 22000 <= int(s) <= 26000]
        prices = [
            float(p)
            for p in re.findall(r"\b(\d{1,3}(?:\.\d{1,2})?)\b", text)
            if 8 <= float(p) <= 250 and not (22000 <= float(p) <= 26000)
        ]
        if len(strikes) == 1 and len(prices) >= 1:
            pairs.append((strikes[0], max(prices)))
    return pairs


def _center_xy(box: list[list[float]]) -> tuple[float, float]:
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _discover_premiums(blob: str) -> list[float]:
    """Collect likely per-leg premiums from OCR text (wide range for Sensibull UI)."""
    found: list[float] = []
    for p in re.findall(r"\b(\d{1,3}(?:\.\d{1,2})?)\b", blob):
        try:
            v = float(p)
        except ValueError:
            continue
        if 8 <= v <= 250 and not (22000 <= v <= 26000):
            found.append(round(v, 2))
    return sorted(set(found), reverse=True)


def _premium_pool(blob: str) -> list[float]:
    return _discover_premiums(blob)


def _match_strike_premium(strike: int, blob: str, candidates: list[float], used: set[float]) -> float:
    best_price: float | None = None
    best_dist = 10**9
    for prem in candidates:
        if prem in used:
            continue
        prem_token = str(int(prem)) if prem == int(prem) else f"{prem:.2f}"
        for sm in re.finditer(str(strike), blob):
            for pm in re.finditer(prem_token.replace(".", r"\."), blob):
                dist = abs(sm.start() - pm.start())
                if dist < best_dist:
                    best_dist = dist
                    best_price = prem
    if best_price is None:
        for prem in candidates:
            if prem not in used:
                best_price = prem
                break
    if best_price is None:
        raise SensibullParseError(f"No premium match for strike {strike}")
    used.add(best_price)
    return best_price


def _price_near_strike(blob: str, strike: int, used: set[float]) -> float:
    window = 90
    local: list[float] = []
    for m in re.finditer(str(strike), blob):
        chunk = blob[max(0, m.start() - window) : m.end() + window]
        for p in re.findall(r"\b(\d{2,3}\.\d{1,2})\b", chunk):
            val = float(p)
            if 15 <= val <= 150 and val not in used:
                local.append(val)
    if local:
        pick = max(local)
        used.add(pick)
        return pick
    pool = [p for p in _premium_pool(blob) if p not in used]
    if not pool:
        raise SensibullParseError(f"Could not read option price near strike {strike}")
    pick = pool[0]
    used.add(pick)
    return pick


def _legs_from_row_pairs(ocr_lines: list[Any]) -> list[ParsedLeg]:
    """Prefer row-aligned strike+premium pairs from OCR layout."""
    pairs = _extract_rows_from_ocr(ocr_lines)
    if len(pairs) < 4:
        raise SensibullParseError(
            f"Need 4 strike/premium rows in screenshot, found {len(pairs)}: {pairs}"
        )
    ordered = sorted(pairs)[:4]
    pe_sell_k, pe_buy_k, ce_buy_k, ce_sell_k = (p[0] for p in ordered)
    pe_sell_p, pe_buy_p, ce_buy_p, ce_sell_p = (p[1] for p in ordered)
    return [
        ParsedLeg("SELL", pe_sell_k, "PE", 2, pe_sell_p),
        ParsedLeg("BUY", pe_buy_k, "PE", 1, pe_buy_p),
        ParsedLeg("BUY", ce_buy_k, "CE", 1, ce_buy_p),
        ParsedLeg("SELL", ce_sell_k, "CE", 2, ce_sell_p),
    ]


def _extract_leg_candidates(ocr_lines: list[Any]) -> list[ParsedLeg]:
    """Iron condor: four ascending NIFTY strikes with premiums → standard Batman roles."""
    text_blob = "\n".join(getattr(line, "text", str(line)) for line in ocr_lines)
    try:
        return _legs_from_row_pairs(ocr_lines)
    except SensibullParseError:
        pass

    strikes = sorted(set(int(s) for s in _STRIKE_RE.findall(text_blob) if 22000 <= int(s) <= 26000))
    if len(strikes) < 4:
        raise SensibullParseError(
            f"Need 4 option strikes in screenshot OCR, found {len(strikes)}: {strikes}"
        )
    strikes = strikes[:4] if len(strikes) > 4 else strikes
    used: set[float] = set()
    paired: list[tuple[int, float]] = []
    for s in strikes:
        try:
            paired.append((s, _match_strike_premium(s, text_blob, _discover_premiums(text_blob), used)))
        except SensibullParseError:
            paired.append((s, _price_near_strike(text_blob, s, used)))

    pe_sell_k, pe_buy_k, ce_buy_k, ce_sell_k = (p[0] for p in paired)
    pe_sell_p, pe_buy_p, ce_buy_p, ce_sell_p = (p[1] for p in paired)

    return [
        ParsedLeg("SELL", pe_sell_k, "PE", 2, pe_sell_p),
        ParsedLeg("BUY", pe_buy_k, "PE", 1, pe_buy_p),
        ParsedLeg("BUY", ce_buy_k, "CE", 1, ce_buy_p),
        ParsedLeg("SELL", ce_sell_k, "CE", 2, ce_sell_p),
    ]


def _strike_has_type(blob: str, strike: int, opt: str) -> bool:
    window = 80
    for m in re.finditer(str(strike), blob):
        start = max(0, m.start() - window)
        end = min(len(blob), m.end() + window)
        chunk = blob[start:end]
        if opt in chunk.upper():
            return True
    return False


def legs_to_fixture(
    legs: list[ParsedLeg],
    *,
    spot: float,
    expiry_date: str,
    source_image: str,
) -> dict[str, Any]:
    role_order = [
        ("pe_sell", "PE", "SELL"),
        ("pe_buy", "PE", "BUY"),
        ("ce_buy", "CE", "BUY"),
        ("ce_sell", "CE", "SELL"),
    ]
    out_legs = []
    for (role, opt, side), leg in zip(role_order, legs, strict=True):
        if leg.option_type != opt or leg.side != side:
            raise SensibullParseError(f"Leg order mismatch: expected {opt} {side}, got {leg}")
        out_legs.append(
            {
                "role_hint": role,
                "strike": leg.strike,
                "type": leg.option_type,
                "side": leg.side,
                "lots": leg.lots,
                "avg_price": round(leg.avg_price, 2),
            }
        )

    exp_label = datetime.fromisoformat(expiry_date).strftime("%d %b %Y")
    return {
        "source": "sensibull",
        "source_image": source_image,
        "underlying": "NIFTY",
        "spot_at_capture": round(spot, 2),
        "expiry_label": exp_label,
        "expiry_date": expiry_date,
        "captured_at": datetime.now().astimezone().isoformat(),
        "legs": out_legs,
    }


def parse_sensibull_image(image_path: Path) -> dict[str, Any]:
    """OCR image → positions fixture dict."""
    import sys

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from tools.read_image_ocr import run_ocr

    lines = run_ocr(str(image_path))
    if not lines:
        raise SensibullParseError(f"OCR returned no text for {image_path.name}")

    text_blob = "\n".join(line.text for line in lines)
    spot = _infer_spot(text_blob)
    expiry_date = _infer_expiry_iso(text_blob)
    parsed = _extract_leg_candidates(lines)
    return legs_to_fixture(
        parsed,
        spot=spot,
        expiry_date=expiry_date,
        source_image=image_path.name,
    )

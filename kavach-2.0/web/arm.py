"""Web Register / Deploy / Buffer helpers — same backend as Telegram, no second strategy."""

from __future__ import annotations

import json
import shutil
import logging
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from web.runtime import require_runtime

logger = logging.getLogger("batman.kavach.web.arm")

LOT_SIZE = 65
ATO_STEP = 50
RETRACE_DEFAULT_SENTINEL = 5


_KITE_NIFTY_QUOTE_GAP_S = 5.0
_last_kite_nifty_mono = 0.0


def _cache_ltp_if_fresh(max_age_s: float = 5.0) -> float | None:
    try:
        from core.nifty_ltp_feed import read_nifty_ltp_cache

        snap = read_nifty_ltp_cache()
        if snap is None or float(snap.ltp) <= 0:
            return None
        age = float(snap.age_seconds()) if hasattr(snap, "age_seconds") else 9999.0
        if age <= max_age_s:
            return float(snap.ltp)
    except Exception as exc:
        logger.warning("nifty_ltp cache read failed: %s", exc)
    return None


def _kite_nifty_quote() -> float | None:
    """Live NIFTY via existing Kite REST. Does not open a Dhan WebSocket."""
    import time as _time

    import httpx

    from core.zerodha_credentials import load_zerodha_order_creds

    global _last_kite_nifty_mono
    now = _time.monotonic()
    if now - _last_kite_nifty_mono < _KITE_NIFTY_QUOTE_GAP_S:
        return None
    creds = load_zerodha_order_creds()
    if not creds.ok:
        return None
    _last_kite_nifty_mono = now
    resp = httpx.get(
        "https://api.kite.trade/quote",
        params=[("i", "NSE:NIFTY 50")],
        headers={
            "X-Kite-Version": "3",
            "Authorization": f"token {creds.api_key}:{creds.access_token}",
        },
        timeout=8.0,
    )
    body = resp.json()
    if resp.status_code != 200 or body.get("status") != "success":
        logger.warning("Kite NIFTY quote failed: %s", (body.get("message") or resp.status_code))
        return None
    data = body.get("data") or {}
    row = data.get("NSE:NIFTY 50") or (next(iter(data.values()), {}) if data else {})
    last = (row or {}).get("last_price") if isinstance(row, dict) else None
    px = float(last) if last is not None else 0.0
    return px if px > 0 else None


def nifty_ltp() -> float | None:
    fresh = _cache_ltp_if_fresh(5.0)
    if fresh is not None:
        return fresh
    try:
        px = _kite_nifty_quote()
        if px is not None and px > 0:
            # Read-only fallback. Feeder keepalive writes the cache.
            return float(px)
    except Exception as exc:
        logger.warning("NIFTY kite fallback failed: %s", exc)
    try:
        from core.nifty_ltp_feed import read_nifty_ltp_cache

        snap = read_nifty_ltp_cache()
        if snap is not None and float(snap.ltp) > 0:
            return float(snap.ltp)
    except Exception as exc:
        logger.warning("nifty_ltp read failed: %s", exc)
    return None


def nifty_ltp_label() -> str:
    px = nifty_ltp()
    if px is None:
        return "—"
    return f"{px:,.2f}"


def round_nifty_50(px: float | None) -> int | None:
    if px is None:
        return None
    return int(round(float(px) / 50.0) * 50)


def _active_deployment() -> Path | None:
    try:
        from core.batman_mode import deployments_dir

        dep_dir = deployments_dir(require_runtime().root)
    except Exception:
        return None
    if not dep_dir.is_dir():
        return None
    files = sorted(
        [p for p in dep_dir.glob("batman_*.json") if p.parent.name != "archive"],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def _load_dep() -> dict[str, Any]:
    path = _active_deployment()
    if not path:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _persist_live_buffers_to_deployment(st: Any) -> None:
    """Keep Buffer Manager values across Kavach restart (restore reads this file)."""
    path = _active_deployment()
    if not path or st is None:
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    from core.buffer_config.schema import (
        BufferKind,
        legacy_int_from_buffer,
        normalize_buffer_field,
        serialize_buffer_field,
    )

    ato = data.setdefault("ato", {})
    pairs = (
        ("ce_entry_buffer_points", "ce_entry_buffer", "ce_entry_buffer_points"),
        ("pe_entry_buffer_points", "pe_entry_buffer", "pe_entry_buffer_points"),
        ("ce_retrace_points", "ce_retrace_buffer", "ce_retrace_points"),
        ("pe_retrace_points", "pe_retrace_buffer", "pe_retrace_points"),
    )
    for state_key, buf_key, pts_key in pairs:
        raw = st.get(f"ato.{state_key}")
        ato[buf_key] = serialize_buffer_field(
            normalize_buffer_field(raw), BufferKind.CUSTOM
        )
        ato[pts_key] = legacy_int_from_buffer(raw)
    if ato.get("ce_protect_symbol"):
        data["retrace_points"] = ato.get("ce_retrace_points", data.get("retrace_points"))
    else:
        data["retrace_points"] = ato.get("pe_retrace_points", data.get("retrace_points"))
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


def sell_strikes() -> tuple[int | None, int | None]:
    st = require_runtime().state
    if not st or not st.get("deployment.confirmed"):
        return None, None
    dep = _load_dep()
    positions = dep.get("positions") or {}

    def _strike(role: str, state_key: str) -> int | None:
        leg = positions.get(role) or (st.get(state_key) if st else None)
        if isinstance(leg, dict) and leg.get("strike"):
            try:
                return int(leg["strike"])
            except (TypeError, ValueError):
                return None
        return None

    return _strike("ce_sell", "positions.ce_sell"), _strike("pe_sell", "positions.pe_sell")


def buffer_form() -> dict[str, Any]:
    """UI values: entry and retrace as absolute NIFTY levels (blank if dummy retrace 5)."""
    from core.buffer_config.levels import nifty_level_from_buffer
    from core.buffer_config.schema import normalize_buffer_field

    st = require_runtime().state
    if not st or not st.get("deployment.confirmed"):
        return {
            "ok": True,
            "ce_entry": "",
            "pe_entry": "",
            "ce_retrace": "",
            "pe_retrace": "",
            "ce_entry_placeholder": "Nifty Level",
            "pe_entry_placeholder": "Nifty Level",
            "ce_retrace_placeholder": "Nifty Level",
            "pe_retrace_placeholder": "Nifty Level",
            "ce_sell_strike": None,
            "pe_sell_strike": None,
            "nifty_ltp": nifty_ltp(),
        }
    ce_strike, pe_strike = sell_strikes()
    ce_entry_off = normalize_buffer_field(st.get("ato.ce_entry_buffer_points", 0) if st else 0)
    pe_entry_off = normalize_buffer_field(st.get("ato.pe_entry_buffer_points", 0) if st else 0)
    ce_ret = normalize_buffer_field(st.get("ato.ce_retrace_points", 5) if st else 5)
    pe_ret = normalize_buffer_field(st.get("ato.pe_retrace_points", 5) if st else 5)

    def _level(offset: Decimal, side: str, strike: int | None, kind: str, *, hide_sentinel: bool = False) -> str:
        if strike is None:
            return ""
        if hide_sentinel and int(offset) == RETRACE_DEFAULT_SENTINEL:
            return ""
        lvl = nifty_level_from_buffer(offset, side=side, kind=kind, sell_strike=strike)
        return format(lvl.quantize(Decimal("1")), "f")

    return {
        "ok": True,
        "ce_entry": _level(ce_entry_off, "CE", ce_strike, "entry"),
        "pe_entry": _level(pe_entry_off, "PE", pe_strike, "entry"),
        "ce_retrace": _level(ce_ret, "CE", ce_strike, "exit", hide_sentinel=True),
        "pe_retrace": _level(pe_ret, "PE", pe_strike, "exit", hide_sentinel=True),
        "ce_entry_placeholder": "Nifty Level",
        "pe_entry_placeholder": "Nifty Level",
        "ce_retrace_placeholder": "Nifty Level",
        "pe_retrace_placeholder": "Nifty Level",
        "ce_sell_strike": ce_strike,
        "pe_sell_strike": pe_strike,
        "nifty_ltp": nifty_ltp(),
    }


def buffer_save(payload: dict[str, Any]) -> dict[str, Any]:
    from core.buffer_config.levels import buffer_from_nifty_level, looks_like_nifty_level
    from core.buffer_config.parser import parse_buffer_text

    st = require_runtime().state
    if not st:
        return {"ok": False, "error": "No state"}
    ce_strike, pe_strike = sell_strikes()

    def _parse_level(raw: Any, side: str, strike: int | None, *, kind: str, label: str) -> Decimal | None:
        text = str(raw or "").strip().replace(",", "")
        if not text:
            return None
        try:
            value = parse_buffer_text(text)
        except ValueError:
            raise ValueError(f"{label} must be a NIFTY level (e.g. 24200).") from None
        if not looks_like_nifty_level(value):
            raise ValueError(f"{label} must be a NIFTY level (e.g. 24200), not points.")
        if strike is None:
            raise ValueError(f"{label} needs a sell strike — Register Batman first.")
        return buffer_from_nifty_level(value, side=side, kind=kind, sell_strike=strike)

    try:
        ce_off = _parse_level(payload.get("ce_entry"), "CE", ce_strike, kind="entry", label="CE entry")
        pe_off = _parse_level(payload.get("pe_entry"), "PE", pe_strike, kind="entry", label="PE entry")
        ce_pts = _parse_level(payload.get("ce_retrace"), "CE", ce_strike, kind="exit", label="CE retrace")
        pe_pts = _parse_level(payload.get("pe_retrace"), "PE", pe_strike, kind="exit", label="PE retrace")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    # Thin safety: reject illegal same-side exit vs entry (desk UI also disables SAVE).
    from core.buffer_config.levels import nifty_level_from_buffer

    def _abs_level(offset, side: str, kind: str, strike: int | None):
        if offset is None or strike is None:
            return None
        return nifty_level_from_buffer(offset, side=side, kind=kind, sell_strike=strike)

    ce_entry_lvl = _abs_level(ce_off, "CE", "entry", ce_strike)
    ce_exit_lvl = _abs_level(ce_pts, "CE", "exit", ce_strike)
    pe_entry_lvl = _abs_level(pe_off, "PE", "entry", pe_strike)
    pe_exit_lvl = _abs_level(pe_pts, "PE", "exit", pe_strike)
    if ce_entry_lvl is not None and ce_exit_lvl is not None and not (ce_exit_lvl < ce_entry_lvl):
        return {"ok": False, "error": f"CE exit must be below CE entry (entry {ce_entry_lvl})."}
    if pe_entry_lvl is not None and pe_exit_lvl is not None and not (pe_exit_lvl > pe_entry_lvl):
        return {"ok": False, "error": f"PE exit must be above PE entry (entry {pe_entry_lvl})."}

    if ce_off is not None:
        st.set("ato.ce_entry_buffer_points", ce_off)
    if pe_off is not None:
        st.set("ato.pe_entry_buffer_points", pe_off)
    if ce_pts is not None:
        st.set("ato.ce_retrace_points", ce_pts)
    if pe_pts is not None:
        st.set("ato.pe_retrace_points", pe_pts)
    try:
        _persist_live_buffers_to_deployment(st)
    except Exception:
        pass
    out = buffer_form()
    out["text"] = "Buffer saved."
    return out


def poll_form() -> dict[str, Any]:
    st = require_runtime().state
    raw = st.get("ato.poll_interval_seconds") if st else None
    try:
        cur = int(raw) if raw is not None else 2
    except (TypeError, ValueError):
        cur = 2
    if cur not in [0, 1, 2, 3, 4, 5, 10, 15]:
        cur = 2
    return {
        "ok": True,
        "poll_interval": cur,
        "poll_options": [0, 1, 2, 3, 4, 5, 10, 15],
        "default": 2,
    }


def poll_save(payload: dict[str, Any]) -> dict[str, Any]:
    st = require_runtime().state
    if not st:
        return {"ok": False, "error": "No state"}
    raw = payload.get("poll_interval", 2)
    try:
        poll = 2 if raw is None or raw == "" else int(raw)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Poll interval must be a number of seconds."}
    if poll not in (0, 1, 2, 3, 4, 5, 10, 15):
        return {"ok": False, "error": "Poll interval must be 0, 1, 2, 3, 4, 5, 10, or 15 seconds."}
    st.set("ato.poll_interval_seconds", poll)
    path = _active_deployment()
    if path:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.setdefault("ato", {})["poll_interval_seconds"] = poll
            path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
        except Exception:
            pass
    out = poll_form()
    out["text"] = f"Poll interval saved: {poll}s"
    return out


def ato_combined() -> dict[str, Any]:
    rt = require_runtime()
    st = rt.state
    dep = _active_deployment()
    status_lines = []
    if not dep:
        msg = "No active deployment. Use Register Batman to arm Kavach."
        return {"ok": True, "status_text": msg, "positions_text": "", "text": msg}
    if st:
        status_lines += [
            f"CE protect : {st.get('ato.ce_protect_symbol') or 'N/A'}",
            f"PE protect : {st.get('ato.pe_protect_symbol') or 'N/A'}",
            f"Manage     : {st.get('ato.manage_sides', 'both')}",
        ]
    status_text = "\n".join(status_lines)
    return {
        "ok": True,
        "status_text": status_text,
        "positions_text": "",
        "text": status_text,
    }


def _lot_size() -> int:
    rt = require_runtime()
    broker = getattr(rt, "broker", None)
    broker_lot = None
    if broker:
        try:
            broker_lot = int(broker.get_lot_size("NIFTY"))
        except Exception:
            broker_lot = None
    try:
        from core.position_scope import resolve_nifty_lot_size

        return resolve_nifty_lot_size(config_lot_size=LOT_SIZE, broker_lot_size=broker_lot)
    except Exception:
        return LOT_SIZE


def _positions_from_uat_fixture() -> list[dict[str, Any]]:
    try:
        from core.batman_mode import workspace_root
        from core.uat_positions import load_positions_fixture
        from bat_telegram.bots.kavach2.strategy.multileg_entry import resolve_expiry, resolve_symbol
    except Exception as exc:
        logger.warning("uat fixture import failed: %s", exc)
        return []
    try:
        fx = load_positions_fixture(workspace_root())
    except Exception as exc:
        logger.warning("uat fixture load failed: %s", exc)
        return []
    if not isinstance(fx, dict):
        return []
    try:
        exp = resolve_expiry()
        exp_s = exp.isoformat()
    except Exception:
        exp = None
        exp_s = ""
    out: list[dict[str, Any]] = []
    lot_size = _lot_size()
    for leg in fx.get("legs") or []:
        opt = str(leg.get("type") or "").upper()
        side = str(leg.get("side") or "").upper()
        if opt not in ("CE", "PE") or side not in ("BUY", "SELL"):
            continue
        try:
            strike = int(leg.get("strike") or 0)
            lots = max(1, int(leg.get("lots") or 1))
        except (TypeError, ValueError):
            continue
        qty = lots * lot_size
        symbol = ""
        try:
            symbol, lot = resolve_symbol(strike, opt, exp)
            lot_size = int(lot or lot_size)
            qty = lots * lot_size
        except Exception:
            symbol = f"NIFTY-{strike}-{opt}"
        out.append(
            {
                "symbol": symbol,
                "display_symbol": symbol,
                "strike": strike,
                "opt_type": opt,
                "direction": "LONG" if side == "BUY" else "SHORT",
                "qty": qty,
                "avg_price": float(leg.get("avg_price") or 0),
                "instrument_token": "",
                "expiry": exp_s,
            }
        )
    return out


def _load_register_book() -> tuple[list[dict[str, Any]], str]:
    """Broker NIFTY options first; UAT/paper fixture if the book is empty."""
    note = ""
    positions: list[dict[str, Any]] = []
    rt = require_runtime()
    from core.broker_resolve import resolve_kavach_broker

    broker = resolve_kavach_broker(root=getattr(rt, "root", None), runtime_broker=getattr(rt, "broker", None))
    if broker is not None and getattr(rt, "broker", None) is None:
        rt.broker = broker
    if broker:
        try:
            refresh = getattr(broker, "refresh_fixture_positions", None)
            if callable(refresh):
                refresh()
            try:
                from core.zerodha_credentials import sync_live_zerodha_token

                sync_live_zerodha_token(broker, root=getattr(rt, "root", None))
            except Exception:
                pass
            from core.positions import filter_nifty_positions

            df = broker.get_positions()
            positions = filter_nifty_positions(df)
        except Exception as exc:
            logger.warning("register book broker failed: %s", exc)
            note = f"Broker book unavailable ({exc})."
    if not positions:
        from core.batman_mode import is_uat

        root = getattr(rt, "root", None)
        if is_uat(root):
            fixture = _positions_from_uat_fixture()
            if fixture:
                positions = fixture
                note = (note + " Using UAT/paper position book.").strip()
            elif not note:
                note = "No open NIFTY option legs in the book. Deploy Batman first, then Register."
        elif not note:
            note = "No open NIFTY option legs on Zerodha. Open the book, then Register."
    return positions, note


def _public_leg(pos: dict[str, Any], lot_size: int) -> dict[str, Any]:
    from core.position_scope import qty_to_lots

    qty = abs(int(pos.get("qty") or 0))
    lots = qty_to_lots(qty, lot_size)
    symbol = str(pos.get("symbol") or "")
    display = str(pos.get("display_symbol") or symbol)
    avg = pos.get("avg_price") or 0
    try:
        avg_s = f"{float(avg):.2f}"
    except (TypeError, ValueError):
        avg_s = "—"
    label = f"{display} | {pos.get('direction')} {qty} qty ({lots} lots) | avg ₹{avg_s}"
    return {
        "symbol": symbol,
        "strike": int(pos.get("strike") or 0),
        "opt_type": str(pos.get("opt_type") or pos.get("option_type") or ""),
        "direction": str(pos.get("direction") or ""),
        "qty": qty,
        "lots": lots,
        "avg_price": avg,
        "label": label,
        "expiry": pos.get("expiry") or "",
    }


def _find_book_leg(book: list[dict[str, Any]], symbol: str) -> dict[str, Any] | None:
    want = str(symbol or "").strip()
    if not want:
        return None
    for pos in book:
        if str(pos.get("symbol") or "") == want:
            return pos
    return None


def _store_leg(pos: dict[str, Any], lot_size: int) -> dict[str, Any]:
    opt = str(pos.get("opt_type") or pos.get("option_type") or "")
    direction = str(pos.get("direction") or "")
    txn = "BUY" if direction == "LONG" else "SELL"
    return {
        "symbol": pos["symbol"],
        "display_symbol": pos.get("display_symbol") or pos["symbol"],
        "strike": int(pos["strike"]),
        "qty": abs(int(pos.get("qty") or 0)),
        "avg_price": pos.get("avg_price") or 0,
        "option_type": opt,
        "opt_type": opt,
        "direction": direction,
        "transaction_type": txn,
        "lot_size": int(lot_size),
        "expiry": pos.get("expiry") or "",
        "instrument_token": str(pos.get("instrument_token") or ""),
    }


def _archive_active_web() -> list[str]:
    from core.batman_mode import deployments_dir

    dep_dir = deployments_dir(require_runtime().root)
    archive = dep_dir / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for f in sorted(dep_dir.glob("batman_*.json")):
        dest = archive / f.name
        shutil.move(str(f), str(dest))
        moved.append(f.name)
    return moved


def _nifty_level_offset(raw: Any, side: str, kind: str, strike: int | None) -> tuple[Any, str | None]:
    from core.buffer_config.levels import parse_and_validate_user_buffer_or_level

    text = str(raw or "").strip()
    if not text:
        return None, f"{side} {kind} needs a NIFTY level (e.g. 24160)."
    value, err, _mode = parse_and_validate_user_buffer_or_level(
        text, side=side, kind=kind, sell_strike=strike
    )
    if err:
        return None, err
    return value, None



def _default_order_mode() -> str:
    """Prod is live Zerodha; UAT/dev stay paper unless state already says live."""
    try:
        from core.batman_mode import is_prod
        from core.order_mode import order_mode_from_state

        rt = require_runtime()
        default = "live" if is_prod(getattr(rt, "root", None)) else "paper"
        return order_mode_from_state(getattr(rt, "state", None), default=default)
    except Exception:
        return "paper"

def register_defaults(expiry: str | None = None) -> dict[str, Any]:
    from core.position_scope import auto_protect_strike, filter_positions_by_direction, filter_positions_by_side
    from core.wizard_plan import max_wizard_question_count

    from core.nifty_option_expiry import (
        choose_default_register_expiry,
        filter_positions_for_expiry,
        list_register_week_expiries,
    )

    px = nifty_ltp()
    lot_size = _lot_size()
    book, note = _load_register_book()
    expiry_options = list_register_week_expiries()
    expiry_pub = [{"id": o["id"], "iso": o["iso"], "label": o["label"]} for o in expiry_options]
    chosen = str(expiry or "").strip()
    valid = {o["iso"] for o in expiry_pub}
    if chosen not in valid:
        chosen = choose_default_register_expiry(book, expiry_options)
    exp_d = date.fromisoformat(chosen) if chosen else None
    expiry_label = next((o["label"] for o in expiry_pub if o["iso"] == chosen), chosen)
    if exp_d is not None:
        book = filter_positions_for_expiry(book, exp_d)
        if not book:
            extra = f"No open NIFTY option legs for {expiry_label or chosen}."
            note = extra if not note else f"{note} {extra}"
    pe_long = [_public_leg(p, lot_size) for p in filter_positions_by_direction(filter_positions_by_side(book, "PE"), "LONG")]
    pe_short = [_public_leg(p, lot_size) for p in filter_positions_by_direction(filter_positions_by_side(book, "PE"), "SHORT")]
    ce_long = [_public_leg(p, lot_size) for p in filter_positions_by_direction(filter_positions_by_side(book, "CE"), "LONG")]
    ce_short = [_public_leg(p, lot_size) for p in filter_positions_by_direction(filter_positions_by_side(book, "CE"), "SHORT")]
    book_pe = bool(pe_long)
    book_ce = bool(ce_long)
    if book_pe and book_ce:
        scope = "both"
    elif book_pe:
        scope = "pe"
    elif book_ce:
        scope = "ce"
    else:
        scope = "both"
    questions = [
        {"id": "order_mode", "n": 1, "section": "Shared", "label": "Paper or Live trade"},
        {"id": "reg_expiry", "n": 2, "section": "Shared", "label": "Expiry week"},
        {"id": "reg_scope", "n": 3, "section": "Shared", "label": "Register CE/PE"},
        {"id": "pe_buy", "n": 3, "section": "PE", "label": "Select Core PE BUY leg"},
        {"id": "pe_margin_hedge", "n": 4, "section": "PE", "label": "Select Margin Hedge"},
        {"id": "pe_dyn_hedge", "n": 5, "section": "PE", "label": "35% Dynamic Hedge"},
        {"id": "pe_sell", "n": 6, "section": "PE", "label": "Select PE SELL leg"},
        {"id": "pe_ato_strike", "n": 7, "section": "PE", "label": "ATO strike"},
        {"id": "pe_entry", "n": 8, "section": "PE", "label": "Entry NIFTY level"},
        {"id": "pe_exit", "n": 9, "section": "PE", "label": "Exit NIFTY level (retrace)"},
        {"id": "ce_buy", "n": 10, "section": "CE", "label": "Select Core CE BUY leg"},
        {"id": "ce_margin_hedge", "n": 11, "section": "CE", "label": "Select Margin Hedge"},
        {"id": "ce_dyn_hedge", "n": 12, "section": "CE", "label": "35% Dynamic Hedge"},
        {"id": "ce_sell", "n": 13, "section": "CE", "label": "Select CE SELL leg"},
        {"id": "ce_ato_strike", "n": 14, "section": "CE", "label": "ATO strike"},
        {"id": "ce_entry", "n": 15, "section": "CE", "label": "Entry NIFTY level"},
        {"id": "ce_exit", "n": 16, "section": "CE", "label": "Exit NIFTY level (retrace)"},
        {"id": "ato_mon", "n": 17, "section": "Shared", "label": "ATO manage CE/PE"},
        {"id": "confirm", "n": 18, "section": "Shared", "label": "Confirm deployment"},
    ]
    return {
        "ok": True,
        "question_count": max_wizard_question_count(),
        "questions": questions,
        "order_mode": _default_order_mode(),
        "expiry": chosen,
        "expiry_label": expiry_label,
        "expiry_options": expiry_pub,
        "reg_scope": scope,
        "nifty_ltp": px,
        "lot_size": lot_size,
        "ato_step": ATO_STEP,
        "poll_options": [0, 1, 2, 3, 4, 5, 10, 15],
        "poll_interval": 2,
        "ato_mon": "both" if book_pe and book_ce else ("pe" if book_pe else "ce"),
        "pe_long": pe_long,
        "pe_short": pe_short,
        "ce_long": ce_long,
        "ce_short": ce_short,
        "book_has_pe": book_pe,
        "book_has_ce": book_ce,
        "book_note": note,
        "auto_protect_hint": {
            "pe": auto_protect_strike(int(pe_short[0]["strike"]), "PE", ato_step=ATO_STEP) if pe_short else None,
            "ce": auto_protect_strike(int(ce_short[0]["strike"]), "CE", ato_step=ATO_STEP) if ce_short else None,
        },
        "deployed": bool(_active_deployment()),
        "file": _active_deployment().name if _active_deployment() else "",
        "entry_placeholder": "NIFTY level (e.g. 24160)",
        "exit_placeholder": "NIFTY level (e.g. 24200)",
    }


def register_batman(payload: dict[str, Any]) -> dict[str, Any]:
    from core.batman_mode import deployments_dir
    from core.buffer_config.schema import (
        BufferKind,
        legacy_int_from_buffer,
        normalize_buffer_field,
        serialize_buffer_field,
    )
    from core.deployment_lock import deployment_session
    from core.order_mode import normalize_order_mode
    from core.position_scope import (
        auto_protect_strike,
        build_registration_scope,
        parse_and_validate_protect_strike,
        qty_to_lots,
        suggested_ato_lots,
    )
    from core.positions import build_ato_protect_symbol

    if not payload.get("confirm"):
        return {"ok": False, "error": "Confirm Register to arm Kavach."}

    rt = require_runtime()
    from core.nifty_option_expiry import (
        filter_positions_for_expiry,
        list_register_week_expiries,
        symbol_matches_register_expiry,
    )

    lot_size = _lot_size()
    book, _note = _load_register_book()
    if not book:
        return {"ok": False, "error": "No NIFTY option legs in the book. Deploy Batman first, then Register."}

    expiry_raw = str(payload.get("expiry") or "").strip()
    if not expiry_raw:
        return {"ok": False, "error": "Pick an expiry week before Register."}
    try:
        exp_d = date.fromisoformat(expiry_raw)
    except ValueError:
        return {"ok": False, "error": "Expiry week is not a valid date."}
    expiry_options = list_register_week_expiries()
    expiry_label = next((str(o["label"]) for o in expiry_options if o["iso"] == expiry_raw), expiry_raw)
    if expiry_raw not in {o["iso"] for o in expiry_options}:
        return {"ok": False, "error": f"Expiry {expiry_raw} is not in this week / next week / week after."}
    book = filter_positions_for_expiry(book, exp_d)
    if not book:
        return {"ok": False, "error": f"No NIFTY option legs for {expiry_label}."}

    order_mode = str(payload.get("order_mode") or _default_order_mode()).strip().lower()
    if order_mode not in ("paper", "live"):
        order_mode = _default_order_mode()

    scope_choice = str(payload.get("reg_scope") or "both").strip().lower()
    if scope_choice not in ("both", "ce", "pe"):
        return {"ok": False, "error": "Register CE/PE must be both, CE only, or PE only."}
    pe_on = scope_choice in ("both", "pe")
    ce_on = scope_choice in ("both", "ce")

    selected: dict[str, Any] = {
        "pe_buy": None,
        "pe_margin_hedge": None,
        "pe_dyn_hedge": None,
        "pe_sell": None,
        "ce_buy": None,
        "ce_margin_hedge": None,
        "ce_dyn_hedge": None,
        "ce_sell": None,
    }

    def _role(name: str, required: bool) -> tuple[dict[str, Any] | None, str | None]:
        raw = str(payload.get(name) or "").strip()
        if not raw:
            if required:
                return None, f"{name} is required."
            return None, None
        pos = _find_book_leg(book, raw)
        if not pos:
            return None, f"{name} is not in the current book."
        return _store_leg(pos, lot_size), None

    if pe_on:
        for name, required in (
            ("pe_buy", True),
            ("pe_margin_hedge", False),
            ("pe_dyn_hedge", False),
            ("pe_sell", True),
        ):
            leg, err = _role(name, required)
            if err:
                return {"ok": False, "error": err}
            selected[name] = leg
        if selected["pe_buy"]["direction"] != "LONG":
            return {"ok": False, "error": "PE BUY must be a LONG leg."}
        if selected["pe_sell"]["direction"] != "SHORT":
            return {"ok": False, "error": "PE SELL must be a SHORT leg."}

    if ce_on:
        for name, required in (
            ("ce_buy", True),
            ("ce_margin_hedge", False),
            ("ce_dyn_hedge", False),
            ("ce_sell", True),
        ):
            leg, err = _role(name, required)
            if err:
                return {"ok": False, "error": err}
            selected[name] = leg
        if selected["ce_buy"]["direction"] != "LONG":
            return {"ok": False, "error": "CE BUY must be a LONG leg."}
        if selected["ce_sell"]["direction"] != "SHORT":
            return {"ok": False, "error": "CE SELL must be a SHORT leg."}

    used = [leg["symbol"] for leg in selected.values() if leg]
    if len(set(used)) != len(used):
        return {"ok": False, "error": "Each leg must be a different contract."}
    for leg in selected.values():
        if not leg:
            continue
        sym = str(leg.get("symbol") or "")
        if not symbol_matches_register_expiry(sym, exp_d):
            return {
                "ok": False,
                "error": f"{sym} is not the selected week ({expiry_label}).",
            }

    pe_sell_strike = int(selected["pe_sell"]["strike"]) if selected["pe_sell"] else None
    ce_sell_strike = int(selected["ce_sell"]["strike"]) if selected["ce_sell"] else None

    pe_entry = pe_exit = ce_entry = ce_exit = 0
    if pe_on:
        pe_entry, err = _nifty_level_offset(payload.get("pe_entry"), "PE", "entry", pe_sell_strike)
        if err:
            return {"ok": False, "error": err}
        pe_exit, err = _nifty_level_offset(payload.get("pe_exit"), "PE", "exit", pe_sell_strike)
        if err:
            return {"ok": False, "error": err}
    if ce_on:
        ce_entry, err = _nifty_level_offset(payload.get("ce_entry"), "CE", "entry", ce_sell_strike)
        if err:
            return {"ok": False, "error": err}
        ce_exit, err = _nifty_level_offset(payload.get("ce_exit"), "CE", "exit", ce_sell_strike)
        if err:
            return {"ok": False, "error": err}

    def _protect(side: str, sell_strike: int | None):
        if sell_strike is None:
            return None, "FIXED", None
        mode = str(payload.get(f"{side.lower()}_ato_mode") or "auto").strip().lower()
        if mode == "custom":
            value, err = parse_and_validate_protect_strike(str(payload.get(f"{side.lower()}_ato_strike") or ""))
            if err:
                return None, "CUSTOM", err
            return value, "CUSTOM", None
        return auto_protect_strike(sell_strike, side, ato_step=ATO_STEP), "FIXED", None

    pe_prot = ce_prot = None
    pe_prot_mode = ce_prot_mode = "FIXED"
    if pe_on:
        pe_prot, pe_prot_mode, perr = _protect("PE", pe_sell_strike)
        if perr:
            return {"ok": False, "error": perr}
    if ce_on:
        ce_prot, ce_prot_mode, cerr = _protect("CE", ce_sell_strike)
        if cerr:
            return {"ok": False, "error": cerr}

    raw = payload.get("poll_interval", 2)
    try:
        poll = 2 if raw is None or raw == "" else int(raw)
    except (TypeError, ValueError):
        poll = 2
    if poll not in (0, 1, 2, 3, 4, 5, 10, 15):
        poll = 2

    ato_mon = str(payload.get("ato_mon") or "both").strip().lower()
    if pe_on and not ce_on:
        ato_mon = "pe"
    elif ce_on and not pe_on:
        ato_mon = "ce"
    elif ato_mon not in ("both", "ce", "pe"):
        ato_mon = "both"
    if ato_mon == "pe" and not pe_on:
        return {"ok": False, "error": "ATO cannot manage PE — PE was not registered."}
    if ato_mon == "ce" and not ce_on:
        return {"ok": False, "error": "ATO cannot manage CE — CE was not registered."}

    pe_managed = qty_to_lots(int(selected["pe_buy"]["qty"]), lot_size) if selected["pe_buy"] else None
    ce_managed = qty_to_lots(int(selected["ce_buy"]["qty"]), lot_size) if selected["ce_buy"] else None
    pe_ato_lots = (
        suggested_ato_lots(pe_managed, int(selected["pe_buy"]["qty"]), lot_size=lot_size)
        if selected["pe_buy"]
        else None
    )
    ce_ato_lots = (
        suggested_ato_lots(ce_managed, int(selected["ce_buy"]["qty"]), lot_size=lot_size)
        if selected["ce_buy"]
        else None
    )

    scope = build_registration_scope(
        pe_enabled=pe_on,
        ce_enabled=ce_on,
        pe_managed_lots=pe_managed,
        ce_managed_lots=ce_managed,
        pe_ato_lots=pe_ato_lots,
        ce_ato_lots=ce_ato_lots,
        lot_size=lot_size,
    )
    scope["expiry"] = expiry_raw
    scope["expiry_label"] = expiry_label

    ce_entry_dec = normalize_buffer_field(ce_entry)
    pe_entry_dec = normalize_buffer_field(pe_entry)
    ce_retrace_dec = normalize_buffer_field(ce_exit)
    pe_retrace_dec = normalize_buffer_field(pe_exit)

    pe_ato_sym = ce_ato_sym = None
    if selected["pe_sell"] and pe_prot:
        pe_ato_sym = build_ato_protect_symbol(selected["pe_sell"]["symbol"], int(pe_prot), "PE")
    if selected["ce_sell"] and ce_prot:
        ce_ato_sym = build_ato_protect_symbol(selected["ce_sell"]["symbol"], int(ce_prot), "CE")

    now = datetime.now()
    filename = f"batman_{now.strftime('%Y-%m-%d_%H-%M')}.json"
    dep_dir = deployments_dir(rt.root)
    dep_dir.mkdir(parents=True, exist_ok=True)
    filepath = dep_dir / filename

    data: dict[str, Any] = {
        "schema_version": 1.1,
        "order_mode": normalize_order_mode(order_mode),
        "deployed_at": now.astimezone().isoformat(),
        "registered_at": now.strftime("%A %d-%b-%Y at %H:%M"),
        "file_name": filename,
        "source": "kavach_web",
        "retrace_points": int(legacy_int_from_buffer(ce_exit if ce_on else pe_exit, default=0)),
        "ato_manage_sides": ato_mon,
        "registration_scope": scope,
        "positions": selected,
        "ato": {
            "pe_protect_symbol": pe_ato_sym,
            "pe_protect_strike": pe_prot,
            "pe_protect_strike_mode": pe_prot_mode if pe_on else None,
            "ce_protect_symbol": ce_ato_sym,
            "ce_protect_strike": ce_prot,
            "ce_protect_strike_mode": ce_prot_mode if ce_on else None,
            "ato_step": ATO_STEP,
            "ce_entry_buffer": serialize_buffer_field(ce_entry_dec, BufferKind.CUSTOM),
            "pe_entry_buffer": serialize_buffer_field(pe_entry_dec, BufferKind.CUSTOM),
            "ce_retrace_buffer": serialize_buffer_field(ce_retrace_dec, BufferKind.CUSTOM),
            "pe_retrace_buffer": serialize_buffer_field(pe_retrace_dec, BufferKind.CUSTOM),
            "ce_entry_buffer_points": legacy_int_from_buffer(ce_entry),
            "pe_entry_buffer_points": legacy_int_from_buffer(pe_entry),
            "ce_retrace_points": legacy_int_from_buffer(ce_exit),
            "pe_retrace_points": legacy_int_from_buffer(pe_exit),
            "poll_interval_seconds": poll,
        },
        "status": "armed",
    }
    # Overnight / Hedge Box DTE source (Ratripal). Prefer registered week expiry.
    try:
        exp = str((scope or {}).get("expiry") or "").strip()
        if exp:
            data["calendar"] = {
                "expiry_date": exp[:10],
                "source": "registration_scope",
            }
    except Exception:
        pass

    try:
        from core.ato_working_profile import apply_working_profile_to_deploy

        apply_working_profile_to_deploy(data)
    except Exception as exc:
        logger.warning("working profile skip: %s", exc)

    with deployment_session("register_confirm"):
        moved = _archive_active_web()
        filepath.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        _sync_state(filepath, rt.state)
        if rt.event_bus:
            try:
                from core.event_bus import Event

                rt.event_bus.publish(Event.DEPLOYMENT_CONFIRMED, {"file": str(filepath)})
            except Exception:
                pass

    lines = [
        "Batman armed. Kavach is watching.",
        f"File: {filename}",
        f"Mode: {order_mode}",
        f"Register: {scope_choice}",
        f"ATO manage: {ato_mon}",
        f"Poll: {poll}s",
    ]
    if moved:
        lines.append("Archived: " + ", ".join(moved))
    if pe_on:
        lines.append(f"PE sell {pe_sell_strike}  protect {pe_prot}  {pe_ato_sym}")
    if ce_on:
        lines.append(f"CE sell {ce_sell_strike}  protect {ce_prot}  {ce_ato_sym}")
    return {"ok": True, "text": "\n".join(lines), "file": filename}

def _sync_state(filepath: Path, state: Any) -> None:
    from core.buffer_config.schema import normalize_buffer_field
    from core.position_scope import legacy_registration_scope_from_deployment

    if state is None:
        return
    dep = json.loads(filepath.read_text(encoding="utf-8"))
    positions = dep.get("positions") or {}
    ato = dep.get("ato") or {}
    scope = legacy_registration_scope_from_deployment(dep)
    for role, leg in positions.items():
        state.set(f"positions.{role}", leg, save=False)
    state.set("deployment.registration_scope", scope, save=False)
    state.set("ato.ce_protect_symbol", ato.get("ce_protect_symbol"), save=False)
    state.set("ato.ce_protect_strike", ato.get("ce_protect_strike"), save=False)
    state.set("ato.pe_protect_symbol", ato.get("pe_protect_symbol"), save=False)
    state.set("ato.pe_protect_strike", ato.get("pe_protect_strike"), save=False)
    state.set("ato.manage_sides", dep.get("ato_manage_sides", "both"), save=False)
    state.set("ato.poll_interval_seconds", ato.get("poll_interval_seconds"), save=False)
    ce_entry = ato.get("ce_entry_buffer", ato.get("ce_entry_buffer_points", 0))
    pe_entry = ato.get("pe_entry_buffer", ato.get("pe_entry_buffer_points", 0))
    ce_retrace = ato.get("ce_retrace_buffer", ato.get("ce_retrace_points", dep.get("retrace_points", 0)))
    pe_retrace = ato.get("pe_retrace_buffer", ato.get("pe_retrace_points", dep.get("retrace_points", 0)))
    state.set("ato.ce_entry_buffer_points", normalize_buffer_field(ce_entry), save=False)
    state.set("ato.pe_entry_buffer_points", normalize_buffer_field(pe_entry), save=False)
    state.set("ato.ce_retrace_points", normalize_buffer_field(ce_retrace), save=False)
    state.set("ato.pe_retrace_points", normalize_buffer_field(pe_retrace), save=False)
    has_dyn = bool(positions.get("pe_dyn_hedge") or positions.get("ce_dyn_hedge"))
    state.set("dyn_hedge.pe_exited_date", None, save=False)
    state.set("dyn_hedge.ce_exited_date", None, save=False)
    state.set("dyn_hedge.exit_enabled", has_dyn, save=False)
    state.set("ato.ce_triggered", False, save=False)
    state.set("ato.pe_triggered", False, save=False)
    state.set("ato.ce_ato_active", False, save=False)
    state.set("ato.pe_ato_active", False, save=False)
    state.set("ato.ce_awaiting_clearance", False, save=False)
    state.set("ato.pe_awaiting_clearance", False, save=False)
    try:
        from core.ato_side_state import clear_all_side_halts
        clear_all_side_halts(state, save=False)
    except Exception:
        state.set("ato.ce_side_halted", False, save=False)
        state.set("ato.pe_side_halted", False, save=False)
        state.set("ato.ce_halt_reason", None, save=False)
        state.set("ato.pe_halt_reason", None, save=False)
    state.set("deployment.confirmed", True, save=False)
    state.set("deployment.batman_complete", False, save=False)
    state.set("deployment.file", str(filepath), save=False)
    try:
        from core.overnight_handoff import reset_overnight_cycles

        reset_overnight_cycles(state)
    except Exception:
        pass
    # Overnight hedge (RATRIPAL): arm with this register so 15:15 plan can run today.
    has_sell = bool(positions.get("pe_sell") or positions.get("ce_sell"))
    state.set("modules.ratripal.enabled", has_sell, save=False)
    state.set("ratripal.last_run_date", None, save=False)
    state.set("ratripal.last_decision", None, save=False)
    state.set("ratripal.pending.request_id", None, save=False)
    state.set("ratripal.pending.response", None, save=False)
    state.set("overnight.hedge_active", False, save=False)
    state.set("overnight.morning_done_date", None, save=False)
    state.set("algo.paused", False, save=False)
    try:
        from core.pnl_exit_guard import clear_last_fire

        clear_last_fire(state, save=False)
    except Exception:
        state.set("pnl_exit.last_reason", None, save=False)
        state.set("pnl_exit.last_pnl", None, save=False)
        state.set("pnl_exit.last_at", None, save=False)
    try:
        from core.ato_working_profile import apply_working_profile_to_state

        apply_working_profile_to_state(state, save=False, for_deploy=True)
    except Exception:
        pass
    state.save()

def _week_expiry_from_payload(raw: Any) -> tuple[date | None, str, str | None]:
    from core.nifty_option_expiry import list_register_week_expiries

    text = str(raw or "").strip()
    options = list_register_week_expiries()
    if not text:
        return None, "", "Pick an expiry week before Deploy."
    try:
        exp_d = date.fromisoformat(text)
    except ValueError:
        return None, "", "Expiry week is not a valid date."
    label = next((str(o["label"]) for o in options if o["iso"] == text), "")
    if not label:
        return None, "", "Expiry is not in this week / next week / week after."
    return exp_d, label, None


def deploy_defaults(expiry: str | None = None) -> dict[str, Any]:
    from core.nifty_option_expiry import choose_default_register_expiry, list_register_week_expiries

    px = nifty_ltp()
    options = list_register_week_expiries()
    expiry_pub = [{"id": o["id"], "iso": o["iso"], "label": o["label"]} for o in options]
    chosen = str(expiry or "").strip()
    valid = {o["iso"] for o in expiry_pub}
    if chosen not in valid:
        chosen = choose_default_register_expiry([], options)
    expiry_label = next((o["label"] for o in expiry_pub if o["iso"] == chosen), chosen)
    return {
        "ok": True,
        "level": round_nifty_50(px) or "",
        "lots": 1,
        "nifty_ltp": px,
        "placeholder_level": "NIFTY center level (e.g. 24200)",
        "placeholder_lots": "Lots",
        "expiry": chosen,
        "expiry_label": expiry_label,
        "expiry_options": expiry_pub,
    }


def deploy_preview(payload: dict[str, Any]) -> dict[str, Any]:
    from bat_telegram.bots.kavach2.strategy import multileg_entry
    from core.nifty_option_expiry import expiry_label_from_date

    try:
        level = float(str(payload.get("level") or "").replace(",", ""))
        lots = int(payload.get("lots") or 1)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Enter a NIFTY center level and lots."}
    if lots < 1:
        return {"ok": False, "error": "Lots must be at least 1."}
    exp_d, expiry_label, err = _week_expiry_from_payload(payload.get("expiry"))
    if err or exp_d is None:
        return {"ok": False, "error": err or "Pick an expiry week before Deploy."}
    legs, preview = multileg_entry.build_preview(level, base_lots=lots, lot_size=LOT_SIZE, params={})
    exp = multileg_entry.resolve_expiry(exp_d)
    ltp_by_key: dict[str, Any] = {}
    try:
        from web.runtime import require_runtime

        rt = require_runtime()
        broker = getattr(rt, "broker", None)
        if broker is not None:
            names: list[str] = []
            meta: list[tuple[str, str]] = []
            for leg in legs:
                strike = int(leg.strike)
                opt = str(leg.option_type).upper()
                sym, _ = multileg_entry.resolve_symbol(strike, opt, exp)
                names.append(sym)
                meta.append((str(getattr(leg, "key", "")), sym))
            batch = {}
            getter = getattr(broker, "get_ltps_kite_batch", None)
            if callable(getter) and names:
                batch = getter(names) or {}
            for key, sym in meta:
                kite_px = batch.get(sym)
                if kite_px is None:
                    kite_px = broker.get_ltp([sym], kite_only=True).get(sym)
                ltp_by_key[key] = kite_px
        else:
            logger.warning("preview kite quote skipped: broker not connected")
    except Exception as exc:
        logger.warning("preview kite quote failed: %s", exc)

    def _table_row(sn: int, key: str, side: str, opt: str, strike: int, qty: int) -> dict[str, Any]:
        ls = int(LOT_SIZE) or 65
        return {
            "sn": sn,
            "type": key,
            "side": side,
            "opt": opt,
            "strike": int(strike),
            "lots": int(qty) // ls if ls else 0,
            "qty": int(qty),
            "ltp": ltp_by_key.get(key),
        }

    place_rows = [
        _table_row(
            i,
            str(row["key"]),
            str(row["side"]),
            str(row["type"]),
            int(row["strike"]),
            int(row.get("qty") or 0),
        )
        for i, row in enumerate(preview, start=1)
    ]
    shown = {str(row["key"]) for row in preview}
    skipped_legs = [leg for leg in legs if int(leg.qty or 0) <= 0 and leg.key not in shown]
    skipped_rows = [
        _table_row(i, leg.key, leg.side, leg.option_type, int(leg.strike), int(leg.qty or 0))
        for i, leg in enumerate(skipped_legs, start=1)
    ]
    exp_label = expiry_label_from_date(exp)
    text = multileg_entry.format_preview_text(
        level,
        preview,
        expiry_label=exp_label,
        base_lots=lots,
        all_legs=legs,
        lot_size=LOT_SIZE,
        ltp_by_key=ltp_by_key,
    )
    return {
        "ok": True,
        "text": text,
        "level": level,
        "lots": lots,
        "expiry": exp.isoformat(),
        "expiry_label": exp_label,
        "place_rows": place_rows,
        "skipped_rows": skipped_rows,
        "lot_size": LOT_SIZE,
    }


def deploy_batman(payload: dict[str, Any]) -> dict[str, Any]:
    from bat_telegram.bots.kavach2.strategy import multileg_entry

    if not payload.get("confirm"):
        return deploy_preview(payload)
    rt = require_runtime()
    if not rt.broker:
        return {"ok": False, "error": "No broker connected. Set the Zerodha token on TOKEN first."}
    try:
        level = float(str(payload.get("level") or "").replace(",", ""))
        lots = int(payload.get("lots") or 1)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Enter a NIFTY center level and lots."}
    exp_d, _expiry_label, err = _week_expiry_from_payload(payload.get("expiry"))
    if err or exp_d is None:
        return {"ok": False, "error": err or "Pick an expiry week before Deploy."}
    try:
        result = multileg_entry.deploy_multileg(
            rt.broker,
            center_level=level,
            base_lots=lots,
            lot_size=LOT_SIZE,
            expiry=exp_d,
        )
        filled_n = sum(1 for x in (result.get("legs") or []) if x.get("status") == "filled")
        ok = bool(filled_n > 0 and not result.get("error"))
        text = multileg_entry.format_result_text(result)
        if not ok:
            return {
                "ok": False,
                "error": str(result.get("error") or "No legs filled — no broker orders sent."),
                "text": text,
                "result": result,
            }
        return {"ok": True, "text": text, "result": result}
    except Exception as exc:
        logger.exception("web deploy failed")
        return {"ok": False, "error": str(exc)}


def _build_register_payload_from_deploy(
    deploy_payload: dict[str, Any],
    deploy_result: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Build a Register payload only when every placeable leg fully filled."""
    legs = list((deploy_result or {}).get("legs") or [])
    required = [leg for leg in legs if int(leg.get("qty") or 0) > 0]
    if not required:
        return None, "No placeable legs found in deploy result."
    bad = [
        leg for leg in required
        if str(leg.get("status") or "").lower() != "filled" or not str(leg.get("symbol") or "").strip()
    ]
    if bad:
        bits = [f"{leg.get('key')}[{leg.get('status')}]" for leg in bad]
        return None, "Register not started because one or more legs were not fully filled: " + ", ".join(bits)

    by_key = {str(leg.get('key') or ''): leg for leg in required}
    must = ['ce_buy', 'ce_sell', 'pe_buy', 'pe_sell']
    missing = [k for k in must if k not in by_key]
    if missing:
        return None, 'Register payload missing required deployed legs: ' + ', '.join(missing)

    try:
        ce_sell_strike = int(by_key['ce_sell'].get('strike') or 0)
        pe_sell_strike = int(by_key['pe_sell'].get('strike') or 0)
    except (TypeError, ValueError):
        return None, 'Could not read CE/PE sell strikes from deploy result.'
    if ce_sell_strike <= 0 or pe_sell_strike <= 0:
        return None, 'Could not read CE/PE sell strikes from deploy result.'

    expiry_raw = str(deploy_payload.get('expiry') or '').strip()
    if not expiry_raw:
        return None, 'Pick an expiry week before Register.'

    reg: dict[str, Any] = {
        'confirm': True,
        'order_mode': str(_default_order_mode()),
        'expiry': expiry_raw,
        'reg_scope': 'both',
        'ce_buy': str(by_key['ce_buy'].get('symbol') or ''),
        'ce_margin_hedge': str(by_key.get('ce_margin_hedge', {}).get('symbol') or ''),
        'ce_dyn_hedge': str(by_key.get('ce_dyn_hedge', {}).get('symbol') or ''),
        'ce_sell': str(by_key['ce_sell'].get('symbol') or ''),
        'pe_buy': str(by_key['pe_buy'].get('symbol') or ''),
        'pe_margin_hedge': str(by_key.get('pe_margin_hedge', {}).get('symbol') or ''),
        'pe_dyn_hedge': str(by_key.get('pe_dyn_hedge', {}).get('symbol') or ''),
        'pe_sell': str(by_key['pe_sell'].get('symbol') or ''),
        'ce_ato_mode': 'auto',
        'pe_ato_mode': 'auto',
        'ato_mon': 'both',
        'poll_interval': 2,
        'ce_entry': ce_sell_strike,
        'ce_exit': ce_sell_strike - 10,
        'pe_entry': pe_sell_strike,
        'pe_exit': pe_sell_strike + 10,
    }
    return reg, None


def deploy_and_register_batman(payload: dict[str, Any]) -> dict[str, Any]:
    deploy_out = deploy_batman({**payload, 'confirm': True})
    if not bool(deploy_out.get('ok')):
        return deploy_out
    reg_payload, err = _build_register_payload_from_deploy(payload, deploy_out.get('result') or {})
    if err:
        return {
            'ok': False,
            'error': err,
            'text': (deploy_out.get('text') or '') + '\n\n' + err,
            'deploy': deploy_out,
        }
    reg_out = register_batman(reg_payload)
    if not bool(reg_out.get('ok')):
        return {
            'ok': False,
            'error': str(reg_out.get('error') or 'Register failed.'),
            'text': (deploy_out.get('text') or '') + '\n\nDeploy completed, but Register failed: ' + str(reg_out.get('error') or 'Register failed.'),
            'deploy': deploy_out,
            'register': reg_out,
            'register_payload': reg_payload,
        }
    return {
        'ok': True,
        'text': 'Deploy sent and Register armed successfully.',
        'detail_text': (deploy_out.get('text') or '') + '\n\n' + (reg_out.get('text') or ''),
        'deploy': deploy_out,
        'register': reg_out,
        'register_payload': reg_payload,
    }

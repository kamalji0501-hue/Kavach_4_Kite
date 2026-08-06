"""Tick-by-tick CSV: NIFTY LTP + registered ATO CE/PE option LTPs.

Real-money debug trail on the large data disk (Trading_Runtime_*). Not written
into strategy logic — append-only CSV under ``Data/ato_tick_csv/``.

Columns (stable header)::

    date_time_ist,nifty_ltp,ce_ato_symbol,ce_ato_strike,ce_ato_mode,ce_ato_ltp,
    pe_ato_symbol,pe_ato_strike,pe_ato_mode,pe_ato_ltp,source

- ``source``: nifty_ws | nifty_rest | option_poll | register | meta_refresh
- CE/PE *mode*: AUTO (algo strike) or CUSTOM (user-picked strike)
- Option LTPs update when DRISHTI option poll runs; NIFTY updates on every feed tick.
  Rows always carry the latest known values for the other legs.
"""

from __future__ import annotations

import csv
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")
logger = logging.getLogger("batman.ato_nifty_tick_csv")

CSV_COLUMNS: tuple[str, ...] = (
    "date_time_ist",
    "nifty_ltp",
    "ce_ato_symbol",
    "ce_ato_strike",
    "ce_ato_mode",
    "ce_ato_ltp",
    "pe_ato_symbol",
    "pe_ato_strike",
    "pe_ato_mode",
    "pe_ato_ltp",
    "source",
)

_LOCK = threading.RLock()
_WRITER: "AtoNiftyTickCsvWriter | None" = None


def _now_ist() -> datetime:
    return datetime.now(_IST)


def _fmt_ts(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=_IST)
    else:
        now = now.astimezone(_IST)
    return now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}"


def default_csv_dir(workspace_root: Path | None = None) -> Path:
    """Primary CSV root on the runtime data disk."""
    try:
        from core.batman_mode import data_root

        root = data_root(workspace_root)
    except Exception:
        root = Path(workspace_root or ".") / "data"
    return Path(root) / "ato_tick_csv"


def mirror_log_dir(workspace_root: Path | None = None, *, ts: datetime | None = None) -> Path:
    """Also keep a copy path under DRISHTI day logs for easy tailing."""
    try:
        from core.bot_logging import robot_logs_dir
        from core.batman_mode import workspace_root as ws

        wr = workspace_root or ws()
        return robot_logs_dir(wr, "drishti", ts) / "ato_tick_csv"
    except Exception:
        return default_csv_dir(workspace_root) / "mirror"


@dataclass
class AtoTickMeta:
    ce_symbol: str = ""
    ce_strike: str = ""
    ce_mode: str = ""
    pe_symbol: str = ""
    pe_strike: str = ""
    pe_mode: str = ""

    def apply_watch_item(self, role: str, *, symbol: str = "", strike: Any = None) -> None:
        side = "ce" if role.startswith("ce") else "pe" if role.startswith("pe") else ""
        if side not in {"ce", "pe"}:
            return
        if symbol:
            setattr(self, f"{side}_symbol", str(symbol))
        if strike is not None and str(strike) != "":
            try:
                setattr(self, f"{side}_strike", str(int(strike)))
            except (TypeError, ValueError):
                setattr(self, f"{side}_strike", str(strike))


@dataclass
class AtoNiftyTickCsvWriter:
    """Buffered CSV writer — flush every ``flush_interval_seconds`` or N rows."""

    csv_dir: Path
    mirror_dir: Path | None = None
    flush_interval_seconds: float = 1.0
    flush_every_rows: int = 25
    meta: AtoTickMeta = field(default_factory=AtoTickMeta)
    nifty_ltp: float | None = None
    ce_ato_ltp: float | None = None
    pe_ato_ltp: float | None = None

    _buffer: list[dict[str, str]] = field(default_factory=list, repr=False)
    _last_flush_mono: float = field(default=0.0, repr=False)
    _path_day: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        self.csv_dir = Path(self.csv_dir)
        self.csv_dir.mkdir(parents=True, exist_ok=True)
        if self.mirror_dir is not None:
            self.mirror_dir = Path(self.mirror_dir)
            self.mirror_dir.mkdir(parents=True, exist_ok=True)
        import time

        self._last_flush_mono = time.monotonic()

    def current_path(self, *, now: datetime | None = None) -> Path:
        ts = now or _now_ist()
        day = ts.strftime("%Y%m%d")
        ym = ts.strftime("%Y-%m")
        folder = self.csv_dir / ym
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"ato_nifty_ce_pe_{day}.csv"

    def set_registration(
        self,
        *,
        ce_symbol: str | None = None,
        ce_strike: Any = None,
        ce_mode: str | None = None,
        pe_symbol: str | None = None,
        pe_strike: Any = None,
        pe_mode: str | None = None,
        nifty_ltp: float | None = None,
    ) -> Path:
        """Update ATO meta from Kavach /register and write a REGISTER row."""
        with _LOCK:
            if ce_symbol is not None:
                self.meta.ce_symbol = str(ce_symbol or "")
            if ce_strike is not None and str(ce_strike) != "":
                try:
                    self.meta.ce_strike = str(int(ce_strike))
                except (TypeError, ValueError):
                    self.meta.ce_strike = str(ce_strike)
            if ce_mode is not None:
                self.meta.ce_mode = str(ce_mode or "").upper()
            if pe_symbol is not None:
                self.meta.pe_symbol = str(pe_symbol or "")
            if pe_strike is not None and str(pe_strike) != "":
                try:
                    self.meta.pe_strike = str(int(pe_strike))
                except (TypeError, ValueError):
                    self.meta.pe_strike = str(pe_strike)
            if pe_mode is not None:
                self.meta.pe_mode = str(pe_mode or "").upper()
            if nifty_ltp is not None:
                self.nifty_ltp = float(nifty_ltp)
            path = self._enqueue(source="register", now=_now_ist(), force_flush=True)
            try:
                from core.money_audit import audit

                audit(
                    "ato_tick_csv.register",
                    path=str(path),
                    ce_symbol=self.meta.ce_symbol,
                    ce_strike=self.meta.ce_strike,
                    ce_mode=self.meta.ce_mode,
                    pe_symbol=self.meta.pe_symbol,
                    pe_strike=self.meta.pe_strike,
                    pe_mode=self.meta.pe_mode,
                    nifty_ltp=self.nifty_ltp,
                )
            except Exception:
                pass
            logger.info(
                "ATO tick CSV armed path=%s CE=%s(%s) PE=%s(%s)",
                path,
                self.meta.ce_symbol or "-",
                self.meta.ce_mode or "-",
                self.meta.pe_symbol or "-",
                self.meta.pe_mode or "-",
            )
            return path

    def on_nifty_ltp(
        self,
        now: datetime,
        ltp: float,
        *,
        source: str = "nifty",
    ) -> None:
        with _LOCK:
            self.nifty_ltp = float(ltp)
            self._enqueue(source=source, now=now)

    def on_option_quotes(
        self,
        now: datetime,
        quotes: Mapping[str, float],
        *,
        items: list[Any] | None = None,
        source: str = "option_poll",
    ) -> None:
        with _LOCK:
            if items:
                for it in items:
                    role = str(getattr(it, "role", "") or "")
                    if role in {"ce_protect", "pe_protect"}:
                        self.meta.apply_watch_item(
                            role,
                            symbol=str(getattr(it, "symbol", "") or ""),
                            strike=getattr(it, "strike", None),
                        )
            if "ce_protect" in quotes:
                self.ce_ato_ltp = float(quotes["ce_protect"])
            if "pe_protect" in quotes:
                self.pe_ato_ltp = float(quotes["pe_protect"])
            # Only write a row when we have at least one protect quote or nifty
            if self.nifty_ltp is None and "ce_protect" not in quotes and "pe_protect" not in quotes:
                return
            self._enqueue(source=source, now=now)

    def refresh_meta_from_ato_dict(self, ato: Mapping[str, Any]) -> None:
        """Load symbols/strikes/modes from deployment ``ato`` block or state flat keys."""
        with _LOCK:
            def _g(*keys: str) -> Any:
                for k in keys:
                    if k in ato and ato[k] not in (None, ""):
                        return ato[k]
                return None

            ce_sym = _g("ce_protect_symbol")
            pe_sym = _g("pe_protect_symbol")
            ce_strike = _g("ce_protect_strike")
            pe_strike = _g("pe_protect_strike")
            ce_mode = _g("ce_protect_strike_mode")
            pe_mode = _g("pe_protect_strike_mode")
            if ce_sym is not None:
                self.meta.ce_symbol = str(ce_sym)
            if pe_sym is not None:
                self.meta.pe_symbol = str(pe_sym)
            if ce_strike is not None:
                try:
                    self.meta.ce_strike = str(int(ce_strike))
                except (TypeError, ValueError):
                    self.meta.ce_strike = str(ce_strike)
            if pe_strike is not None:
                try:
                    self.meta.pe_strike = str(int(pe_strike))
                except (TypeError, ValueError):
                    self.meta.pe_strike = str(pe_strike)
            if ce_mode is not None:
                self.meta.ce_mode = str(ce_mode).upper()
            if pe_mode is not None:
                self.meta.pe_mode = str(pe_mode).upper()

    def _row(self, *, source: str, now: datetime) -> dict[str, str]:
        def _px(v: float | None) -> str:
            if v is None:
                return ""
            return f"{float(v):.2f}"

        return {
            "date_time_ist": _fmt_ts(now),
            "nifty_ltp": _px(self.nifty_ltp),
            "ce_ato_symbol": self.meta.ce_symbol,
            "ce_ato_strike": self.meta.ce_strike,
            "ce_ato_mode": self.meta.ce_mode,
            "ce_ato_ltp": _px(self.ce_ato_ltp),
            "pe_ato_symbol": self.meta.pe_symbol,
            "pe_ato_strike": self.meta.pe_strike,
            "pe_ato_mode": self.meta.pe_mode,
            "pe_ato_ltp": _px(self.pe_ato_ltp),
            "source": source,
        }

    def _enqueue(
        self,
        *,
        source: str,
        now: datetime,
        force_flush: bool = False,
    ) -> Path:
        import time

        row = self._row(source=source, now=now)
        self._buffer.append(row)
        path = self.current_path(now=now)
        due = (
            force_flush
            or len(self._buffer) >= self.flush_every_rows
            or (time.monotonic() - self._last_flush_mono) >= self.flush_interval_seconds
        )
        if due:
            self.flush()
        return path

    def flush(self) -> None:
        import time

        with _LOCK:
            if not self._buffer:
                self._last_flush_mono = time.monotonic()
                return
            rows = self._buffer
            self._buffer = []
            self._last_flush_mono = time.monotonic()
            now = _now_ist()
            primary = self.current_path(now=now)
            targets = [primary]
            if self.mirror_dir is not None:
                day = now.strftime("%Y%m%d")
                self.mirror_dir.mkdir(parents=True, exist_ok=True)
                targets.append(self.mirror_dir / f"ato_nifty_ce_pe_{day}.csv")

        wrote_primary = False
        for path in targets:
            try:
                new_file = not path.exists() or path.stat().st_size == 0
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(CSV_COLUMNS), extrasaction="ignore")
                    if new_file:
                        w.writeheader()
                    w.writerows(rows)
                if not wrote_primary:
                    wrote_primary = True
                    logger.debug(
                        "ATO tick CSV flushed rows=%s path=%s new_file=%s",
                        len(rows),
                        path,
                        new_file,
                    )
            except OSError as exc:
                logger.warning("ATO tick CSV flush failed path=%s err=%s", path, exc)
                with _LOCK:
                    self._buffer = rows + self._buffer
                break


def get_ato_tick_csv_writer(
    workspace_root: Path | None = None,
    *,
    create: bool = True,
) -> AtoNiftyTickCsvWriter | None:
    """Process-wide singleton writer (safe across Drishti feed + Kavach)."""
    global _WRITER
    with _LOCK:
        if _WRITER is not None:
            return _WRITER
        if not create:
            return None
        try:
            from core.batman_mode import workspace_root as ws

            wr = Path(workspace_root) if workspace_root else ws()
        except Exception:
            wr = Path(workspace_root or ".")
        mirror: Path | None
        try:
            mirror = mirror_log_dir(wr)
        except Exception:
            mirror = None
        _WRITER = AtoNiftyTickCsvWriter(
            csv_dir=default_csv_dir(wr),
            mirror_dir=mirror,
        )
        # Best-effort: seed meta from current deployment/state
        try:
            from core.option_ltp_watchlist import _positions_and_ato_from_sources

            _pos, ato, _src = _positions_and_ato_from_sources(wr)
            if ato:
                _WRITER.refresh_meta_from_ato_dict(ato)
        except Exception as exc:
            logger.debug("ato tick csv meta seed skipped: %s", exc)
        logger.info("ATO+NIFTY tick CSV writer ready dir=%s", _WRITER.csv_dir)
        return _WRITER


def record_nifty_tick(now: datetime, ltp: float, *, source: str = "nifty") -> None:
    """Fire-and-forget hook for NIFTY feed (never raises into feed loop)."""
    try:
        w = get_ato_tick_csv_writer()
        if w is not None:
            w.on_nifty_ltp(now, float(ltp), source=source)
    except Exception as exc:
        logger.debug("record_nifty_tick skipped: %s", exc)


def record_option_quotes(
    now: datetime,
    quotes: Mapping[str, float],
    *,
    items: list[Any] | None = None,
    source: str = "option_poll",
) -> None:
    try:
        w = get_ato_tick_csv_writer()
        if w is not None:
            w.on_option_quotes(now, quotes, items=items, source=source)
    except Exception as exc:
        logger.debug("record_option_quotes skipped: %s", exc)


def record_registration(**kwargs: Any) -> Path | None:
    """Called from Kavach after /register confirm — returns CSV path for Telegram."""
    try:
        w = get_ato_tick_csv_writer()
        if w is None:
            return None
        return w.set_registration(**kwargs)
    except Exception as exc:
        logger.warning("record_registration failed: %s", exc)
        return None
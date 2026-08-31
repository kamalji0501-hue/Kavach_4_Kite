"""Unit tests for ATO readiness ARMED / BLOCKED matrix."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from core.ato_readiness import compute_ato_readiness


class _FakeSnap:
    def __init__(self, *, ltp=24100.0, age=1.0, healthy=True, source="dhan_ws", collector="feeder"):
        self.ltp = ltp
        self._age = age
        self.feed_healthy = healthy
        self.source = source
        self.collector = collector
        self.consecutive_failures = 0

    def age_seconds(self, now=None):
        return self._age


class _State:
    def __init__(self, data=None):
        self._d = dict(data or {})

    def get(self, key, default=None):
        return self._d.get(key, default)


def _base_patches(*, ready=True, detail="ok", snap=None, socket=True, dfb=True, kav=True):
    snap = snap or _FakeSnap()
    return [
        patch("core.nifty_ltp_feed.read_nifty_ltp_cache", return_value=snap),
        patch("core.nifty_ltp_feed.cache_consumer_status", return_value=(ready, detail)),
        patch("core.nifty_ltp_feed.consumer_max_age_for_trading", return_value=6.0),
        patch("core.nifty_ltp_feed.default_cache_path", return_value=SimpleNamespace()),
        patch("core.feeder_ipc.feeder_socket_ready", return_value=socket),
        patch("core.ato_readiness._svc_active", side_effect=lambda n: dfb if "datafeed" in n else kav),
        patch(
            "core.ato_monitoring_schedule.is_past_monitoring_start",
            return_value=True,
        ),
        patch("core.ato_readiness._levels_from_state", return_value={
            "pe_entry": "24100",
            "pe_exit": "24150",
            "ce_entry": "24200",
            "ce_exit": "24150",
            "protect_symbol_pe": "NIFTY24900PE",
            "protect_symbol_ce": "",
            "protect_broker_qty_pe": 0,
            "protect_broker_qty_ce": 0,
        }),
    ]


def _armed_state(**extra):
    d = {
        "deployment.confirmed": True,
        "algo.paused": False,
        "ato.manage_sides": "pe",
        "ato.pe_side_halted": False,
        "ato.ce_side_halted": False,
    }
    d.update(extra)
    return _State(d)


def test_armed_when_feed_fresh_and_gates_open():
    patches = _base_patches()
    for p in patches:
        p.start()
    try:
        snap = compute_ato_readiness(state=_armed_state(), positions=[], check_services=True)
        assert snap["armed"] is True
        assert snap["hard_blocked_reasons"] == []
        assert "ARMED" in snap["summary_line"]
    finally:
        for p in patches:
            p.stop()


def test_blocked_when_paused():
    patches = _base_patches()
    for p in patches:
        p.start()
    try:
        snap = compute_ato_readiness(
            state=_armed_state(algo_paused=True) if False else _armed_state(
                **{"algo.paused": True, "algo.pause_reason": "nifty_ltp_cache_stale"}
            ),
            positions=[],
        )
        assert snap["armed"] is False
        assert "algo_paused" in snap["hard_blocked_reasons"]
    finally:
        for p in patches:
            p.stop()


def test_blocked_when_stale_cache():
    stale = _FakeSnap(age=18.0, healthy=True)
    patches = _base_patches(ready=False, detail="stale", snap=stale)
    for p in patches:
        p.start()
    try:
        snap = compute_ato_readiness(state=_armed_state(), positions=[])
        assert snap["armed"] is False
        assert "nifty_cache_stale" in snap["hard_blocked_reasons"]
        assert "stale" in snap["summary_line"].lower() or "BLOCKED" in snap["summary_line"]
    finally:
        for p in patches:
            p.stop()


def test_blocked_when_pe_halted_manage_pe():
    patches = _base_patches()
    for p in patches:
        p.start()
    try:
        snap = compute_ato_readiness(
            state=_armed_state(
                **{"ato.pe_side_halted": True, "ato.pe_halt_reason": "manual_protect_full_exit"}
            ),
            positions=[],
        )
        assert snap["armed"] is False
        assert "pe_side_halted" in snap["hard_blocked_reasons"]
    finally:
        for p in patches:
            p.stop()


def test_blocked_when_protect_in_book_manage_pe():
    patches = _base_patches()
    for p in patches:
        p.start()
    try:
        st = _armed_state(**{"ato.pe_ato_active": True, "ato.pe_protect_symbol": "NIFTY24900PE"})
        positions = [{"symbol": "NIFTY24900PE", "qty": 65}]
        snap = compute_ato_readiness(state=st, positions=positions)
        assert snap["armed"] is False
        assert "pe_protect_in_book" in snap["hard_blocked_reasons"]
    finally:
        for p in patches:
            p.stop()


def test_blocked_when_datafeedbot_down():
    patches = _base_patches(dfb=False)
    for p in patches:
        p.start()
    try:
        snap = compute_ato_readiness(state=_armed_state(), positions=[])
        assert snap["armed"] is False
        assert "datafeedbot_down" in snap["hard_blocked_reasons"]
    finally:
        for p in patches:
            p.stop()

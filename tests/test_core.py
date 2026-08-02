"""Tests for core.config, core.state, core.event_bus, core.utils, core.token_store."""

import time


class TestConfig:

    def test_dot_notation_get(self, config):
        assert config.get("strategy.lot_size") == 65
        assert config.get("broker.client_code") == "TEST"

    def test_nested_get(self, config):
        assert config.get("modules.ato_protection.enabled") is True

    def test_default_value(self, config):
        assert config.get("nonexistent.key", "fallback") == "fallback"

    def test_section(self, config):
        strat = config.get("strategy")
        assert isinstance(strat, dict)
        assert strat["lot_size"] == 65


class TestState:

    def test_set_and_get(self, state):
        state.set("foo.bar", 42)
        assert state.get("foo.bar") == 42

    def test_persistence(self, state, tmp_path):
        state.set("test_key", "hello")
        # Create a new StateManager reading the same file
        from core.state import StateManager

        state2 = StateManager(path=state._path)
        assert state2.get("test_key") == "hello"

    def test_reset(self, state):
        state.set("custom", "data")
        state.reset(backup=False)
        assert state.get("custom") is None
        assert state.get("session_id") is not None

    def test_default_on_missing_key(self, state):
        assert state.get("missing.path", "default") == "default"


class TestEventBus:

    def test_publish_subscribe(self, event_bus):
        from core.event_bus import Event

        received = []
        event_bus.subscribe(Event.BROKER_CONNECTED, lambda e, d: received.append(d))
        event_bus.publish(Event.BROKER_CONNECTED, {"status": "ok"})
        assert len(received) == 1
        assert received[0]["status"] == "ok"

    def test_unsubscribe(self, event_bus):
        from core.event_bus import Event

        received = []

        def cb(e, d):
            received.append(d)

        event_bus.subscribe(Event.BROKER_CONNECTED, cb)
        event_bus.unsubscribe(Event.BROKER_CONNECTED, cb)
        event_bus.publish(Event.BROKER_CONNECTED, {"status": "ok"})
        assert len(received) == 0

    def test_history(self, event_bus):
        from core.event_bus import Event

        event_bus.publish(Event.MTM_UPDATE, {"pnl": 100})
        event_bus.publish(Event.MTM_UPDATE, {"pnl": 200})
        history = event_bus.get_history(Event.MTM_UPDATE)
        assert len(history) == 2


class TestUtils:

    def test_round_to_strike(self):
        from core.utils import round_to_strike

        assert round_to_strike(25234.6) == 25250
        assert round_to_strike(25200.0) == 25200
        assert round_to_strike(25224.9) == 25200

    def test_center_line(self):
        from core.utils import center_line

        assert center_line(25234.6) == 25250

    def test_calculate_strikes(self):
        from core.utils import calculate_strikes

        # Batman structure: BUY is INSIDE (closer to ATM), SELL is outside
        s = calculate_strikes(25200, sell_distance=300, hedge_gap=250)
        assert s["center"] == 25200
        assert s["ce_sell"] == 25500  # ATM + 300 (outer)
        assert s["ce_buy"] == 25450  # ATM + 250 (inner, closer to spot)
        assert s["pe_sell"] == 24900  # ATM − 300 (outer)
        assert s["pe_buy"] == 24950  # ATM − 250 (inner, closer to spot)
        assert s["sell_otm"] == 6
        assert s["buy_otm"] == 5

    def test_otm_count_from_distance(self):
        from core.utils import otm_count_from_distance

        assert otm_count_from_distance(300) == 6
        assert otm_count_from_distance(550) == 11

    def test_fmt_rupees(self):
        from core.utils import fmt_rupees

        assert "₹" in fmt_rupees(12345.67)
        assert "-₹" in fmt_rupees(-500)
        assert "-₹" in fmt_rupees(-500)


class TestEntryWindow:
    """Unit tests for entry_date_this_week() and is_entry_window()."""

    def test_normal_wednesday_is_entry(self):
        """A regular (non-holiday) Wednesday is the entry day."""
        from datetime import date

        from core.utils import is_entry_window

        # 2026-03-11 is a Wednesday and NOT an NSE holiday
        assert is_entry_window(entry_weekday=2, ref=date(2026, 3, 11)) is True

    def test_thursday_is_not_entry_when_wednesday_is_fine(self):
        """Thursday is not the entry day when Wednesday was a normal trading day."""
        from datetime import date

        from core.utils import is_entry_window

        # 2026-03-12 is Thursday; 2026-03-11 (Wednesday) was fine
        assert is_entry_window(entry_weekday=2, ref=date(2026, 3, 12)) is False

    def test_holiday_wednesday_shifts_entry_to_thursday(self):
        """When Wednesday is an NSE holiday, Thursday becomes the entry day."""
        from datetime import date

        from core.utils import entry_date_this_week, is_entry_window

        # 2026-10-21 is Wednesday AND an NSE holiday (Dussehra)
        wed_holiday = date(2026, 10, 21)
        thu_entry = date(2026, 10, 22)
        assert entry_date_this_week(entry_weekday=2, ref=wed_holiday) == thu_entry
        # Wednesday itself is a holiday — NOT an entry day
        assert is_entry_window(entry_weekday=2, ref=wed_holiday) is False
        # Thursday IS the entry day
        assert is_entry_window(entry_weekday=2, ref=thu_entry) is True

    def test_friday_is_not_entry_even_after_holiday_wednesday(self):
        """Friday is not the entry day even if Wednesday was a holiday (Thu was entry)."""
        from datetime import date

        from core.utils import is_entry_window

        # Entry already fell on Thursday 2026-10-22; Friday should not re-trigger
        assert is_entry_window(entry_weekday=2, ref=date(2026, 10, 23)) is False

    def test_extra_holidays_param_respected(self):
        """extra_holidays shifts entry forward past those dates too."""
        from datetime import date

        from core.utils import entry_date_this_week

        # Force Wednesday 2026-03-11 to be treated as a holiday via extra_holidays
        extra = [date(2026, 3, 11)]
        result = entry_date_this_week(entry_weekday=2, ref=date(2026, 3, 11), extra_holidays=extra)
        assert result == date(2026, 3, 12)  # shifted to Thursday


class TestOptionSymbolUtils:
    """
    Tests for parse_option_symbol() and build_ato_symbols() in core.utils.

    The ATO protect symbol must:
      1. Use the SAME expiry prefix as the deployed sell leg.
      2. Be exactly one strike_step further OTM (CE: +50, PE: −50).
      3. Work for any expiry date — no hardcoding.
    """

    # ── parse_option_symbol ───────────────────────────────────────────────────

    def test_parse_valid_ce_symbol(self):
        from core.utils import parse_option_symbol

        prefix, strike, opt_type = parse_option_symbol("NIFTY25APR23000CE")
        assert prefix == "NIFTY25APR"
        assert strike == 23000
        assert opt_type == "CE"

    def test_parse_valid_pe_symbol(self):
        from core.utils import parse_option_symbol

        prefix, strike, opt_type = parse_option_symbol("NIFTY25APR22000PE")
        assert prefix == "NIFTY25APR"
        assert strike == 22000
        assert opt_type == "PE"

    def test_parse_different_expiry_month(self):
        """Expiry in a different month — prefix varies, logic stays the same."""
        from core.utils import parse_option_symbol

        prefix, strike, opt_type = parse_option_symbol("NIFTY25JAN24500CE")
        assert prefix == "NIFTY25JAN"
        assert strike == 24500
        assert opt_type == "CE"

    def test_parse_invalid_symbol_returns_none_triple(self):
        from core.utils import parse_option_symbol

        assert parse_option_symbol("INVALID") == (None, None, None)
        assert parse_option_symbol("") == (None, None, None)
        assert parse_option_symbol("NIFTY25APR") == (None, None, None)  # no strike/type

    # ── build_ato_symbols ─────────────────────────────────────────────────────

    def test_ato_symbols_same_expiry_as_legs(self):
        """ATO symbols must share the exact expiry prefix of the sell legs.

        User example: legs deployed for 13 Apr, ATO must also be 13 Apr.
        NOT next week or a different expiry.
        """
        from core.utils import build_ato_symbols

        ato = build_ato_symbols(
            ce_sell_symbol="NIFTY25APR23000CE",
            pe_sell_symbol="NIFTY25APR22000PE",
        )
        # Both ATO symbols carry the same "NIFTY25APR" prefix as the legs
        assert ato["ce_protect_symbol"] == "NIFTY25APR23050CE"
        assert ato["pe_protect_symbol"] == "NIFTY25APR21950PE"

    def test_ato_ce_strike_is_one_step_higher(self):
        """CE ATO strike = ce_sell_strike + 50 (one step more OTM on call side)."""
        from core.utils import build_ato_symbols

        ato = build_ato_symbols("NIFTY25APR23000CE", "NIFTY25APR22000PE")
        assert ato["ce_protect_strike"] == 23050  # 23000 + 50

    def test_ato_pe_strike_is_one_step_lower(self):
        """PE ATO strike = pe_sell_strike − 50 (one step more OTM on put side)."""
        from core.utils import build_ato_symbols

        ato = build_ato_symbols("NIFTY25APR23000CE", "NIFTY25APR22000PE")
        assert ato["pe_protect_strike"] == 21950  # 22000 − 50

    def test_ato_different_expiry_still_correct(self):
        """Works with any expiry — 7 Apr, 13 Apr, any week."""
        from core.utils import build_ato_symbols

        # Legs on 7 Apr expiry
        ato_apr7 = build_ato_symbols("NIFTY25APR24800CE", "NIFTY25APR24200PE")
        assert ato_apr7["ce_protect_symbol"] == "NIFTY25APR24850CE"
        assert ato_apr7["pe_protect_symbol"] == "NIFTY25APR24150PE"

        # Same strikes but on January expiry — prefix must differ
        ato_jan = build_ato_symbols("NIFTY25JAN24800CE", "NIFTY25JAN24200PE")
        assert ato_jan["ce_protect_symbol"] == "NIFTY25JAN24850CE"
        assert ato_jan["pe_protect_symbol"] == "NIFTY25JAN24150PE"

    def test_ato_symbols_cannot_mix_expiries(self):
        """CE and PE sell legs must be on the same expiry in production.
        The function derives each ATO symbol independently from its own leg —
        so passing mismatched expiries produces ATO symbols on their respective
        (different) expiries.  This test documents that behavior so it is
        caught if the wizard ever passes mismatched legs.
        """
        from core.utils import build_ato_symbols

        ato = build_ato_symbols(
            ce_sell_symbol="NIFTY25APR23000CE",  # Apr expiry
            pe_sell_symbol="NIFTY25MAY22000PE",  # May expiry (mismatched!)
        )
        # Each ATO symbol follows its own sell leg's expiry
        assert "APR" in ato["ce_protect_symbol"]
        assert "MAY" in ato["pe_protect_symbol"]

    def test_ato_invalid_symbol_returns_none(self):
        """If either sell symbol cannot be parsed, all ATO values are None/0."""
        from core.utils import build_ato_symbols

        ato = build_ato_symbols("INVALID_SYMBOL", "NIFTY25APR22000PE")
        assert ato["ce_protect_symbol"] is None
        assert ato["ce_protect_strike"] == 0
        assert ato["pe_protect_symbol"] is None


class TestTokenStore:
    """Tests for core.token_store.TokenStore — token persistence to disk."""

    def test_save_and_load_roundtrip(self, tmp_path):
        from core.token_store import TokenStore

        store = TokenStore(path=tmp_path / "access_token.json")
        store.save("my_jwt_token_abc123")
        token, saved_at = store.load()
        assert token == "my_jwt_token_abc123"
        assert saved_at is not None

    def test_absent_token_returns_none(self, tmp_path):
        from core.token_store import TokenStore

        store = TokenStore(path=tmp_path / "nonexistent.json")
        token, saved_at = store.load()
        assert token is None
        assert saved_at is None

    def test_fresh_token_not_expired(self, tmp_path):
        from core.token_store import TokenStore

        store = TokenStore(path=tmp_path / "access_token.json")
        store.save("fresh_token")
        assert store.is_expired() is False

    def test_absent_token_is_expired(self, tmp_path):
        from core.token_store import TokenStore

        store = TokenStore(path=tmp_path / "access_token.json")
        assert store.is_expired() is True  # no file → treat as expired

    def test_token_age_hours_is_near_zero(self, tmp_path):
        from core.token_store import TokenStore

        store = TokenStore(path=tmp_path / "access_token.json")
        store.save("token")
        age = store.token_age_hours()
        assert age is not None
        assert age < 0.01  # just saved — well under 1 minute

    def test_token_age_returns_none_when_absent(self, tmp_path):
        from core.token_store import TokenStore

        store = TokenStore(path=tmp_path / "access_token.json")
        assert store.token_age_hours() is None

    def test_clear_removes_file(self, tmp_path):
        from core.token_store import TokenStore

        store = TokenStore(path=tmp_path / "access_token.json")
        store.save("token")
        store.clear()
        assert not (tmp_path / "access_token.json").exists()
        token, _ = store.load()
        assert token is None

    def test_overwrite_updates_saved_at(self, tmp_path):
        """Saving a second time overwrites the first entry."""

        from core.token_store import TokenStore

        store = TokenStore(path=tmp_path / "access_token.json")
        store.save("first_token")
        _, saved_at_1 = store.load()
        time.sleep(0.05)  # ensure timestamp differs
        store.save("second_token")
        token, saved_at_2 = store.load()
        assert token == "second_token"
        assert saved_at_2 >= saved_at_1

    def test_corrupted_file_returns_none(self, tmp_path):
        """A corrupted JSON file is treated as absent — no crash."""
        from core.token_store import TokenStore

        p = tmp_path / "access_token.json"
        p.write_text("NOT VALID JSON {{{", encoding="utf-8")
        store = TokenStore(path=p)
        token, saved_at = store.load()
        assert token is None
        assert saved_at is None

    def test_is_expired_with_tolerance(self, tmp_path):
        """is_expired(extra_tolerance_hours) reduces effective TTL."""
        from core.token_store import TokenStore

        store = TokenStore(path=tmp_path / "access_token.json")
        store.save("token")
        # With tolerance = 23.999h, effective TTL = 0.001h ≈ 3.6s —
        # a just-saved token has age ≈ 0s so it is NOT expired yet.
        assert store.is_expired(extra_tolerance_hours=23.999) is False

"""
tests/test_signals.py
======================
Unit tests for the EntrySignal and ExitSignal engine.
Run with: pytest tests/test_signals.py -v
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.signals import SignalEngine, EntrySignal, ExitSignal


def make_perfect_entry_snapshot() -> dict:
    """All entry conditions met."""
    return {
        "price": 150.0,
        "ema_20": 145.0,
        "ema_50": 140.0,
        "price_above_ema_20": True,
        "price_above_ema_50": True,
        "rsi": 55.0,
        "rsi_in_entry_range": True,
        "rsi_overbought": False,
        "rsi_extreme_overbought": False,
        "macd": 1.5,
        "macd_signal": 1.0,
        "macd_hist": 0.5,
        "macd_above_signal": True,
        "macd_bullish_crossover": True,
        "macd_hist_expanding": True,
        "macd_bearish_crossover": False,
        "volume_ratio": 1.8,
        "volume_confirmed": True,
        "volume_drying": False,
        "signal_strong_bull": True,
        "signal_entry_criteria_met": True,
        "atr": 2.5,
        "suggested_stop_distance": 3.75,
        "bb_upper": 160.0,
        "bb_lower": 140.0,
        "bb_squeeze": True,
    }


def make_failed_entry_snapshot() -> dict:
    """Most conditions NOT met."""
    return {
        "price": 130.0,
        "ema_20": 145.0,
        "ema_50": 150.0,
        "price_above_ema_20": False,
        "price_above_ema_50": False,
        "rsi": 72.0,
        "rsi_in_entry_range": False,
        "rsi_overbought": True,
        "rsi_extreme_overbought": True,
        "macd": -1.0,
        "macd_signal": 0.5,
        "macd_hist": -1.5,
        "macd_above_signal": False,
        "macd_bullish_crossover": False,
        "macd_hist_expanding": False,
        "macd_bearish_crossover": True,
        "volume_ratio": 0.6,
        "volume_confirmed": False,
        "volume_drying": True,
        "signal_strong_bull": False,
        "signal_entry_criteria_met": False,
        "atr": 2.5,
        "suggested_stop_distance": 3.75,
        "bb_upper": 145.0,
        "bb_lower": 125.0,
        "bb_squeeze": False,
    }


def make_bull_regime() -> dict:
    return {"regime": "bull", "spy_above_ema_50": True, "vix": 14.0}


class TestEntrySignal:
    def test_entry_signal_has_ticker(self):
        signal = EntrySignal(ticker="NVDA")
        assert signal.ticker == "NVDA"

    def test_all_clear_requires_all_gates(self):
        signal = EntrySignal(ticker="TEST")
        signal.trend_confirmed = True
        signal.rsi_in_range = True
        signal.macd_bullish = True
        signal.volume_confirmed = True
        signal.catalyst_present = True
        signal.rr_ratio_valid = True
        signal.confidence_sufficient = True
        assert signal.all_clear is True

    def test_all_clear_fails_if_one_gate_fails(self):
        signal = EntrySignal(ticker="TEST")
        signal.trend_confirmed = True
        signal.rsi_in_range = True
        signal.macd_bullish = True
        signal.volume_confirmed = True
        signal.catalyst_present = False  # ← one gate fails
        signal.rr_ratio_valid = True
        signal.confidence_sufficient = True
        assert signal.all_clear is False

    def test_fail_reasons_populated_on_failure(self):
        signal = EntrySignal(ticker="TEST")
        signal.trend_confirmed = False
        signal.fail_reasons = ["Price below 20 EMA"]
        assert len(signal.fail_reasons) > 0


class TestSignalEngine:
    def setup_method(self):
        self.engine = SignalEngine()

    def test_evaluate_entry_returns_entry_signal(self):
        snap = make_perfect_entry_snapshot()
        result = self.engine.evaluate_entry(
            ticker="NVDA",
            snapshot=snap,
            market_regime=make_bull_regime(),
            manual_stop=146.25,
            manual_target=161.25,
        )
        assert isinstance(result, EntrySignal)

    def test_perfect_entry_passes_technical_gates(self):
        snap = make_perfect_entry_snapshot()
        result = self.engine.evaluate_entry(
            ticker="NVDA",
            snapshot=snap,
            market_regime=make_bull_regime(),
            manual_stop=146.25,
            manual_target=161.25,
        )
        assert result.trend_confirmed is True
        assert result.rsi_in_range is True
        assert result.macd_bullish is True
        assert result.volume_confirmed is True

    def test_failed_entry_fails_gates(self):
        snap = make_failed_entry_snapshot()
        result = self.engine.evaluate_entry(
            ticker="TEST",
            snapshot=snap,
            market_regime=make_bull_regime(),
            manual_stop=127.5,
            manual_target=133.0,
        )
        assert result.trend_confirmed is False

    def test_good_rr_passes_rr_gate(self):
        snap = make_perfect_entry_snapshot()
        result = self.engine.evaluate_entry(
            ticker="TEST",
            snapshot=snap,
            market_regime=make_bull_regime(),
            manual_stop=144.0,   # 6 pts risk
            manual_target=162.0,  # 12 pts reward = 2:1
        )
        assert result.rr_ratio_valid is True

    def test_poor_rr_fails_rr_gate(self):
        snap = make_perfect_entry_snapshot()
        result = self.engine.evaluate_entry(
            ticker="TEST",
            snapshot=snap,
            market_regime=make_bull_regime(),
            manual_stop=149.0,   # 1 pt risk
            manual_target=151.0,  # 1 pt reward = 1:1 (fails 2:1 minimum)
        )
        assert result.rr_ratio_valid is False

    def test_entry_fail_reasons_populated(self):
        snap = make_failed_entry_snapshot()
        result = self.engine.evaluate_entry(
            ticker="TEST",
            snapshot=snap,
            market_regime={"regime": "bear"},
            manual_stop=127.0,
            manual_target=132.0,
        )
        # Should have several failure reasons
        assert len(result.fail_reasons) >= 1

    def test_summary_str_not_empty(self):
        snap = make_perfect_entry_snapshot()
        result = self.engine.evaluate_entry(
            ticker="NVDA",
            snapshot=snap,
            market_regime=make_bull_regime(),
            manual_stop=146.25,
            manual_target=162.0,
        )
        summary = result.summary_str()
        assert "NVDA" in summary
        assert len(summary) > 10

    def test_alert_str_sms_length(self):
        snap = make_perfect_entry_snapshot()
        result = self.engine.evaluate_entry(
            ticker="NVDA",
            snapshot=snap,
            market_regime=make_bull_regime(),
            manual_stop=146.25,
            manual_target=162.0,
        )
        alert = result.alert_str()
        assert len(alert) <= 320  # Should be SMS-friendly


class TestExitSignal:
    def setup_method(self):
        self.engine = SignalEngine()

    def test_stop_hit_triggers_exit(self):
        # Current price at or below stop
        snap = make_perfect_entry_snapshot()
        snap["price"] = 143.0  # Below our entry stop of 145

        result = self.engine.evaluate_exit(
            position={"ticker": "NVDA", "id": "t1", "entry_price": 150.0, "stop_loss": 145.0, "target": 165.0, "shares": 10},
            snapshot=snap,
        )
        assert isinstance(result, ExitSignal)
        assert result.stop_loss_hit is True

    def test_rsi_overbought_triggers_exit_warning(self):
        snap = make_perfect_entry_snapshot()
        snap["rsi"] = 78.0
        snap["rsi_extreme_overbought"] = True

        result = self.engine.evaluate_exit(
            position={"ticker": "TEST", "id": "t2", "entry_price": 140.0, "stop_loss": 135.0, "target": 160.0, "shares": 10},
            snapshot=snap,
        )
        assert result.rsi_overbought is True

    def test_macd_bearish_cross_triggers_exit_warning(self):
        snap = make_perfect_entry_snapshot()
        snap["macd_bearish_crossover"] = True
        snap["macd_above_signal"] = False

        result = self.engine.evaluate_exit(
            position={"ticker": "TEST", "id": "t3", "entry_price": 140.0, "stop_loss": 135.0, "target": 160.0, "shares": 10},
            snapshot=snap,
        )
        assert result.macd_reversal is True

    def test_target_hit_triggers_exit(self):
        snap = make_perfect_entry_snapshot()
        snap["price"] = 165.5  # Above target of 165

        result = self.engine.evaluate_exit(position={"ticker": "TEST", "id": "t", "entry_price": 150.0, "stop_loss": 144.0, "target": 165.0, "shares": 10}, snapshot=snap)
        assert result.target_reached is True

    def test_volume_drying_flags_concern(self):
        snap = make_perfect_entry_snapshot()
        snap["volume_drying"] = True

        result = self.engine.evaluate_exit(position={"ticker": "TEST", "id": "t", "entry_price": 145.0, "stop_loss": 140.0, "target": 160.0, "shares": 10}, snapshot=snap)
        assert result.volume_drying is True

    def test_no_exit_trigger_when_all_good(self):
        snap = make_perfect_entry_snapshot()
        # Price holding above entry, not near stop or target
        result = self.engine.evaluate_exit(position={"ticker": "NVDA", "id": "t", "entry_price": 145.0, "stop_loss": 138.0, "target": 170.0, "shares": 10}, snapshot=snap)
        assert result.stop_loss_hit is False
        assert result.target_reached is False
        # RSI is 55 — not overbought
        assert result.rsi_overbought is False

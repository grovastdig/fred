"""
tests/test_confidence.py
========================
Unit tests for the Confidence Meter scoring system.
Run with: pytest tests/test_confidence.py -v
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.confidence import ConfidenceMeter, ConfidenceScore


def make_bullish_indicators() -> dict:
    """Strong bullish technical setup."""
    return {
        "price": 150.0,
        "ema_20": 145.0,
        "ema_50": 140.0,
        "ema_200": 130.0,
        "price_above_ema_20": True,
        "price_above_ema_50": True,
        "price_above_ema_200": True,
        "ema_20_trending_up": True,
        "rsi": 55.0,
        "rsi_in_entry_range": True,
        "rsi_overbought": False,
        "rsi_oversold": False,
        "rsi_extreme_overbought": False,
        "macd": 1.5,
        "macd_signal": 1.0,
        "macd_hist": 0.5,
        "macd_above_signal": True,
        "macd_bullish_crossover": True,
        "macd_hist_expanding": True,
        "macd_bearish_crossover": False,
        "bb_squeeze": True,
        "volume_ratio": 1.8,
        "volume_confirmed": True,
        "volume_spike": False,
        "volume_drying": False,
        "signal_strong_bull": True,
        "signal_entry_criteria_met": True,
        "atr": 2.5,
        "golden_cross": False,
        "death_cross": False,
    }


def make_bearish_indicators() -> dict:
    """Weak/bearish technical setup — should score low."""
    return {
        "price": 100.0,
        "ema_20": 110.0,
        "ema_50": 115.0,
        "ema_200": 120.0,
        "price_above_ema_20": False,
        "price_above_ema_50": False,
        "price_above_ema_200": False,
        "ema_20_trending_up": False,
        "rsi": 72.0,
        "rsi_in_entry_range": False,
        "rsi_overbought": True,
        "rsi_oversold": False,
        "rsi_extreme_overbought": True,
        "macd": -1.5,
        "macd_signal": -1.0,
        "macd_hist": -0.5,
        "macd_above_signal": False,
        "macd_bullish_crossover": False,
        "macd_hist_expanding": False,
        "macd_bearish_crossover": True,
        "bb_squeeze": False,
        "volume_ratio": 0.7,
        "volume_confirmed": False,
        "volume_spike": False,
        "volume_drying": True,
        "signal_strong_bull": False,
        "signal_entry_criteria_met": False,
        "atr": 2.5,
        "golden_cross": False,
        "death_cross": True,
    }


def make_bull_regime() -> dict:
    return {
        "regime": "bull",
        "spy_above_ema_50": True,
        "vix": 14.5,
        "spy_price": 500.0,
    }


def make_bear_regime() -> dict:
    return {
        "regime": "bear",
        "spy_above_ema_50": False,
        "vix": 30.0,
        "spy_price": 480.0,
    }


def make_catalyst(strength: str = "strong") -> dict:
    return {
        "type": "earnings",
        "strength": strength,
        "description": "Q3 earnings beat by 15%",
        "count": 1,
    }


class TestConfidenceScoreDataclass:
    def test_default_total(self):
        score = ConfidenceScore(ticker="TEST")
        assert score.total == 0.0

    def test_total_sums_components(self):
        score = ConfidenceScore(ticker="TEST")
        score.technical_setup = 20
        score.volume_confirmation = 10
        score.catalyst_strength = 15
        assert score.total == pytest.approx(20 + 10 + 15 + 0 + 0 + 0 + 0)

    def test_label_conviction(self):
        score = ConfidenceScore(ticker="TEST")
        score.technical_setup = 25
        score.volume_confirmation = 15
        score.catalyst_strength = 20
        score.sector_strength = 10
        score.market_regime = 10
        score.risk_reward_ratio = 10
        score.political_tailwind = 10
        assert score.label in ("🔥 Conviction", "✅ Strong")

    def test_label_skip_low_score(self):
        score = ConfidenceScore(ticker="TEST")
        score.technical_setup = 5
        assert score.label == "❌ Skip"

    def test_should_trade_above_threshold(self):
        score = ConfidenceScore(ticker="TEST")
        score.technical_setup = 25
        score.volume_confirmation = 15
        score.catalyst_strength = 15
        assert score.should_trade is True

    def test_should_not_trade_below_threshold(self):
        score = ConfidenceScore(ticker="TEST")
        score.technical_setup = 5
        assert score.should_trade is False

    def test_position_size_conviction(self):
        score = ConfidenceScore(ticker="TEST")
        # Fill all components for conviction-level score
        score.technical_setup = 25
        score.volume_confirmation = 15
        score.catalyst_strength = 20
        score.sector_strength = 10
        score.market_regime = 10
        score.risk_reward_ratio = 10
        score.political_tailwind = 10
        assert score.position_size_pct >= 25

    def test_position_size_zero_for_skip(self):
        score = ConfidenceScore(ticker="TEST")
        score.technical_setup = 2
        assert score.position_size_pct == 0.0  # skip = 0


class TestConfidenceMeterScoring:
    def setup_method(self):
        self.meter = ConfidenceMeter()

    def test_returns_confidence_score(self):
        result = self.meter.score(
            ticker="NVDA",
            technical_data=make_bullish_indicators(),
        )
        assert isinstance(result, ConfidenceScore)

    def test_bullish_setup_scores_higher_than_bearish(self):
        bull = self.meter.score(
            ticker="TEST",
            technical_data=make_bullish_indicators(),
            market_regime=make_bull_regime(),
        )
        bear = self.meter.score(
            ticker="TEST",
            technical_data=make_bearish_indicators(),
            market_regime=make_bear_regime(),
        )
        assert bull.total > bear.total

    def test_catalyst_increases_score(self):
        no_catalyst = self.meter.score(
            ticker="TEST",
            technical_data=make_bullish_indicators(),
        )
        with_catalyst = self.meter.score(
            ticker="TEST",
            technical_data=make_bullish_indicators(),
            catalyst=make_catalyst("strong"),
        )
        assert with_catalyst.total > no_catalyst.total

    def test_bull_regime_increases_score(self):
        neutral = self.meter.score(
            ticker="TEST",
            technical_data=make_bullish_indicators(),
        )
        bull = self.meter.score(
            ticker="TEST",
            technical_data=make_bullish_indicators(),
            market_regime=make_bull_regime(),
        )
        assert bull.total >= neutral.total

    def test_good_rr_increases_score(self):
        with_rr = self.meter.score(
            ticker="TEST",
            technical_data=make_bullish_indicators(),
            entry_price=150.0,
            stop_loss=144.0,   # 4% risk
            target_price=162.0,  # 8% gain = 2:1
        )
        without_rr = self.meter.score(
            ticker="TEST",
            technical_data=make_bullish_indicators(),
        )
        assert with_rr.total >= without_rr.total

    def test_score_never_exceeds_100(self):
        # Max everything out
        result = self.meter.score(
            ticker="TEST",
            technical_data=make_bullish_indicators(),
            catalyst=make_catalyst("strong"),
            market_regime=make_bull_regime(),
            entry_price=150.0,
            stop_loss=144.0,
            target_price=168.0,  # 3:1
            political_signal={"type": "trump_tweet", "direction": "bullish", "ticker": "TEST"},
        )
        assert result.total <= 100.0

    def test_score_never_negative(self):
        result = self.meter.score(
            ticker="TEST",
            technical_data=make_bearish_indicators(),
            market_regime=make_bear_regime(),
        )
        assert result.total >= 0.0

    def test_score_has_correct_ticker(self):
        result = self.meter.score("AAPL", make_bullish_indicators())
        assert result.ticker == "AAPL"

    def test_overbought_generates_warning(self):
        indicators = make_bullish_indicators()
        indicators["rsi"] = 82.0
        indicators["rsi_extreme_overbought"] = True
        result = self.meter.score("TEST", indicators)
        assert len(result.warnings) > 0

    def test_no_stop_generates_warning(self):
        result = self.meter.score(
            "TEST",
            make_bullish_indicators(),
            entry_price=150.0,
            # No stop_loss provided
        )
        assert any("stop" in w.lower() for w in result.warnings)

    def test_strong_catalyst_scores_more_than_weak(self):
        strong = self.meter.score(
            "TEST",
            make_bullish_indicators(),
            catalyst=make_catalyst("strong"),
        )
        weak = self.meter.score(
            "TEST",
            make_bullish_indicators(),
            catalyst=make_catalyst("weak"),
        )
        assert strong.total > weak.total

    def test_sms_format_not_empty(self):
        result = self.meter.score("NVDA", make_bullish_indicators())
        sms = result.to_sms()
        assert "NVDA" in sms
        assert len(sms) > 20

    def test_death_cross_generates_warning(self):
        indicators = make_bullish_indicators()
        indicators["death_cross"] = True
        result = self.meter.score("TEST", indicators)
        assert any("death" in w.lower() or "cross" in w.lower() for w in result.warnings)

    def test_volume_drying_generates_warning_on_position(self):
        indicators = make_bullish_indicators()
        indicators["volume_drying"] = True
        result = self.meter.score("TEST", indicators)
        # Volume drying is a warning
        assert result.volume_confirmation < 15  # Should not get full volume score

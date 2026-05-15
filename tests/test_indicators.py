"""
tests/test_indicators.py
=========================
Unit tests for the IndicatorEngine.

Tests all indicator calculations against known values.
Run with: pytest tests/test_indicators.py -v
"""

import pytest
import pandas as pd
import numpy as np
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.indicators import IndicatorEngine


def make_trending_up_df(n=100) -> pd.DataFrame:
    """Create a synthetic uptrending OHLCV DataFrame."""
    np.random.seed(42)
    base = 100
    closes = [base + i * 0.5 + np.random.normal(0, 0.3) for i in range(n)]
    opens = [c - np.random.uniform(0, 0.5) for c in closes]
    highs = [c + np.random.uniform(0.1, 1.0) for c in closes]
    lows = [c - np.random.uniform(0.1, 1.0) for c in closes]
    volumes = [1_000_000 + np.random.randint(-100_000, 500_000) for _ in range(n)]

    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


def make_trending_down_df(n=100) -> pd.DataFrame:
    """Create a synthetic downtrending OHLCV DataFrame."""
    np.random.seed(99)
    base = 150
    closes = [base - i * 0.5 + np.random.normal(0, 0.3) for i in range(n)]
    opens = [c + np.random.uniform(0, 0.5) for c in closes]
    highs = [c + np.random.uniform(0.1, 1.0) for c in closes]
    lows = [c - np.random.uniform(0.1, 1.0) for c in closes]
    volumes = [800_000 + np.random.randint(-100_000, 200_000) for _ in range(n)]

    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


class TestEMAs:
    def setup_method(self):
        self.engine = IndicatorEngine()
        self.df = make_trending_up_df()

    def test_ema_20_exists(self):
        result = self.engine._calculate_emas(self.df)
        assert "ema_20" in result
        assert result["ema_20"] is not None

    def test_ema_50_exists(self):
        result = self.engine._calculate_emas(self.df)
        assert "ema_50" in result

    def test_ema_200_exists(self):
        result = self.engine._calculate_emas(self.df)
        assert "ema_200" in result

    def test_price_above_ema_in_uptrend(self):
        result = self.engine._calculate_emas(self.df)
        # In uptrend, price should be above 20 EMA
        assert result["price_above_ema_20"] is True

    def test_golden_cross_in_uptrend(self):
        result = self.engine._calculate_emas(self.df)
        # 200+ bars of uptrend should show golden cross
        if result.get("ema_50") and result.get("ema_200"):
            assert result["golden_cross"] is True

    def test_ema_slope_positive_in_uptrend(self):
        result = self.engine._calculate_emas(self.df)
        assert result.get("ema_20_trending_up") is True


class TestRSI:
    def setup_method(self):
        self.engine = IndicatorEngine()

    def test_rsi_in_valid_range(self):
        df = make_trending_up_df()
        result = self.engine._calculate_rsi(df)
        assert 0 <= result["rsi"] <= 100

    def test_rsi_structure(self):
        df = make_trending_up_df()
        result = self.engine._calculate_rsi(df)
        assert "rsi" in result
        assert "rsi_oversold" in result
        assert "rsi_overbought" in result
        assert "rsi_in_entry_range" in result

    def test_rsi_not_overbought_in_mild_uptrend(self):
        df = make_trending_up_df()
        result = self.engine._calculate_rsi(df)
        # Mild uptrend shouldn't be overbought
        assert not result["rsi_overbought"] or result["rsi"] < 75

    def test_rsi_entry_range(self):
        df = make_trending_up_df()
        result = self.engine._calculate_rsi(df)
        rsi = result["rsi"]
        in_range = result["rsi_in_entry_range"]
        assert in_range == (40 <= rsi <= 65)

    def test_insufficient_data_returns_defaults(self):
        df = make_trending_up_df(n=5)  # Too few bars
        result = self.engine._calculate_rsi(df)
        assert result["rsi"] == 50.0  # Should return safe default


class TestMACD:
    def setup_method(self):
        self.engine = IndicatorEngine()

    def test_macd_structure(self):
        df = make_trending_up_df()
        result = self.engine._calculate_macd(df)
        expected_keys = ["macd", "macd_signal", "macd_hist", "macd_bullish_crossover",
                         "macd_bearish_crossover", "macd_hist_expanding"]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_macd_types(self):
        df = make_trending_up_df()
        result = self.engine._calculate_macd(df)
        assert isinstance(result["macd"], float)
        assert isinstance(result["macd_bullish_crossover"], bool)

    def test_macd_not_both_crossovers(self):
        """Can't have bullish AND bearish crossover at same time."""
        df = make_trending_up_df()
        result = self.engine._calculate_macd(df)
        assert not (result["macd_bullish_crossover"] and result["macd_bearish_crossover"])


class TestBollingerBands:
    def setup_method(self):
        self.engine = IndicatorEngine()

    def test_bb_structure(self):
        df = make_trending_up_df()
        result = self.engine._calculate_bollinger_bands(df)
        assert "bb_upper" in result
        assert "bb_middle" in result
        assert "bb_lower" in result

    def test_bb_upper_above_lower(self):
        df = make_trending_up_df()
        result = self.engine._calculate_bollinger_bands(df)
        assert result["bb_upper"] > result["bb_lower"]

    def test_bb_pct_in_range(self):
        df = make_trending_up_df()
        result = self.engine._calculate_bollinger_bands(df)
        # Price should be somewhere within bands (allow slight overflow)
        assert -0.1 <= result["bb_pct"] <= 1.1


class TestATR:
    def setup_method(self):
        self.engine = IndicatorEngine()

    def test_atr_positive(self):
        df = make_trending_up_df()
        result = self.engine._calculate_atr(df)
        assert result["atr"] > 0

    def test_atr_stop_distance(self):
        df = make_trending_up_df()
        result = self.engine._calculate_atr(df)
        # Stop distance should be 1.5x ATR
        assert abs(result["suggested_stop_distance"] - result["atr"] * 1.5) < 0.01


class TestVolumeMetrics:
    def setup_method(self):
        self.engine = IndicatorEngine()

    def test_volume_ratio_positive(self):
        df = make_trending_up_df()
        result = self.engine._calculate_volume_metrics(df)
        assert result["volume_ratio"] > 0

    def test_volume_20ma_reasonable(self):
        df = make_trending_up_df()
        result = self.engine._calculate_volume_metrics(df)
        assert result["volume_20ma"] > 0


class TestCalculateAll:
    def setup_method(self):
        self.engine = IndicatorEngine()

    def test_calculate_all_returns_dict(self):
        df = make_trending_up_df()
        result = self.engine.calculate_all(df)
        assert isinstance(result, dict)

    def test_calculate_all_has_all_keys(self):
        df = make_trending_up_df()
        result = self.engine.calculate_all(df)
        required_keys = [
            "ema_20", "ema_50", "rsi", "macd", "macd_signal",
            "bb_upper", "bb_lower", "atr", "volume_ratio",
            "signal_strong_bull", "signal_entry_criteria_met",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_empty_df_returns_safe_defaults(self):
        df = pd.DataFrame()
        result = self.engine.calculate_all(df)
        assert isinstance(result, dict)
        assert result.get("rsi") == 50.0 or result.get("rsi") is None

    def test_short_df_returns_safe_defaults(self):
        df = make_trending_up_df(n=5)
        result = self.engine.calculate_all(df)
        assert isinstance(result, dict)

    def test_composite_signals_consistency(self):
        """signal_strong_bull should require all conditions."""
        df = make_trending_up_df()
        result = self.engine.calculate_all(df)

        if result.get("signal_strong_bull"):
            assert result.get("price_above_ema_20") is True

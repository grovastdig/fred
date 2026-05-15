"""
tests/conftest.py
=================
Shared pytest fixtures for Fred's test suite.
"""

import pytest
import pandas as pd
import numpy as np
import sys
import os

# Project root on path for all tests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Synthetic Market Data ─────────────────────────────────────────────────────

@pytest.fixture
def trending_up_df():
    """100-bar uptrending OHLCV DataFrame."""
    np.random.seed(42)
    n = 100
    base = 100.0
    closes = [base + i * 0.5 + np.random.normal(0, 0.3) for i in range(n)]
    opens = [c - np.random.uniform(0, 0.5) for c in closes]
    highs = [c + np.random.uniform(0.1, 1.0) for c in closes]
    lows = [c - np.random.uniform(0.1, 1.0) for c in closes]
    volumes = [1_000_000 + np.random.randint(-100_000, 500_000) for _ in range(n)]
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    })


@pytest.fixture
def trending_down_df():
    """100-bar downtrending OHLCV DataFrame."""
    np.random.seed(99)
    n = 100
    base = 150.0
    closes = [base - i * 0.5 + np.random.normal(0, 0.3) for i in range(n)]
    opens = [c + np.random.uniform(0, 0.5) for c in closes]
    highs = [c + np.random.uniform(0.1, 1.0) for c in closes]
    lows = [c - np.random.uniform(0.1, 1.0) for c in closes]
    volumes = [800_000 + np.random.randint(-100_000, 200_000) for _ in range(n)]
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    })


@pytest.fixture
def choppy_df():
    """100-bar choppy sideways market DataFrame."""
    np.random.seed(7)
    n = 100
    closes = [100.0 + np.random.normal(0, 2.0) for _ in range(n)]
    opens = [c + np.random.uniform(-1, 1) for c in closes]
    highs = [c + np.random.uniform(0.5, 2.0) for c in closes]
    lows = [c - np.random.uniform(0.5, 2.0) for c in closes]
    volumes = [500_000 + np.random.randint(-100_000, 100_000) for _ in range(n)]
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    })


@pytest.fixture
def minimal_df():
    """Minimal 5-bar DataFrame — triggers safe defaults."""
    return pd.DataFrame({
        "open":   [100, 101, 102, 101, 103],
        "high":   [102, 103, 104, 103, 105],
        "low":    [99,  100, 101, 100, 102],
        "close":  [101, 102, 103, 102, 104],
        "volume": [1_000_000] * 5,
    })


# ── Snapshot Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def bullish_snapshot():
    """Full bullish market snapshot dict."""
    return {
        "ticker": "NVDA",
        "price": 150.0,
        "ema_9": 147.0,
        "ema_20": 145.0,
        "ema_50": 140.0,
        "ema_200": 120.0,
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
        "bb_upper": 160.0,
        "bb_lower": 140.0,
        "bb_middle": 150.0,
        "bb_squeeze": True,
        "volume_ratio": 1.8,
        "volume_20ma": 5_000_000,
        "volume_confirmed": True,
        "volume_spike": False,
        "volume_drying": False,
        "signal_strong_bull": True,
        "signal_entry_criteria_met": True,
        "atr": 2.5,
        "suggested_stop_distance": 3.75,
        "golden_cross": False,
        "death_cross": False,
    }


@pytest.fixture
def bearish_snapshot():
    """Full bearish market snapshot dict."""
    return {
        "ticker": "TEST",
        "price": 100.0,
        "ema_9": 108.0,
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
        "macd_signal": -0.5,
        "macd_hist": -1.0,
        "macd_above_signal": False,
        "macd_bullish_crossover": False,
        "macd_hist_expanding": False,
        "macd_bearish_crossover": True,
        "bb_upper": 115.0,
        "bb_lower": 95.0,
        "bb_middle": 105.0,
        "bb_squeeze": False,
        "volume_ratio": 0.6,
        "volume_20ma": 5_000_000,
        "volume_confirmed": False,
        "volume_spike": False,
        "volume_drying": True,
        "signal_strong_bull": False,
        "signal_entry_criteria_met": False,
        "atr": 2.5,
        "suggested_stop_distance": 3.75,
        "golden_cross": False,
        "death_cross": True,
    }

"""
core/indicators.py
==================
Technical indicator calculation engine.

Indicators used by Fred:
- EMA (9, 20, 50, 200) — trend direction
- RSI (14) — momentum / overbought / oversold
- MACD (12, 26, 9) — trend + momentum
- Bollinger Bands (20, 2) — volatility + breakout
- ATR (14) — volatility / stop placement
- VWAP — intraday institutional reference
- OBV — volume confirmation
- Volume ratio — conviction check

All methods take a pandas DataFrame with OHLCV columns.
All columns expected lowercase: open, high, low, close, volume.
"""

import pandas as pd
import numpy as np
import logging as _logging; logger = _logging.getLogger(__name__)


class IndicatorEngine:
    """
    Calculates all technical indicators from OHLCV data.
    Returns a flat dict of indicator values for the latest bar.
    """

    def calculate_all(self, df: pd.DataFrame) -> dict:
        """
        Run all indicators on a DataFrame and return latest values.
        This is the main method called by MarketData.
        """
        if df.empty or len(df) < 20:
            logger.warning("Insufficient data for indicator calculation")
            return self._empty_indicators()

        # Ensure lowercase columns
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]

        try:
            results = {}

            # EMA family
            results.update(self._calculate_emas(df))

            # RSI
            results.update(self._calculate_rsi(df))

            # MACD
            results.update(self._calculate_macd(df))

            # Bollinger Bands
            results.update(self._calculate_bollinger_bands(df))

            # ATR
            results.update(self._calculate_atr(df))

            # OBV
            results.update(self._calculate_obv(df))

            # Volume analysis
            results.update(self._calculate_volume_metrics(df))

            # Candlestick pattern signals
            results.update(self._detect_patterns(df))

            # Composite signals derived from above
            results.update(self._calculate_composite_signals(results, df))

            return results

        except Exception as e:
            logger.error(f"Indicator calculation failed: {e}")
            return self._empty_indicators()

    # ── EMA ──────────────────────────────────────────────────────────────────

    def _calculate_emas(self, df: pd.DataFrame) -> dict:
        """Exponential Moving Averages at key periods."""
        results = {}
        periods = [9, 20, 50, 200]

        for p in periods:
            if len(df) >= p:
                ema = df["close"].ewm(span=p, adjust=False).mean()
                results[f"ema_{p}"] = round(float(ema.iloc[-1]), 4)
            else:
                results[f"ema_{p}"] = None

        # EMA slope (is it trending up?)
        if "ema_20" in results and results["ema_20"]:
            ema_20_series = df["close"].ewm(span=20, adjust=False).mean()
            if len(ema_20_series) >= 5:
                slope = (ema_20_series.iloc[-1] - ema_20_series.iloc[-5]) / ema_20_series.iloc[-5] * 100
                results["ema_20_slope_pct"] = round(float(slope), 3)
                results["ema_20_trending_up"] = slope > 0
            else:
                results["ema_20_slope_pct"] = 0
                results["ema_20_trending_up"] = False

        # Price relative to key EMAs
        price = float(df["close"].iloc[-1])
        results["price_above_ema_20"] = (
            price > results["ema_20"] if results.get("ema_20") else False
        )
        results["price_above_ema_50"] = (
            price > results["ema_50"] if results.get("ema_50") else False
        )
        results["price_above_ema_200"] = (
            price > results["ema_200"] if results.get("ema_200") else False
        )

        # Golden cross / death cross
        if results.get("ema_50") and results.get("ema_200"):
            results["golden_cross"] = results["ema_50"] > results["ema_200"]
            results["death_cross"] = results["ema_50"] < results["ema_200"]
        else:
            results["golden_cross"] = False
            results["death_cross"] = False

        return results

    # ── RSI ──────────────────────────────────────────────────────────────────

    def _calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> dict:
        """Relative Strength Index."""
        if len(df) < period + 1:
            return {"rsi": 50.0, "rsi_oversold": False, "rsi_overbought": False}

        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)

        avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
        avg_loss = loss.ewm(com=period - 1, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rsi_val = float(rsi.iloc[-1])

        # RSI divergence detection (simple version)
        # Price making higher high but RSI making lower high = bearish divergence
        price_hh = df["close"].iloc[-1] > df["close"].iloc[-5:].max() * 0.98
        rsi_lh = rsi_val < float(rsi.iloc[-6:-1].max()) * 0.98 if len(rsi) > 6 else False
        bearish_divergence = price_hh and rsi_lh

        # Price making lower low but RSI making higher low = bullish divergence
        price_ll = df["close"].iloc[-1] < df["close"].iloc[-5:].min() * 1.02
        rsi_hl = rsi_val > float(rsi.iloc[-6:-1].min()) * 1.02 if len(rsi) > 6 else False
        bullish_divergence = price_ll and rsi_hl

        return {
            "rsi": round(rsi_val, 2),
            "rsi_oversold": rsi_val < 30,
            "rsi_overbought": rsi_val > 70,
            "rsi_in_entry_range": 40 <= rsi_val <= 65,
            "rsi_extreme_overbought": rsi_val > 75,
            "rsi_extreme_oversold": rsi_val < 25,
            "rsi_bearish_divergence": bearish_divergence,
            "rsi_bullish_divergence": bullish_divergence,
        }

    # ── MACD ─────────────────────────────────────────────────────────────────

    def _calculate_macd(
        self,
        df: pd.DataFrame,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> dict:
        """Moving Average Convergence Divergence."""
        if len(df) < slow + signal:
            return {
                "macd": 0,
                "macd_signal": 0,
                "macd_hist": 0,
                "macd_bullish_crossover": False,
                "macd_bearish_crossover": False,
                "macd_hist_expanding": False,
            }

        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line

        macd_val = float(macd_line.iloc[-1])
        signal_val = float(signal_line.iloc[-1])
        hist_val = float(histogram.iloc[-1])
        prev_hist_val = float(histogram.iloc[-2]) if len(histogram) > 1 else 0

        # Crossover detection
        prev_macd = float(macd_line.iloc[-2]) if len(macd_line) > 1 else macd_val
        prev_signal = float(signal_line.iloc[-2]) if len(signal_line) > 1 else signal_val

        bullish_crossover = prev_macd <= prev_signal and macd_val > signal_val
        bearish_crossover = prev_macd >= prev_signal and macd_val < signal_val

        # Histogram expanding (momentum building)
        hist_expanding = abs(hist_val) > abs(prev_hist_val)
        hist_positive = hist_val > 0

        # Zero line crossover
        zero_cross_up = float(macd_line.iloc[-2]) < 0 and macd_val > 0 if len(macd_line) > 1 else False
        zero_cross_down = float(macd_line.iloc[-2]) > 0 and macd_val < 0 if len(macd_line) > 1 else False

        return {
            "macd": round(macd_val, 6),
            "macd_signal": round(signal_val, 6),
            "macd_hist": round(hist_val, 6),
            "macd_bullish_crossover": bullish_crossover,
            "macd_bearish_crossover": bearish_crossover,
            "macd_hist_expanding": hist_expanding,
            "macd_hist_positive": hist_positive,
            "macd_zero_cross_up": zero_cross_up,
            "macd_zero_cross_down": zero_cross_down,
            "macd_above_signal": macd_val > signal_val,
        }

    # ── Bollinger Bands ───────────────────────────────────────────────────────

    def _calculate_bollinger_bands(
        self, df: pd.DataFrame, period: int = 20, std_dev: float = 2.0
    ) -> dict:
        """Bollinger Bands — volatility and breakout signals."""
        if len(df) < period:
            price = float(df["close"].iloc[-1])
            return {
                "bb_upper": price * 1.02,
                "bb_middle": price,
                "bb_lower": price * 0.98,
                "bb_width": 0.04,
                "bb_pct": 0.5,
                "bb_squeeze": False,
                "bb_breakout_up": False,
                "bb_breakout_down": False,
            }

        rolling_mean = df["close"].rolling(window=period).mean()
        rolling_std = df["close"].rolling(window=period).std()

        upper = rolling_mean + (rolling_std * std_dev)
        lower = rolling_mean - (rolling_std * std_dev)

        bb_upper = float(upper.iloc[-1])
        bb_middle = float(rolling_mean.iloc[-1])
        bb_lower = float(lower.iloc[-1])
        price = float(df["close"].iloc[-1])

        bb_width = (bb_upper - bb_lower) / bb_middle if bb_middle > 0 else 0
        bb_pct = (price - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5

        # Squeeze: bands are narrowing (compression before breakout)
        prev_width = (
            float(upper.iloc[-6]) - float(lower.iloc[-6])
        ) / float(rolling_mean.iloc[-6]) if len(df) > 5 else bb_width
        bb_squeeze = bb_width < prev_width * 0.95

        # Breakout
        bb_breakout_up = price > bb_upper
        bb_breakout_down = price < bb_lower

        return {
            "bb_upper": round(bb_upper, 4),
            "bb_middle": round(bb_middle, 4),
            "bb_lower": round(bb_lower, 4),
            "bb_width": round(bb_width, 4),
            "bb_pct": round(bb_pct, 4),
            "bb_squeeze": bb_squeeze,
            "bb_breakout_up": bb_breakout_up,
            "bb_breakout_down": bb_breakout_down,
            "near_upper_band": bb_pct > 0.85,
            "near_lower_band": bb_pct < 0.15,
        }

    # ── ATR ──────────────────────────────────────────────────────────────────

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> dict:
        """Average True Range — volatility measure used for stop placement."""
        if len(df) < period + 1:
            price = float(df["close"].iloc[-1])
            return {"atr": price * 0.02, "atr_pct": 2.0}

        high = df["high"]
        low = df["low"]
        prev_close = df["close"].shift(1)

        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)

        atr = tr.ewm(com=period - 1, adjust=False).mean()
        atr_val = float(atr.iloc[-1])
        price = float(df["close"].iloc[-1])
        atr_pct = (atr_val / price * 100) if price > 0 else 0

        return {
            "atr": round(atr_val, 4),
            "atr_pct": round(atr_pct, 2),
            # Suggested stop distance: 1.5x ATR below entry
            "suggested_stop_distance": round(atr_val * 1.5, 4),
        }

    # ── OBV ──────────────────────────────────────────────────────────────────

    def _calculate_obv(self, df: pd.DataFrame) -> dict:
        """On-Balance Volume — volume-price confirmation."""
        obv = (
            df["volume"]
            .where(df["close"] > df["close"].shift(1), -df["volume"])
            .cumsum()
        )

        obv_ema = obv.ewm(span=20, adjust=False).mean()
        obv_val = float(obv.iloc[-1])
        obv_ema_val = float(obv_ema.iloc[-1])

        return {
            "obv": int(obv_val),
            "obv_above_ema": obv_val > obv_ema_val,
            "obv_trending_up": float(obv.iloc[-1]) > float(obv.iloc[-5]) if len(obv) > 5 else True,
        }

    # ── Volume Metrics ────────────────────────────────────────────────────────

    def _calculate_volume_metrics(self, df: pd.DataFrame) -> dict:
        """Volume analysis — confirmation and conviction check."""
        volume = df["volume"]
        current_vol = int(volume.iloc[-1])
        vol_20ma = float(volume.tail(20).mean())
        vol_ratio = current_vol / vol_20ma if vol_20ma > 0 else 1.0

        # Relative volume spike
        vol_spike = vol_ratio >= 2.0
        vol_confirmed = vol_ratio >= 1.0
        vol_drying = vol_ratio < 0.5

        return {
            "volume_20ma": int(vol_20ma),
            "volume_ratio": round(vol_ratio, 2),
            "volume_spike": vol_spike,
            "volume_confirmed": vol_confirmed,
            "volume_drying": vol_drying,
        }

    # ── Pattern Detection ─────────────────────────────────────────────────────

    def _detect_patterns(self, df: pd.DataFrame) -> dict:
        """Simple candlestick pattern detection."""
        if len(df) < 3:
            return {}

        o = df["open"]
        h = df["high"]
        lo = df["low"]
        c = df["close"]

        # Doji (indecision)
        body = abs(c - o)
        range_ = h - lo
        doji = (body / range_.replace(0, np.nan) < 0.1).iloc[-1]

        # Hammer (bullish reversal)
        lower_wick = o - lo if c.iloc[-1] > o.iloc[-1] else c - lo
        hammer = (
            lower_wick.iloc[-1] > body.iloc[-1] * 2
            and c.iloc[-1] > o.iloc[-1]
        )

        # Engulfing bullish
        bullish_engulf = (
            c.iloc[-2] < o.iloc[-2]  # prev bearish
            and c.iloc[-1] > o.iloc[-1]  # current bullish
            and o.iloc[-1] < c.iloc[-2]  # open below prev close
            and c.iloc[-1] > o.iloc[-2]  # close above prev open
        )

        return {
            "pattern_doji": bool(doji),
            "pattern_hammer": bool(hammer),
            "pattern_bullish_engulf": bool(bullish_engulf),
        }

    # ── Composite Signals ─────────────────────────────────────────────────────

    def _calculate_composite_signals(self, indicators: dict, df: pd.DataFrame) -> dict:
        """
        Derived signals combining multiple indicators.
        These are used directly in confidence scoring.
        """
        # Strong bull signal: price above EMA20, RSI in range, MACD bullish, volume confirmed
        strong_bull = (
            indicators.get("price_above_ema_20", False)
            and indicators.get("rsi_in_entry_range", False)
            and indicators.get("macd_above_signal", False)
            and indicators.get("volume_confirmed", False)
        )

        # Exit warning: RSI overbought or MACD bearish crossover
        exit_warning = (
            indicators.get("rsi_extreme_overbought", False)
            or indicators.get("macd_bearish_crossover", False)
        )

        # Squeeze breakout imminent
        squeeze_breakout = (
            indicators.get("bb_squeeze", False)
            and indicators.get("volume_spike", False)
        )

        # All entry criteria met (technical only — catalyst must be added separately)
        entry_criteria_met = (
            indicators.get("price_above_ema_20", False)
            and indicators.get("rsi_in_entry_range", False)
            and (
                indicators.get("macd_bullish_crossover", False)
                or indicators.get("macd_hist_expanding", False)
            )
            and indicators.get("volume_confirmed", False)
        )

        return {
            "signal_strong_bull": strong_bull,
            "signal_exit_warning": exit_warning,
            "signal_squeeze_breakout": squeeze_breakout,
            "signal_entry_criteria_met": entry_criteria_met,
        }

    # ── Empty Fallback ────────────────────────────────────────────────────────

    def _empty_indicators(self) -> dict:
        """Returns safe defaults when calculation fails."""
        return {
            "ema_9": None, "ema_20": None, "ema_50": None, "ema_200": None,
            "ema_20_slope_pct": 0, "ema_20_trending_up": False,
            "price_above_ema_20": False, "price_above_ema_50": False,
            "price_above_ema_200": False, "golden_cross": False, "death_cross": False,
            "rsi": 50.0, "rsi_oversold": False, "rsi_overbought": False,
            "rsi_in_entry_range": False, "rsi_extreme_overbought": False,
            "rsi_bullish_divergence": False, "rsi_bearish_divergence": False,
            "macd": 0, "macd_signal": 0, "macd_hist": 0,
            "macd_bullish_crossover": False, "macd_bearish_crossover": False,
            "macd_hist_expanding": False, "macd_above_signal": False,
            "bb_upper": 0, "bb_lower": 0, "bb_middle": 0,
            "bb_squeeze": False, "bb_breakout_up": False,
            "atr": 0, "atr_pct": 0, "suggested_stop_distance": 0,
            "volume_20ma": 0, "volume_ratio": 1.0,
            "volume_spike": False, "volume_confirmed": False,
            "obv": 0, "obv_above_ema": False,
            "signal_strong_bull": False, "signal_exit_warning": False,
            "signal_entry_criteria_met": False,
        }

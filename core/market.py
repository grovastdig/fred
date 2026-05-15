"""
core/market.py
==============
Market data layer. Fetches price data, fundamentals, and macro indicators.

Primary: Polygon.io (real-time, paid)
Fallback: yfinance (delayed 15min, free)

All data is normalized into a standard dict format before
being passed to the indicator engine or brain.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional
import logging as _logging; logger = _logging.getLogger(__name__)
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings


class MarketData:
    """
    Fetches and normalizes market data for any ticker.
    Used by indicators, signals, and the brain.
    """

    def __init__(self):
        self._cache: dict = {}
        self._cache_ttl: int = 60  # seconds
        self._polygon_client = None

        if settings.has_polygon:
            try:
                from polygon import RESTClient
                self._polygon_client = RESTClient(settings.polygon_api_key)
                logger.info("Polygon.io client initialized")
            except Exception as e:
                logger.warning(f"Polygon init failed, using yfinance: {e}")

    # ── Primary Data Methods ─────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=5))
    def get_snapshot(self, ticker: str) -> dict:
        """
        Get full market snapshot for a ticker.
        Returns normalized dict with price, indicators, and metadata.
        """
        ticker = ticker.upper().strip()

        try:
            if self._polygon_client and not settings.use_yfinance_fallback:
                return self._fetch_polygon_snapshot(ticker)
            else:
                return self._fetch_yfinance_snapshot(ticker)
        except Exception as e:
            logger.error(f"Failed to fetch snapshot for {ticker}: {e}")
            raise

    def get_bulk_snapshots(self, tickers: list[str]) -> dict[str, dict]:
        """
        Fetch snapshots for multiple tickers efficiently.
        Returns dict of {ticker: snapshot}.
        """
        results = {}
        for ticker in tickers:
            try:
                results[ticker] = self.get_snapshot(ticker)
            except Exception as e:
                logger.warning(f"Skipping {ticker} due to error: {e}")
                results[ticker] = {"error": str(e), "ticker": ticker}
        return results

    def get_historical(
        self,
        ticker: str,
        period: str = "6mo",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data.
        period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y
        interval: 1m, 5m, 15m, 30m, 1h, 1d, 1wk
        """
        try:
            ticker_obj = yf.Ticker(ticker)
            df = ticker_obj.history(period=period, interval=interval)

            if df.empty:
                logger.warning(f"No historical data for {ticker}")
                return pd.DataFrame()

            df.index = pd.to_datetime(df.index)
            df.columns = [c.lower() for c in df.columns]
            return df

        except Exception as e:
            logger.error(f"Historical fetch failed for {ticker}: {e}")
            return pd.DataFrame()

    # ── Macro Data ───────────────────────────────────────────────────────────

    def get_market_regime(self) -> dict:
        """
        Determine current market regime: bull, choppy, or bear.
        Uses S&P 500 and VIX to classify.
        """
        try:
            spy = self.get_snapshot("SPY")
            vix = self.get_snapshot("^VIX")

            spy_above_50ema = spy.get("price", 0) > spy.get("ema_50", 0)
            spy_above_200ema = spy.get("price", 0) > spy.get("ema_200", 0)
            vix_level = vix.get("price", 20)

            if vix_level < 20 and spy_above_50ema:
                regime = "bull"
                description = "VIX calm, market trending up. Full aggression."
                max_positions = 5
            elif vix_level > 30 or not spy_above_200ema:
                regime = "bear"
                description = "VIX elevated, market stressed. Very selective."
                max_positions = 2
            else:
                regime = "choppy"
                description = "Mixed signals. Only highest conviction setups."
                max_positions = 3

            return {
                "regime": regime,
                "description": description,
                "max_positions": max_positions,
                "vix": vix_level,
                "spy_above_50ema": spy_above_50ema,
                "spy_above_200ema": spy_above_200ema,
                "spy_price": spy.get("price", 0),
                "spy_change_pct": spy.get("change_pct", 0),
            }

        except Exception as e:
            logger.error(f"Market regime check failed: {e}")
            return {
                "regime": "unknown",
                "description": "Could not determine regime",
                "max_positions": 3,
                "vix": None,
                "error": str(e),
            }

    def get_macro_snapshot(self) -> dict:
        """
        Quick macro dashboard — futures, VIX, DXY, oil, gold.
        Used for morning brief.
        """
        symbols = {
            "sp_futures": "ES=F",
            "nasdaq_futures": "NQ=F",
            "vix": "^VIX",
            "dxy": "DX-Y.NYB",
            "oil": "CL=F",
            "gold": "GC=F",
            "ten_yr": "^TNX",
        }

        macro = {}
        for key, symbol in symbols.items():
            try:
                snap = self.get_snapshot(symbol)
                macro[key] = snap.get("price")
                macro[f"{key}_pct"] = snap.get("change_pct")
            except Exception:
                macro[key] = None
                macro[f"{key}_pct"] = None

        return macro

    def get_sector_performance(self) -> dict:
        """
        Fetch weekly performance for all major sectors.
        Identifies what's hot and what's not.
        """
        sector_etfs = {
            "Technology": "XLK",
            "Healthcare": "XLV",
            "Financials": "XLF",
            "Energy": "XLE",
            "Consumer Discretionary": "XLY",
            "Consumer Staples": "XLP",
            "Industrials": "XLI",
            "Materials": "XLB",
            "Real Estate": "XLRE",
            "Utilities": "XLU",
            "Communication": "XLC",
            "Semiconductors": "SOXX",
        }

        performance = {}
        for sector, etf in sector_etfs.items():
            try:
                snap = self.get_snapshot(etf)
                performance[sector] = {
                    "etf": etf,
                    "change_pct_today": snap.get("change_pct", 0),
                    "price": snap.get("price", 0),
                }
            except Exception as e:
                performance[sector] = {"etf": etf, "error": str(e)}

        # Sort by today's performance
        sorted_sectors = sorted(
            performance.items(),
            key=lambda x: x[1].get("change_pct_today", -999),
            reverse=True,
        )

        return {
            "sectors": dict(sorted_sectors),
            "top_sector": sorted_sectors[0][0] if sorted_sectors else None,
            "worst_sector": sorted_sectors[-1][0] if sorted_sectors else None,
            "timestamp": datetime.now().isoformat(),
        }

    # ── Stock Scanner ────────────────────────────────────────────────────────

    def scan_momentum_stocks(
        self,
        watchlist: Optional[list[str]] = None,
        universe: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Scan stocks for momentum setups.
        Returns candidates sorted by momentum score.
        """
        # Default universe if none provided
        if not universe and not watchlist:
            universe = self._get_default_scan_universe()

        tickers_to_scan = list(set((watchlist or []) + (universe or [])))
        candidates = []

        for ticker in tickers_to_scan[:50]:  # Cap at 50 to avoid rate limits
            try:
                snap = self.get_snapshot(ticker)
                if "error" in snap:
                    continue

                # Quick momentum pre-filter
                rsi = snap.get("rsi", 50)
                volume_ratio = snap.get("volume_ratio", 1)
                price_above_ema20 = snap.get("price", 0) > snap.get("ema_20", 0)
                change_pct = snap.get("change_pct", 0)

                # Must pass basic criteria to be a candidate
                if (
                    40 <= rsi <= 70
                    and volume_ratio >= 1.2
                    and price_above_ema20
                    and change_pct > -3
                ):
                    candidates.append(snap)

            except Exception as e:
                logger.debug(f"Scan skipping {ticker}: {e}")

        # Sort by momentum score (volume * change)
        candidates.sort(
            key=lambda x: x.get("volume_ratio", 0) * abs(x.get("change_pct", 0)),
            reverse=True,
        )

        logger.info(f"Scan found {len(candidates)} candidates from {len(tickers_to_scan)} tickers")
        return candidates[:20]

    # ── yfinance Implementation ──────────────────────────────────────────────

    def _fetch_yfinance_snapshot(self, ticker: str) -> dict:
        """Fetch and normalize data from yfinance."""
        from core.indicators import IndicatorEngine

        ticker_obj = yf.Ticker(ticker)

        # Get 6 months of daily data for indicators
        hist = ticker_obj.history(period="6mo", interval="1d")

        if hist.empty:
            raise ValueError(f"No data returned for {ticker}")

        hist.columns = [c.lower() for c in hist.columns]

        # Calculate indicators
        indicators = IndicatorEngine().calculate_all(hist)

        # Get latest values
        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) > 1 else latest

        price = float(latest["close"])
        prev_close = float(prev["close"])
        change_pct = ((price - prev_close) / prev_close) * 100

        # 52-week range
        high_52w = float(hist["close"].tail(252).max())
        low_52w = float(hist["close"].tail(252).min())

        # Volume analysis
        volume = int(latest["volume"])
        volume_20ma = float(hist["volume"].tail(20).mean())
        volume_ratio = volume / volume_20ma if volume_20ma > 0 else 1.0

        # Basic info
        try:
            info = ticker_obj.info
            market_cap = info.get("marketCap", 0)
            sector = info.get("sector", "Unknown")
            company_name = info.get("longName", ticker)
        except Exception:
            market_cap = 0
            sector = "Unknown"
            company_name = ticker

        return {
            "ticker": ticker,
            "company_name": company_name,
            "sector": sector,
            "price": price,
            "open": float(latest.get("open", price)),
            "high": float(latest.get("high", price)),
            "low": float(latest.get("low", price)),
            "prev_close": prev_close,
            "change_pct": change_pct,
            "volume": volume,
            "volume_20ma": int(volume_20ma),
            "volume_ratio": round(volume_ratio, 2),
            "market_cap": market_cap,
            "high_52w": high_52w,
            "low_52w": low_52w,
            # Indicators from IndicatorEngine
            **indicators,
            "data_source": "yfinance",
            "timestamp": datetime.now().isoformat(),
        }

    def _fetch_polygon_snapshot(self, ticker: str) -> dict:
        """Fetch real-time data from Polygon.io."""
        try:
            snap = self._polygon_client.get_snapshot_ticker("stocks", ticker)
            # ... polygon response normalization
            # Falls back to yfinance for indicators since Polygon
            # doesn't provide calculated indicators
            yf_data = self._fetch_yfinance_snapshot(ticker)
            # Override price with real-time Polygon price
            if snap and hasattr(snap, "day"):
                yf_data["price"] = snap.day.close
                yf_data["volume"] = snap.day.volume
                yf_data["change_pct"] = snap.todaysChangePerc
                yf_data["data_source"] = "polygon"
            return yf_data
        except Exception as e:
            logger.warning(f"Polygon fetch failed for {ticker}, falling back to yfinance: {e}")
            return self._fetch_yfinance_snapshot(ticker)

    def _get_default_scan_universe(self) -> list[str]:
        """Default stock universe to scan when no watchlist provided."""
        return [
            # Mega cap tech
            "AAPL", "MSFT", "NVDA", "AMD", "META", "GOOGL", "AMZN", "TSLA",
            # Semiconductors
            "AVGO", "QCOM", "MU", "INTC", "TSM", "AMAT", "LRCX", "KLAC",
            # High momentum
            "PLTR", "RBLX", "COIN", "MSTR", "HOOD", "SOFI", "UPST",
            # ETFs for regime check
            "SPY", "QQQ", "IWM", "XLK", "XLE", "XLF",
            # Energy
            "XOM", "CVX", "OXY", "SLB", "HAL",
            # Financials
            "JPM", "BAC", "GS", "MS", "C",
            # Healthcare
            "LLY", "NVO", "MRNA", "BNTX",
        ]


# Global singleton
market_data = MarketData()

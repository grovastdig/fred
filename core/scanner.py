"""
core/scanner.py
===============
Fred's market scanner. Runs on schedule and on-demand.

Scans the full watchlist every 15 minutes during market hours,
applies ALL entry criteria, scores each setup with the Confidence
Meter, and only surfaces setups that clear the 50/100 minimum.

This is the engine that finds the plays. Claude ranks them.
You decide. Nobody trades without your say-so.
"""

from typing import Optional
from dataclasses import dataclass
import logging as _logging; logger = _logging.getLogger(__name__)

from core.market import market_data
from core.confidence import ConfidenceMeter, ConfidenceScore
from config.settings import settings
from config.trading_rules import SCAN_UNIVERSE


confidence_meter = ConfidenceMeter()


@dataclass
class ScanResult:
    """A single ticker's full scan output."""

    ticker: str
    price: float
    confidence: ConfidenceScore
    indicators: dict
    snapshot: dict

    # Suggested trade levels
    suggested_entry: float = 0.0
    suggested_stop: float = 0.0
    suggested_target: float = 0.0
    risk_reward: float = 0.0

    def __post_init__(self):
        if self.suggested_entry and self.suggested_stop and self.suggested_target:
            risk = self.suggested_entry - self.suggested_stop
            reward = self.suggested_target - self.suggested_entry
            self.risk_reward = reward / risk if risk > 0 else 0.0

    def to_sms(self) -> str:
        """Format for SMS — punchy, readable on a phone screen."""
        score = self.confidence.total
        grade = self.confidence.label
        size = self.confidence.position_size_label
        return (
            f"🎯 {self.ticker} — {score:.0f}/100 {grade}\n"
            f"Price: ${self.price:.2f}\n"
            f"Entry: ${self.suggested_entry:.2f} | Stop: ${self.suggested_stop:.2f}\n"
            f"Target: ${self.suggested_target:.2f} | R:R {self.risk_reward:.1f}:1\n"
            f"Size: {size}"
        )

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "confidence": self.confidence.total,
            "grade": self.confidence.label,
            "entry": self.suggested_entry,
            "stop": self.suggested_stop,
            "target": self.suggested_target,
            "rr": self.risk_reward,
            "position_size_pct": self.confidence.position_size_pct,
            "rsi": self.indicators.get("rsi"),
            "volume_ratio": self.indicators.get("volume_ratio"),
            "macd_bullish": self.indicators.get("macd_above_signal"),
        }


class MarketScanner:
    """
    Scans the configured universe for actionable setups.
    Runs on a 15-minute schedule during market hours.
    Trigger on-demand via SMS: "scan".
    """

    def __init__(self):
        self._last_results: list[ScanResult] = []
        self._scan_universe = SCAN_UNIVERSE
        logger.info(
            f"MarketScanner initialized — {len(self._scan_universe)} tickers in universe"
        )

    def scan_ticker(
        self,
        ticker: str,
        market_regime: Optional[dict] = None,
        news_catalysts: Optional[list] = None,
    ) -> Optional[ScanResult]:
        """
        Full scan of a single ticker.
        Returns ScanResult if setup clears minimum confidence, else None.
        """
        ticker = ticker.upper().strip()
        try:
            # Get full snapshot (price + all indicators)
            snapshot = market_data.get_snapshot(ticker)
            if "error" in snapshot or not snapshot.get("price"):
                logger.debug(f"{ticker}: no snapshot data")
                return None

            price = snapshot["price"]
            indicators = snapshot

            # Need EMA data to evaluate setup
            if not indicators.get("ema_20"):
                logger.debug(f"{ticker}: insufficient indicator data")
                return None

            # Determine ATR-based trade levels
            atr = indicators.get("atr", price * 0.02)
            stop = round(price - (atr * 1.5), 2)
            target = round(price + (atr * 3.0), 2)  # 2:1 minimum

            # Build catalyst dict from news if available
            catalyst = None
            if news_catalysts:
                matching = [n for n in news_catalysts if ticker in n.get("tickers", [])]
                if matching:
                    catalyst = {
                        "type": "news",
                        "strength": "moderate",
                        "description": matching[0].get("title", ""),
                        "count": len(matching),
                    }

            # Score the setup
            regime = market_regime or market_data.get_market_regime()
            sector_data = {
                "sector_trending_up": regime.get("spy_above_ema_50", False)
            }

            confidence = confidence_meter.score(
                ticker=ticker,
                technical_data=indicators,
                catalyst=catalyst,
                sector_data=sector_data,
                market_regime=regime,
                entry_price=price,
                stop_loss=stop,
                target_price=target,
            )

            # Filter: only return setups above minimum threshold
            min_score = settings.min_confidence_score
            if confidence.total < min_score:
                logger.debug(
                    f"{ticker}: {confidence.total:.0f}/100 below minimum {min_score} — skipped"
                )
                return None

            result = ScanResult(
                ticker=ticker,
                price=price,
                confidence=confidence,
                indicators=indicators,
                snapshot=snapshot,
                suggested_entry=round(price, 2),
                suggested_stop=stop,
                suggested_target=target,
            )

            logger.info(
                f"✅ {ticker} — {confidence.total:.0f}/100 {confidence.label} "
                f"| ${price:.2f} | Stop ${stop:.2f} | Target ${target:.2f}"
            )
            return result

        except Exception as e:
            logger.error(f"Error scanning {ticker}: {e}")
            return None

    def scan_all(
        self,
        tickers: Optional[list] = None,
        market_regime: Optional[dict] = None,
        news_catalysts: Optional[list] = None,
    ) -> list[ScanResult]:
        """
        Scan all tickers in the universe.
        Returns results sorted by confidence score, highest first.
        """
        universe = tickers or self._scan_universe
        regime = market_regime or market_data.get_market_regime()
        catalysts = news_catalysts or []

        logger.info(
            f"Starting full scan — {len(universe)} tickers | "
            f"regime: {regime.get('regime', 'unknown')}"
        )

        results = []
        for ticker in universe:
            result = self.scan_ticker(ticker, regime, catalysts)
            if result:
                results.append(result)

        results.sort(key=lambda r: r.confidence.total, reverse=True)
        self._last_results = results

        logger.info(
            f"Scan complete — {len(results)}/{len(universe)} setups found"
        )
        return results

    def get_top_setups(self, n: int = 3) -> list[ScanResult]:
        """Top N from last scan."""
        return self._last_results[:n]

    def scan_to_sms(
        self,
        tickers: Optional[list] = None,
        max_results: int = 3,
    ) -> str:
        """Run scan and return formatted SMS string."""
        regime = market_data.get_market_regime()
        results = self.scan_all(tickers, regime)
        regime_str = regime.get("regime", "unknown").upper()

        if not results:
            return (
                f"🔍 SCAN COMPLETE — {regime_str} MARKET\n"
                "No clean setups right now.\n"
                "Cash is a position — stay patient."
            )

        top = results[:max_results]
        header = f"🔍 SCAN — {len(results)} setup(s) | {regime_str}\n{'─'*28}"
        sections = [header]
        for i, r in enumerate(top, 1):
            sections.append(f"\n[#{i}] {r.to_sms()}")

        return "\n".join(sections)

    def check_entry_conditions(
        self,
        ticker: str,
        entry: float,
        stop: float,
        target: float,
    ) -> dict:
        """
        Mechanically verify every entry condition for a specific setup.
        Returns pass/fail with detailed reasons.
        """
        snapshot = market_data.get_snapshot(ticker.upper())
        if "error" in snapshot:
            return {"passes": False, "reason": f"No data for {ticker}"}

        failures = []

        if not snapshot.get("price_above_ema_20"):
            ema = snapshot.get("ema_20", 0)
            failures.append(f"Price ${snapshot.get('price', 0):.2f} below 20 EMA ${ema:.2f}")

        rsi = snapshot.get("rsi", 50)
        if not (40 <= rsi <= 65):
            failures.append(f"RSI {rsi:.1f} outside buy zone (40-65)")

        if not snapshot.get("macd_above_signal"):
            failures.append("MACD not bullish")

        vol_ratio = snapshot.get("volume_ratio", 0)
        if vol_ratio < 1.0:
            failures.append(f"Volume {vol_ratio:.1f}x avg (need 1.0x+)")

        if entry > 0 and stop > 0 and target > 0:
            risk = entry - stop
            reward = target - entry
            rr = reward / risk if risk > 0 else 0
            if rr < 2.0:
                failures.append(f"R:R {rr:.1f}:1 below minimum 2:1")

        if failures:
            return {
                "passes": False,
                "failures": failures,
                "indicators": snapshot,
                "message": "❌ Fails entry criteria:\n• " + "\n• ".join(failures),
            }

        return {
            "passes": True,
            "indicators": snapshot,
            "message": f"✅ {ticker} passes all entry conditions",
        }


# Global singleton
market_scanner = MarketScanner()

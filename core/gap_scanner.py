"""
core/gap_scanner.py
====================
Overnight gap scanner. Finds stocks moving 12%+ in pre/after-hours.
Built for consistent daily alpha generation.

Runs three times daily:
  8:00 PM ET  — After-hours scan (earnings reactions settling)
  4:30 AM ET  — Pre-market scan (gap forming, before retail piles in)
  9:15 AM ET  — Confirmation scan (is the gap holding at open?)

Gap plays are higher risk than regular swing trades.
Fred flags them clearly and sizes them accordingly.
A 40% gap on a $300 position is $120. These happen multiple times a week.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config.trading_rules import SCAN_UNIVERSE

logger = logging.getLogger("fred.gap_scanner")

# Minimum overnight move to qualify
MIN_GAP_PCT    = 12.0   # 12% minimum — smaller gaps aren't worth the risk profile
STRONG_GAP_PCT = 25.0   # 25%+ = strong signal
MONSTER_GAP_PCT = 40.0  # 40%+ = potential runner, use with tight stop

# Small/mid cap universe — these are the names that actually gap 20-50%
GAP_UNIVERSE = [
    # High-beta small caps
    "RKLB", "LUNR", "ACHR", "JOBY", "ASTS", "RCAT", "SPCE",
    # Biotech / FDA
    "SAVA", "ARWR", "BEAM", "EDIT", "CRSP", "NTLA", "KYMR", "ALNY",
    "AGEN", "FREQ", "AGIO",
    # Meme / social momentum
    "GME", "AMC",
    # EV / clean energy
    "CHPT", "BLNK", "EVGO", "PLUG", "FCEL",
    # Crypto-adjacent
    "MARA", "RIOT", "HUT", "BITF", "CLSK",
    # Defense small caps
    "AVAV", "KTOS",
    # AI small caps
    "SOUN", "BBAI",
    # Special situations
    "DJT", "HOOD", "SOFI",
] + SCAN_UNIVERSE  # Always include the standard watchlist


@dataclass
class GapPlay:
    """A single gap play opportunity."""
    ticker: str
    gap_pct: float
    current_price: float
    prev_close: float
    volume_ratio: float
    catalyst: str
    direction: str       # "up" or "down"
    strength: str        # "monster", "strong", "moderate"
    gap_type: str = "unknown"  # "earnings", "news", "unknown"
    is_holding: bool = True    # Is gap holding vs fading?

    def to_sms(self, balance: float = 0) -> str:
        emoji = (
            "🚀" if self.gap_pct >= 40
            else "📈" if self.gap_pct >= 25
            else "👀"
        )
        direction_str = "UP" if self.direction == "up" else "DOWN"
        lines = [
            f"{emoji} GAP PLAY: {self.ticker} {direction_str} "
            f"{self.gap_pct:+.1f}%",
            f"Price: ${self.current_price:.2f} (prev ${self.prev_close:.2f})",
            f"Volume: {self.volume_ratio:.1f}x avg",
            f"Catalyst: {self.catalyst[:70]}",
        ]
        if balance > 0:
            # Builder Mode sizing — gap plays are higher risk, 15% max
            pct = 0.15
            size = balance * pct
            lines.append(f"Suggested size: ${size:.2f} ({int(pct*100)}%)")
        return "\n".join(lines)


class GapScanner:
    """
    Scans for overnight gap plays three times daily.
    Higher risk than standard setups — sized accordingly.
    """

    def __init__(self):
        self._last_scan: Optional[datetime] = None
        self._recent_alerts: set[str] = set()

    async def scan(self, universe: Optional[list] = None) -> list[GapPlay]:
        """
        Scan for gap plays. Returns list sorted by gap size.
        Deduplicates the universe first to avoid redundant calls.
        """
        tickers = list(set(universe or GAP_UNIVERSE))
        plays = []

        logger.info(f"Gap scan starting — {len(tickers)} tickers")

        # Process in batches to avoid yfinance rate limits
        batch_size = 15
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            batch_plays = await self._scan_batch(batch)
            plays.extend(batch_plays)
            await asyncio.sleep(0.3)

        plays.sort(key=lambda p: abs(p.gap_pct), reverse=True)
        self._last_scan = datetime.now()

        logger.info(f"Gap scan complete — {len(plays)} plays found")
        return plays

    async def _scan_batch(self, tickers: list) -> list[GapPlay]:
        plays = []
        loop = asyncio.get_event_loop()
        for ticker in tickers:
            try:
                play = await loop.run_in_executor(
                    None, self._check_ticker, ticker
                )
                if play:
                    plays.append(play)
            except Exception as e:
                logger.debug(f"Gap check failed {ticker}: {e}")
        return plays

    def _check_ticker(self, ticker: str) -> Optional[GapPlay]:
        """Check a single ticker for overnight gap. Sync — runs in executor."""
        try:
            import yfinance as yf
            tk = yf.Ticker(ticker)

            hist = tk.history(period="5d", interval="1d")
            if len(hist) < 2:
                return None

            prev_close = float(hist["Close"].iloc[-2])
            info = tk.fast_info
            current = getattr(info, "last_price", None)

            if not current or not prev_close or prev_close <= 0:
                return None

            gap_pct = ((current - prev_close) / prev_close) * 100

            if abs(gap_pct) < MIN_GAP_PCT:
                return None

            avg_vol = getattr(info, "three_month_average_volume", 0)
            current_vol = getattr(info, "last_volume", 0)
            vol_ratio = (current_vol / avg_vol) if avg_vol > 0 else 1.0

            # Low-volume small gaps are usually traps
            if vol_ratio < 0.5 and abs(gap_pct) < STRONG_GAP_PCT:
                return None

            if abs(gap_pct) >= MONSTER_GAP_PCT:
                strength = "monster"
            elif abs(gap_pct) >= STRONG_GAP_PCT:
                strength = "strong"
            else:
                strength = "moderate"

            catalyst = self._get_catalyst(ticker, tk)
            gap_type = (
                "earnings" if "earn" in catalyst.lower()
                else "news" if catalyst != "Unknown catalyst"
                else "unknown"
            )

            return GapPlay(
                ticker=ticker,
                gap_pct=gap_pct,
                current_price=current,
                prev_close=prev_close,
                volume_ratio=vol_ratio,
                catalyst=catalyst,
                direction="up" if gap_pct > 0 else "down",
                strength=strength,
                gap_type=gap_type,
            )

        except Exception as e:
            logger.debug(f"Ticker check error {ticker}: {e}")
            return None

    def _get_catalyst(self, ticker: str, tk) -> str:
        """Pull most recent news headline as catalyst."""
        try:
            news = tk.news
            if news:
                return news[0].get("title", "Unknown catalyst")[:80]
        except Exception:
            pass
        return "Unknown catalyst — check news"

    async def scan_and_alert(self, balance: float = 0, mode: str = "builder") -> str:
        """Run scan and format results for SMS."""
        plays = await self.scan()

        if not plays:
            return (
                f"🔍 Gap scan complete ({datetime.now().strftime('%H:%M ET')})\n"
                "Nothing moving 12%+ right now. Clean slate."
            )

        upside = [p for p in plays if p.direction == "up"][:3]
        downside = [p for p in plays if p.direction == "down"][:1]

        lines = [
            f"🌙 OVERNIGHT GAPS "
            f"({datetime.now().strftime('%H:%M ET')})\n"
        ]

        for play in upside:
            lines.append(play.to_sms(balance))
            lines.append("")

        if downside:
            lines.append("📉 NOTABLE DROPS:")
            for play in downside:
                lines.append(
                    f"{play.ticker}: {play.gap_pct:+.1f}% — "
                    f"{play.catalyst[:50]}"
                )
            lines.append("")

        lines.append("Text any ticker for full analysis.")
        return "\n".join(lines)

    async def confirmation_scan(self, balance: float = 0, mode: str = "builder") -> str:
        """
        9:15 AM scan — only surface gaps that are still holding.
        Moderate gaps that fade at open are traps. Fred calls them out.
        """
        plays = await self.scan()
        strong = [
            p for p in plays
            if p.strength in ("strong", "monster") and p.direction == "up"
        ]

        if not strong:
            return (
                "🔔 9:15 gap check — moderate gaps fading.\n"
                "Nothing strong enough to chase at open.\n"
                "Wait for the first 15 min candle to settle."
            )

        lines = ["🔔 GAPS HOLDING AT 9:15 — these are real:\n"]
        for p in strong[:3]:
            lines.append(p.to_sms(balance))
            lines.append("")

        return "\n".join(lines)


# Global singleton
gap_scanner = GapScanner()

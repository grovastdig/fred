"""
alerts/trump_fast_path.py
==========================
Two-phase alert system for Truth Social / political posts.

Phase 1 (immediate, <30 seconds): Raw post text + affected tickers.
No Claude call - instant keyword mapping. You know what happened
before the market has time to fully react.

Phase 2 (60 seconds later): Full Claude analysis with specific
trade plan, sector impacts, and position-aware recommendations.

This is Fred's primary alpha edge for political catalyst trades.
Speed matters more here than anywhere else in the system.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("fred.trump_fast_path")

# Keyword → affected tickers map
# Built from historical post-to-market-move analysis
TRUMP_TICKER_MAP = {
    # Energy
    "oil": ["XOM", "CVX", "OXY", "COP", "SLB", "XLE"],
    "energy": ["XOM", "CVX", "XLE", "OXY", "HAL"],
    "coal": ["BTU", "ARCH", "CEIX"],
    "pipeline": ["KMI", "ET", "WMB"],
    "lng": ["LNG", "CQP", "TELL"],
    # Defense / military
    "military": ["LMT", "RTX", "NOC", "GD", "BA", "KTOS"],
    "defense": ["LMT", "RTX", "NOC", "GD", "AVAV"],
    "ukraine": ["LMT", "RTX", "NOC", "KTOS"],
    "israel": ["LMT", "RTX", "NOC", "AXON"],
    "nato": ["LMT", "RTX", "NOC", "GD"],
    # Tech / China
    "china": ["BABA", "JD", "PDD", "NVDA", "SOXL", "SMH"],
    "tiktok": ["META", "SNAP", "GOOGL", "PINS"],
    "huawei": ["NVDA", "QCOM", "INTC", "AVGO"],
    "semiconductor": ["NVDA", "AMD", "INTC", "SOXX", "SMH"],
    # Trade
    "tariff": ["SPY", "QQQ", "XLI", "XLB", "SOXL"],
    "tariffs": ["SPY", "QQQ", "XLI", "XLB"],
    "mexico": ["KO", "WMT", "HD", "F", "GM"],
    "canada": ["ENB", "TRP", "CNI", "CP"],
    "trade war": ["SPY", "XLK", "XLI"],
    # Crypto
    "bitcoin": ["COIN", "MSTR", "MARA", "RIOT", "HUT"],
    "crypto": ["COIN", "MSTR", "MARA", "RIOT", "CLSK"],
    "digital": ["COIN", "MSTR", "SQ", "PYPL"],
    # Finance
    "bank": ["JPM", "BAC", "GS", "MS", "WFC", "XLF"],
    "fed": ["JPM", "BAC", "TLT", "GS", "XLF"],
    "interest rate": ["TLT", "JPM", "BAC", "XLF"],
    # Pharma
    "pharma": ["XPH", "PFE", "MRNA", "LLY", "JNJ"],
    "drug": ["XPH", "PFE", "MRNA", "ABBV"],
    "fda": ["XBI", "IBB", "MRNA"],
    # Steel / manufacturing
    "steel": ["X", "NUE", "CLF", "RS", "STLD"],
    "manufacturing": ["CAT", "DE", "XLI", "HON"],
    "auto": ["F", "GM", "TSLA", "RIVN"],
    # Space / EV (Elon adjacent)
    "elon": ["TSLA", "DOGE"],
    "tesla": ["TSLA"],
    "spacex": ["RKLB", "PL", "ASTS"],
    "doge": ["DOGE", "COIN"],
    # Real estate / housing
    "housing": ["HD", "LOW", "DHI", "LEN", "TOL"],
    "mortgage": ["RKT", "UWM", "PFSI"],
    # Broad market movers
    "executive order": ["SPY", "QQQ"],
    "deal": ["SPY", "QQQ"],
    "sanctions": ["XLE", "XLF", "SPY"],
    # Trump-specific vehicles
    "truth social": ["DJT"],
    "djt": ["DJT"],
    "mar-a-lago": ["DJT"],
    "trump media": ["DJT"],
}


class TrumpFastPath:
    """Two-phase political post alert system."""

    async def process(
        self,
        post_text: str,
        relevance: dict,
        open_positions: list,
        watchlist: list,
        source: str = "truth_social",
    ) -> None:
        """
        Process a Trump post with two-phase alerting.
        Phase 1: Immediate. Phase 2: Full analysis 60 sec later.
        """
        from integrations.telegram_client import telegram_client
        from core.brain import fred_brain
        from core.mode_manager import mode_manager

        # ── Phase 1: Immediate (no Claude, <5 seconds) ───────────────────────
        affected = self._map_tickers(post_text, open_positions, watchlist)
        positions_hit = [t for t in affected if t in open_positions]

        phase1 = self._build_phase1(post_text, affected, positions_hit, source)
        telegram_client.send(phase1, alert_key=None)  # Never deduplicate political alerts
        logger.info(f"Phase 1 alert sent - source: {source} | affected: {affected}")

        # ── Phase 2: Full analysis (60 seconds, Claude) ──────────────────────
        await asyncio.sleep(60)

        try:
            mode = "builder"

            prompt = f"""A post just went up on {source.upper().replace('_', ' ')}.

POST: "{post_text}"

Immediately affected tickers identified: {', '.join(affected) if affected else 'Mapping in progress'}
Your open positions: {', '.join(open_positions) if open_positions else 'None'}
Watchlist: {', '.join(watchlist[:10]) if watchlist else 'Standard universe'}

Respond in this exact format:

DIRECTION: BULLISH / BEARISH / MIXED / UNCLEAR
TOP PLAY: [ticker] - [entry zone] - [one line reason]
SECONDARY: [ticker] - [one line] (or NONE)
POSITIONS AT RISK: [tickers] or NONE
ACTION: [specific action or MONITOR]
URGENCY: IMMEDIATE / TODAY / MONITOR
THESIS: [2 sentences - what does this actually mean for markets]"""

            analysis = await fred_brain.think(prompt, max_tokens=350)
            phase2 = f"🧠 ANALYSIS\n\n{analysis}"
            telegram_client.send(phase2, alert_key=None)
            logger.info("Phase 2 analysis sent")

        except Exception as e:
            logger.error(f"Phase 2 failed: {e}")
            telegram_client.send(
                "⚠️ Analysis delayed - check the post manually.",
                alert_key="phase2_fail"
            )

    def _map_tickers(
        self, text: str, open_positions: list, watchlist: list
    ) -> list[str]:
        """
        Map post keywords to affected tickers instantly.
        No Claude needed - pure keyword lookup.
        """
        text_lower = text.lower()
        found = set()

        for keyword, tickers in TRUMP_TICKER_MAP.items():
            if keyword in text_lower:
                found.update(tickers)

        # Check if open positions are directly mentioned
        for ticker in open_positions:
            if ticker.lower() in text_lower:
                found.add(ticker)

        # Check watchlist mentions
        for ticker in watchlist:
            if ticker.lower() in text_lower:
                found.add(ticker)

        return list(found)[:8]  # Cap at 8 per alert

    def _build_phase1(
        self,
        post_text: str,
        affected: list,
        positions_hit: list,
        source: str,
    ) -> str:
        source_label = (
            "TRUTH SOCIAL" if "truth" in source else "SOCIAL"
        )
        lines = [f"🚨 {source_label} - POSTED NOW", ""]

        # Truncate for SMS
        display = (
            post_text if len(post_text) <= 200
            else post_text[:197] + "..."
        )
        lines.append(f'"{display}"')
        lines.append("")

        if positions_hit:
            lines.append(f"⚠️ YOUR POSITIONS: {', '.join(positions_hit)}")

        if affected:
            lines.append(f"📈 WATCH: {', '.join(affected)}")

        lines.append("")
        lines.append("Full analysis in ~60 sec...")
        return "\n".join(lines)


# Global singleton
trump_fast_path = TrumpFastPath()

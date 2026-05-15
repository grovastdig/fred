"""
core/fred_brain_writer.py
==========================
Fred keeps notes. After every analysis, every trade, every market
observation — he writes it down in Notion under "Fred's Brain."

This is not a log of alerts. It's Fred's actual thinking.
You can open Notion any time and read exactly what Fred sees.

Pages written to:
  - Market Regime Log (daily)
  - Stock Notes (per ticker, updated continuously)
  - Active Trade Thesis (for every open position)
  - Trade Lessons (every closed trade, win or loss)
  - Setup Radar (stocks being watched but not called yet)
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("fred.brain_writer")

# Notion page ID for Fred's Brain (set during setup)
FREDS_BRAIN_PAGE_ID = "35ed6963-22fb-8199-a118-d6f0225ffebc"


class FredBrainWriter:
    """
    Writes Fred's observations and lessons to Notion.
    Called after every significant analysis or trade event.
    """

    def __init__(self):
        self._notion = None
        self._initialized = False

    def _get_notion(self):
        """Lazy-load notion client."""
        if not self._notion:
            try:
                from integrations.notion_client import notion_client
                self._notion = notion_client
                self._initialized = True
            except Exception as e:
                logger.warning(f"Notion client unavailable: {e}")
        return self._notion

    # ── Stock Notes ───────────────────────────────────────────────────────────

    async def write_stock_observation(
        self,
        ticker: str,
        observation: str,
        confidence_score: Optional[float] = None,
        action: str = "watching",  # 'watching', 'called', 'skipped'
    ) -> None:
        """
        Write a stock observation to Fred's Brain.
        Called after every ticker analysis.
        """
        notion = self._get_notion()
        if not notion:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        score_str = f" | Score: {confidence_score:.0f}/100" if confidence_score is not None else ""
        action_emoji = {"watching": "👀", "called": "🎯", "skipped": "❌"}.get(action, "📝")

        note = (
            f"**{timestamp}** {action_emoji} {ticker}{score_str}\n"
            f"{observation}"
        )

        try:
            await notion.append_to_brain_section(
                section="Stock Notes",
                ticker=ticker,
                content=note,
            )
            logger.debug(f"Brain note written for {ticker}")
        except Exception as e:
            logger.warning(f"Failed to write stock note for {ticker}: {e}")

    # ── Market Regime Log ─────────────────────────────────────────────────────

    async def write_market_regime(
        self,
        regime: str,
        vix: Optional[float],
        spy_vs_ema: str,
        reasoning: str,
    ) -> None:
        """Write daily market regime assessment."""
        notion = self._get_notion()
        if not notion:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d")
        regime_emoji = {"bull": "🟢", "neutral": "🟡", "bear": "🔴"}.get(
            regime.lower(), "⚪"
        )

        note = (
            f"**{timestamp}** {regime_emoji} {regime.upper()}\n"
            f"VIX: {vix:.1f} | SPY: {spy_vs_ema}\n"
            f"{reasoning}"
        )

        try:
            await notion.append_to_brain_section(
                section="Market Regime Log",
                ticker=None,
                content=note,
            )
        except Exception as e:
            logger.warning(f"Failed to write regime log: {e}")

    # ── Trade Thesis ──────────────────────────────────────────────────────────

    async def write_trade_thesis(
        self,
        ticker: str,
        entry_price: float,
        stop_loss: float,
        target: float,
        thesis: str,
        what_breaks_it: str,
        confidence_score: float,
    ) -> None:
        """Write the thesis for a new open position."""
        notion = self._get_notion()
        if not notion:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        rr = (target - entry_price) / (entry_price - stop_loss) if entry_price != stop_loss else 0

        note = (
            f"**{timestamp}** 🎯 ENTERED {ticker}\n"
            f"Entry: ${entry_price:.2f} | Stop: ${stop_loss:.2f} | "
            f"Target: ${target:.2f} | R:R {rr:.1f}:1\n"
            f"Confidence: {confidence_score:.0f}/100\n\n"
            f"**Thesis:** {thesis}\n\n"
            f"**What breaks it:** {what_breaks_it}"
        )

        try:
            await notion.append_to_brain_section(
                section="Active Trade Thesis",
                ticker=ticker,
                content=note,
            )
        except Exception as e:
            logger.warning(f"Failed to write trade thesis for {ticker}: {e}")

    # ── Trade Lessons ─────────────────────────────────────────────────────────

    async def write_trade_lesson(
        self,
        ticker: str,
        entry_price: float,
        exit_price: float,
        pnl_pct: float,
        pnl_dollars: float,
        hold_days: int,
        exit_reason: str,
        lesson: str,
    ) -> None:
        """
        Write a lesson after every closed trade — win or loss.
        Fred learns from every trade. These notes are referenced in future analysis.
        """
        notion = self._get_notion()
        if not notion:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d")
        outcome_emoji = "🏆" if pnl_pct > 0 else "📉"

        note = (
            f"**{timestamp}** {outcome_emoji} {ticker} — "
            f"{pnl_pct:+.1f}% (${pnl_dollars:+.2f})\n"
            f"Entry: ${entry_price:.2f} → Exit: ${exit_price:.2f} "
            f"| Held {hold_days} day{'s' if hold_days != 1 else ''}\n"
            f"Exit reason: {exit_reason}\n\n"
            f"**Lesson:** {lesson}"
        )

        try:
            await notion.append_to_brain_section(
                section="Trade Lessons",
                ticker=ticker,
                content=note,
            )
            logger.info(f"Trade lesson written for {ticker}")
        except Exception as e:
            logger.warning(f"Failed to write trade lesson for {ticker}: {e}")

    # ── Setup Radar ───────────────────────────────────────────────────────────

    async def write_radar_entry(
        self,
        ticker: str,
        what_fred_sees: str,
        what_is_missing: str,
        confidence_score: float,
    ) -> None:
        """
        Add a stock to Fred's setup radar.
        These are setups that are close but not quite ready.
        """
        notion = self._get_notion()
        if not notion:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d")

        note = (
            f"**{timestamp}** 👀 {ticker} ({confidence_score:.0f}/100)\n"
            f"Sees: {what_fred_sees}\n"
            f"Missing: {what_is_missing}"
        )

        try:
            await notion.append_to_brain_section(
                section="Setup Radar",
                ticker=ticker,
                content=note,
            )
        except Exception as e:
            logger.warning(f"Failed to write radar entry for {ticker}: {e}")

    # ── Social/News Notes ─────────────────────────────────────────────────────

    async def write_social_observation(
        self,
        account: str,
        post_preview: str,
        impact: str,
        affected_tickers: list[str],
        fred_take: str,
    ) -> None:
        """Write a note about a significant social media post."""
        notion = self._get_notion()
        if not notion:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        tickers_str = ", ".join(affected_tickers) if affected_tickers else "General market"

        note = (
            f"**{timestamp}** 🐦 @{account} — {impact} impact\n"
            f"Post: \"{post_preview[:100]}\"\n"
            f"Affects: {tickers_str}\n"
            f"Fred's read: {fred_take}"
        )

        try:
            await notion.append_to_brain_section(
                section="Market Regime Log",  # Social events go in regime log
                ticker=None,
                content=note,
            )
        except Exception as e:
            logger.warning(f"Failed to write social observation: {e}")

    # ── Weekly Thesis ─────────────────────────────────────────────────────────

    async def write_weekly_thesis(self, thesis: str) -> None:
        """Write Fred's Sunday evening weekly thesis."""
        notion = self._get_notion()
        if not notion:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d")
        note = f"**Week of {timestamp}**\n\n{thesis}"

        try:
            await notion.append_to_brain_section(
                section="Weekly Thesis",
                ticker=None,
                content=note,
            )
            logger.info("Weekly thesis written to Fred's Brain")
        except Exception as e:
            logger.warning(f"Failed to write weekly thesis: {e}")


# Global singleton
brain_writer = FredBrainWriter()

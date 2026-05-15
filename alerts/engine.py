"""
alerts/engine.py
================
Central alert orchestration hub. Fred's nervous system.

All monitors (twitter, news, stop loss, technical) funnel into here.
AlertEngine decides what gets sent, prioritizes urgency, and coordinates
with the brain for context-aware messages.

Alert flow:
1. Monitor detects event
2. Calls AlertEngine.process_*()
3. Engine cross-references portfolio and watchlist
4. Engine calls Brain for analysis if needed
5. Engine sends SMS via Twilio
6. Engine logs to Notion
"""

import asyncio
from datetime import datetime
from typing import Optional
import logging as _logging; logger = _logging.getLogger(__name__)

from core.brain import fred_brain
from core.portfolio import portfolio_manager
from integrations.telegram_client import telegram_client
from integrations.notion_client import notion_client
from config.settings import settings


class AlertEngine:
    """
    Central hub for all Fred alerts.
    Coordinates between monitors, brain, SMS, and Notion.
    """

    def __init__(self):
        self._alert_queue: asyncio.Queue = asyncio.Queue()
        self._processing = False

    # ── Social Media Alerts ───────────────────────────────────────────────────

    async def process_social_post(
        self, account: str, post_text: str, post_data: dict
    ) -> None:
        """
        Handle a new high-impact social media post.
        Called by TwitterMonitor callback.
        """
        logger.info(f"Processing social post from @{account}")

        try:
            # Get current portfolio context
            positions = portfolio_manager.get_position_tickers()
            watchlist_raw = await notion_client.get_watchlist()
            watchlist_tickers = [w.get("ticker", "") for w in watchlist_raw]

            # Ask the brain to analyze
            analysis = fred_brain.analyze_social_post(
                account=account,
                post_text=post_text,
                open_positions=positions,
                watchlist=watchlist_tickers,
            )

            if analysis.get("error"):
                logger.error(f"Brain failed to analyze social post: {analysis}")
                return

            # Only alert if market-relevant and urgent enough
            impact = analysis.get("impact_level", "NONE")
            alert_user = analysis.get("alert_user", False)

            if not alert_user or impact in ["NONE", "LOW"]:
                logger.debug(f"Social post from @{account} filtered (impact={impact})")
                return

            # Build SMS message
            summary = analysis.get("summary", "No analysis available")
            positions_at_risk = analysis.get("positions_at_risk", [])
            watchlist_opp = analysis.get("watchlist_opportunity", [])
            suggested_action = analysis.get("suggested_action")

            urgency_str = analysis.get("urgency", "MEDIUM")

            extra_context = ""
            if positions_at_risk:
                extra_context += f"\nPositions affected: {', '.join(positions_at_risk)}"
            if watchlist_opp:
                extra_context += f"\nWatchlist opportunity: {', '.join(watchlist_opp)}"
            if suggested_action:
                extra_context += f"\nSuggested action: {suggested_action}"

            # Send the alert
            telegram_client.send(
                account=account,
                post_text=post_text,
                analysis=summary + extra_context,
                urgency=urgency_str,
            )

            # Log to Notion
            await notion_client.log_social_trigger(
                account=account,
                post_text=post_text,
                impact_level=impact,
                affected_tickers=analysis.get("affected_tickers", []),
                analysis=summary,
            )

            await notion_client.log_alert(
                alert_type="SOCIAL",
                ticker=None,
                message=f"@{account}: {post_text[:100]}",
                urgency=urgency_str,
                action_taken="SMS sent",
            )

        except Exception as e:
            logger.error(f"Social alert processing failed: {e}")

    # ── News Alerts ───────────────────────────────────────────────────────────

    async def process_news_article(self, article: dict) -> None:
        """
        Handle a new relevant news article.
        Called by NewsMonitor callback.
        """
        headline = article.get("headline", "")
        relevance = article.get("relevance", {})
        affected_tickers = relevance.get("tickers", [])
        affected_sectors = relevance.get("sectors", [])
        relevance_score = relevance.get("score", 0)

        # Only process high-relevance articles
        if relevance_score < 10:
            return

        # Check if any affected tickers are in our portfolio
        open_tickers = portfolio_manager.get_position_tickers()
        portfolio_hit = [t for t in affected_tickers if t in open_tickers]

        if not portfolio_hit and not affected_tickers:
            return

        logger.info(f"News alert: {headline[:60]}... (hits: {portfolio_hit})")

        impact = "HIGH" if portfolio_hit else "MEDIUM"

        # For portfolio hits, get the brain's analysis
        if portfolio_hit:
            for ticker in portfolio_hit[:2]:  # Max 2 tickers per alert
                position = portfolio_manager.get_position(ticker)
                if not position:
                    continue

                telegram_client.send(
                    headline=headline,
                    ticker=ticker,
                    impact=impact,
                )

                await notion_client.log_alert(
                    alert_type="NEWS",
                    ticker=ticker,
                    message=headline,
                    urgency=impact,
                    action_taken="SMS sent",
                )

    # ── Stop Loss Alerts ──────────────────────────────────────────────────────

    async def process_stop_loss_check(self, ticker: str, current_price: float) -> None:
        """
        Check and alert on stop loss proximity.
        Called by the scheduler during market hours.
        """
        position = portfolio_manager.get_position(ticker)
        if not position or not position.stop_loss:
            return

        pct_to_stop = position.pct_to_stop

        if pct_to_stop is None:
            return

        # CRITICAL: Stop actually hit
        if current_price <= position.stop_loss:
            logger.warning(f"🚨 STOP HIT: {ticker} at ${current_price:.2f}")
            telegram_client.send(
                ticker=ticker,
                current_price=current_price,
                stop_price=position.stop_loss,
                urgency="CRITICAL",
            )
            await notion_client.log_alert(
                alert_type="STOP_LOSS",
                ticker=ticker,
                message=f"STOP HIT at ${current_price:.2f} (stop was ${position.stop_loss:.2f})",
                urgency="CRITICAL",
                action_taken="CRITICAL SMS sent",
            )

        # WARNING: Getting close
        elif pct_to_stop <= 1.5:
            telegram_client.send(
                ticker=ticker,
                current_price=current_price,
                stop_price=position.stop_loss,
                urgency="HIGH",
            )
            await notion_client.log_alert(
                alert_type="STOP_APPROACHING",
                ticker=ticker,
                message=f"{pct_to_stop:.1f}% from stop at ${position.stop_loss:.2f}",
                urgency="HIGH",
                action_taken="Warning SMS sent",
            )

        # WATCH: Getting close-ish
        elif pct_to_stop <= 3.0:
            await notion_client.log_alert(
                alert_type="STOP_WATCH",
                ticker=ticker,
                message=f"{pct_to_stop:.1f}% from stop — monitoring",
                urgency="MEDIUM",
                action_taken="Logged only",
            )

    # ── Target Alerts ─────────────────────────────────────────────────────────

    async def process_target_check(self, ticker: str, current_price: float) -> None:
        """Alert when a position hits its price target."""
        position = portfolio_manager.get_position(ticker)
        if not position or not position.target:
            return

        if current_price >= position.target:
            logger.info(f"🎯 Target hit: {ticker} at ${current_price:.2f}")
            telegram_client.send(
                ticker=ticker,
                current_price=current_price,
                target=position.target,
            )
            await notion_client.log_alert(
                alert_type="TARGET_HIT",
                ticker=ticker,
                message=f"Target ${position.target:.2f} reached at ${current_price:.2f}",
                urgency="HIGH",
                action_taken="Target SMS sent",
            )

    # ── Technical Alerts ──────────────────────────────────────────────────────

    async def process_technical_alert(
        self,
        ticker: str,
        snapshot: dict,
        alert_type: str,
    ) -> None:
        """
        Handle technical indicator alerts (RSI overbought, MACD crossover, etc.)
        """
        position = portfolio_manager.get_position(ticker)
        if not position:
            return

        rsi = snapshot.get("rsi", 50)
        current_price = snapshot.get("price", 0)
        pnl_pct = position.pnl_pct

        if alert_type == "RSI_OVERBOUGHT" and rsi > 75:
            msg = (
                f"⚠️ {ticker} RSI ALERT\n"
                f"RSI: {rsi:.0f} (overbought territory)\n"
                f"Current: ${current_price:.2f} ({pnl_pct:+.1f}%)\n"
                f"Consider taking profits or trailing your stop."
            )
            telegram_client.send(msg, alert_key=f"rsi_overbought_{ticker}")

        elif alert_type == "MACD_BEARISH":
            msg = (
                f"📉 {ticker} MACD REVERSAL\n"
                f"MACD bearish crossover detected.\n"
                f"Current: ${current_price:.2f} ({pnl_pct:+.1f}%)\n"
                f"Momentum shifting. Tighten your stop."
            )
            telegram_client.send(msg, alert_key=f"macd_bearish_{ticker}")

        await notion_client.log_alert(
            alert_type=f"TECHNICAL_{alert_type}",
            ticker=ticker,
            message=f"{alert_type} on {ticker} at ${current_price:.2f}",
            urgency="MEDIUM",
        )

    # ── Entry Signal Alerts ────────────────────────────────────────────────────

    async def process_entry_signal(self, signal) -> None:
        """
        Alert user to a potential entry opportunity.
        Only fires for all-clear signals.
        """
        if not signal.all_clear:
            return

        ticker = signal.ticker
        logger.info(f"📈 Entry signal: {ticker} ({signal.confidence.total:.0f}/100)")

        telegram_client.send(
            ticker=ticker,
            signal_summary=signal.summary_str(),
        )

        await notion_client.log_alert(
            alert_type="ENTRY_SIGNAL",
            ticker=ticker,
            message=f"Entry signal — score {signal.confidence.total:.0f}/100",
            urgency="MEDIUM",
            action_taken="SMS sent",
        )

    # ── Morning Brief ─────────────────────────────────────────────────────────

    async def send_morning_brief(self) -> None:
        """
        Generate and send the daily morning brief.
        Called by scheduler at 8:30 AM ET.
        """
        from alerts.morning_brief import MorningBriefGenerator
        generator = MorningBriefGenerator()
        await generator.generate_and_send()

    # ── Truth Social Fast Path ────────────────────────────────────────────────

    async def process_truth_social_post(
        self,
        source: str,
        account: str,
        text: str,
        published: str,
        relevance: dict,
    ) -> None:
        """
        Handle Truth Social post — uses fast path for market-relevant content.
        Phase 1 fires immediately. Phase 2 (Claude analysis) fires 60 sec later.
        """
        if not relevance.get("is_market_relevant"):
            logger.debug(f"Truth Social post filtered — not market relevant")
            return

        logger.info(
            f"Market-relevant Truth Social post — "
            f"relevance score: {relevance['score']}"
        )

        try:
            from alerts.trump_fast_path import trump_fast_path

            positions = portfolio_manager.get_position_tickers()
            try:
                watchlist_raw = await notion_client.get_watchlist()
                watchlist = [w.get("ticker", "") for w in watchlist_raw]
            except Exception:
                watchlist = []

            # Run fast path as background task — don't block the monitor loop
            asyncio.create_task(
                trump_fast_path.process(
                    post_text=text,
                    relevance=relevance,
                    open_positions=positions,
                    watchlist=watchlist,
                    source=source,
                )
            )

            # Log to Notion alert log
            try:
                await notion_client.log_alert(
                    alert_type="TRUTH_SOCIAL",
                    ticker=None,
                    message=text[:200],
                    urgency="CRITICAL" if relevance["score"] >= 60 else "HIGH",
                    action_taken="Fast path triggered",
                )
            except Exception as e:
                logger.debug(f"Alert log error: {e}")

        except Exception as e:
            logger.error(f"Truth Social processing failed: {e}")

        # ── EOD Debrief ───────────────────────────────────────────────────────────

    async def send_eod_debrief(self) -> None:
        """Send end-of-day debrief at 4:30 PM ET."""
        try:
            await portfolio_manager.refresh_prices()
            positions = list(portfolio_manager._positions.values())

            from core.market import market_data
            market_summary = {}
            spy = market_data.get_snapshot("SPY")
            qqq = market_data.get_snapshot("QQQ")
            vix = market_data.get_snapshot("^VIX")
            market_summary["sp_pct"] = spy.get("change_pct", 0)
            market_summary["nasdaq_pct"] = qqq.get("change_pct", 0)
            market_summary["vix"] = vix.get("price", 0)

            from datetime import datetime
            brief = fred_brain.generate_eod_debrief(context={
                "date": datetime.now().strftime("%A, %b %d"),
                "mode": "builder",
                "positions": [p.to_dict() for p in positions],
                "closed_today": [],
                "day_pnl": f"${sum(p.pnl_dollars for p in positions):+.2f}",
                "challenge_status": "Builder Mode — intelligent compounding." if False else "",
            })

            telegram_client.send(brief)
            logger.info("EOD debrief sent")

        except Exception as e:
            logger.error(f"EOD debrief failed: {e}")
            telegram_client.send("⚠️ EOD debrief failed to generate. Check logs.")

    # ── Sunday Sync ───────────────────────────────────────────────────────────

    async def send_sunday_sync(self) -> None:
        """Sunday evening portfolio sync and weekly summary."""
        try:
            await portfolio_manager.refresh_prices()
            positions = list(portfolio_manager._positions.values())
            journal_stats = await notion_client.get_journal_stats()

            lines = [
                "📊 WEEKLY PERFORMANCE",
                f"Trades: {journal_stats.get('total_trades', 0)}",
                f"Win Rate: {journal_stats.get('win_rate', 0):.0f}%",
                f"Total P&L: ${journal_stats.get('total_pnl', 0):+.2f}",
                f"Profit Factor: {journal_stats.get('profit_factor', 0):.1f}",
                "",
                "📂 OPEN POSITIONS",
            ]

            for p in positions:
                lines.append(p.status_line())

            lines.extend([
                "",
                "🗓️ MONDAY GAME PLAN",
                "Text Fred 'scan' for tomorrow's setups.",
            ])

            telegram_client.send("\n".join(lines))
            logger.info("Sunday sync sent")

        except Exception as e:
            logger.error(f"Sunday sync failed: {e}")


# Global singleton
alert_engine = AlertEngine()

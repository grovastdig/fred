"""
alerts/morning_brief.py
========================
Daily morning brief — Fred's first text of the day.

Sent at 8:30 AM ET, ~1 hour before market open.

Covers:
1. Overnight market tone (futures, VIX, macro)
2. Each open position — overnight news, health check
3. Top 1-2 watchlist setups that are close to entry
4. Earnings and macro events today
5. Today's game plan in one sentence
"""

import logging as _logging; logger = _logging.getLogger(__name__)

from core.brain import fred_brain
from core.market import market_data
from core.portfolio import portfolio_manager
from integrations.notion_client import notion_client
from integrations.telegram_client import telegram_client
from integrations.news_monitor import news_monitor


class MorningBriefGenerator:
    """
    Assembles and delivers the daily morning brief.
    """

    async def generate_and_send(self) -> None:
        """Full pipeline: gather data → brief → send."""
        try:
            logger.info("Generating morning brief...")

            # 1. Refresh positions with latest prices
            await portfolio_manager.load_positions()
            await portfolio_manager.refresh_prices()

            positions = list(portfolio_manager._positions.values())
            watchlist = await notion_client.get_watchlist()

            # 2. Get macro snapshot
            macro = market_data.get_macro_snapshot()
            macro_formatted = self._format_macro(macro)

            # 3. Get sector performance
            sectors = market_data.get_sector_performance()
            top_sector = sectors.get("top_sector", "N/A")
            worst_sector = sectors.get("worst_sector", "N/A")

            # 4. Get this week's earnings for positions
            position_tickers = [p.ticker for p in positions]
            watchlist_tickers = [w.get("ticker", "") for w in watchlist]
            all_tickers = list(set(position_tickers + watchlist_tickers))

            earnings_events = await news_monitor.get_earnings_this_week(all_tickers)
            econ_events = news_monitor.get_upcoming_economic_events()

            # 5. Get overnight news headlines
            market_summary = await news_monitor.get_market_summary()
            headlines = market_summary.get("headlines", [])

            # 6. Format events for brief
            upcoming_events = []
            for e in earnings_events[:3]:
                upcoming_events.append(
                    f"{e['ticker']} earnings in {e['days_until']} day(s)"
                )
            for e in econ_events[:2]:
                upcoming_events.append(f"{e['name']} ({e['market_impact']} impact)")

            # 7. Generate brief via Claude
            brief = fred_brain.generate_morning_brief(
                positions=[p.to_dict() for p in positions],
                watchlist=watchlist,
                market_data=macro_formatted,
                news_headlines=headlines,
                upcoming_events=upcoming_events,
            )

            # 8. Prepend sector data
            sector_line = f"🔥 Hot sector: {top_sector} | Cold: {worst_sector}\n\n"
            full_brief = sector_line + brief

            # 9. Send it
            telegram_client.send(full_brief)
            logger.info("Morning brief sent successfully")

        except Exception as e:
            logger.error(f"Morning brief generation failed: {e}")
            # Send a minimal backup brief
            try:
                telegram_client.send(
                    "Good morning. Brief generation failed — check Fred's logs.\n"
                    "Text 'status' for portfolio health."
                )
            except Exception:
                pass

    def _format_macro(self, macro: dict) -> dict:
        """Format macro data for brain consumption."""
        def fmt(val):
            if val is None:
                return "N/A"
            if isinstance(val, float):
                return f"{val:+.2f}"
            return str(val)

        return {
            "sp_futures_pct": fmt(macro.get("sp_futures_pct")),
            "nasdaq_futures_pct": fmt(macro.get("nasdaq_futures_pct")),
            "vix": fmt(macro.get("vix")),
            "dxy": fmt(macro.get("dxy")),
            "oil": fmt(macro.get("oil")),
            "gold": fmt(macro.get("gold")),
            "ten_yr": fmt(macro.get("ten_yr")),
        }

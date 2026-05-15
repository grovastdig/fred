"""
alerts/technical_alerts.py
===========================
Technical signal scanner and alert handler.

Runs every 15 minutes during market hours.
Scans the watchlist + universe for new entry setups.
Alerts the user when a strong setup appears.
"""

import asyncio
import logging as _logging; logger = _logging.getLogger(__name__)

from core.market import market_data
from core.signals import signal_engine
from core.portfolio import portfolio_manager
from integrations.notion_client import notion_client
from integrations.alpaca_client import alpaca_client
from alerts.engine import alert_engine


class TechnicalAlertScanner:
    """
    Scans for new entry setups on the watchlist and broader universe.
    Sends alerts for all-clear signals.
    """

    def __init__(self):
        self._running = False
        self._scan_interval = 900  # 15 minutes

    async def start(self) -> None:
        """Start the technical scan loop."""
        self._running = True
        logger.info("Technical alert scanner started")

        while self._running:
            try:
                if alpaca_client.is_market_open():
                    await self._run_scan()
            except Exception as e:
                logger.error(f"Technical scanner error: {e}")

            await asyncio.sleep(self._scan_interval)

    def stop(self) -> None:
        self._running = False

    async def _run_scan(self) -> None:
        """Full scan cycle: watchlist + universe."""
        logger.debug("Running technical scan...")

        # Get regime for context
        regime = market_data.get_market_regime()

        # 1. Scan watchlist first (priority)
        watchlist = await notion_client.get_watchlist()
        if watchlist:
            watchlist_tickers = [w.get("ticker", "") for w in watchlist if w.get("ticker")]
            snapshots = market_data.get_bulk_snapshots(watchlist_tickers)

            signals = signal_engine.screen_watchlist(
                watchlist=watchlist,
                snapshots=snapshots,
                market_regime=regime,
            )

            for signal in signals:
                if signal.all_clear:
                    await alert_engine.process_entry_signal(signal)

        # 2. Quick scan of broader universe for new opportunities
        candidates = market_data.scan_momentum_stocks()

        if candidates:
            # Only process top 5 candidates to avoid alert spam
            for candidate in candidates[:5]:
                ticker = candidate.get("ticker")
                if not ticker:
                    continue

                # Skip if already in portfolio
                if portfolio_manager.has_position(ticker):
                    continue

                # Quick signal evaluation
                signal = signal_engine.evaluate_entry(
                    ticker=ticker,
                    snapshot=candidate,
                    market_regime=regime,
                )

                # Only alert on 6/7+ gate signals with 70+ score
                if signal.gates_passed >= 6 and signal.confidence and signal.confidence.total >= 70:
                    await alert_engine.process_entry_signal(signal)

        logger.debug("Technical scan complete")


# Singleton
technical_scanner = TechnicalAlertScanner()

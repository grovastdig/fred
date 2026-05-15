"""
alerts/stop_loss.py
====================
Stop loss monitoring — Fred's most important job.

Monitors ALL open positions every 5 minutes during market hours.
Fires alerts at:
- 3% from stop: Watch alert
- 1.5% from stop: Warning alert
- Stop hit: CRITICAL — EXIT IMMEDIATELY

Also monitors RSI overbought and MACD reversals
for early exit signals.
"""

import asyncio
import logging as _logging; logger = _logging.getLogger(__name__)

from core.market import market_data
from core.portfolio import portfolio_manager
from core.signals import signal_engine
from alerts.engine import alert_engine
from integrations.alpaca_client import alpaca_client


class StopLossMonitor:
    """
    Real-time stop loss and position health monitoring.
    Runs continuously during market hours.
    """

    def __init__(self):
        self._running = False
        self._check_interval = 300  # 5 minutes

    async def start(self) -> None:
        """Start the stop loss monitoring loop."""
        self._running = True
        logger.info("Stop loss monitor started")

        while self._running:
            try:
                if alpaca_client.is_market_open():
                    await self._check_all_positions()
                else:
                    logger.debug("Market closed — stop loss monitor sleeping")
            except Exception as e:
                logger.error(f"Stop loss monitor error: {e}")

            await asyncio.sleep(self._check_interval)

    def stop(self) -> None:
        self._running = False

    async def _check_all_positions(self) -> None:
        """Check all open positions for stop loss proximity."""
        positions = list(portfolio_manager._positions.values())

        if not positions:
            return

        logger.debug(f"Checking {len(positions)} positions for stop/target alerts")

        for position in positions:
            try:
                await self._check_position(position)
            except Exception as e:
                logger.error(f"Error checking position {position.ticker}: {e}")

    async def _check_position(self, position) -> None:
        """Full health check on a single position."""
        ticker = position.ticker

        # Get current market data
        snapshot = market_data.get_snapshot(ticker)
        if "error" in snapshot:
            logger.warning(f"Could not get data for {ticker}: {snapshot.get('error')}")
            return

        current_price = snapshot.get("price", 0)
        if not current_price:
            return

        # Update current price in memory
        portfolio_manager._positions[ticker].current_price = current_price

        # ── Stop Loss Check ──
        await alert_engine.process_stop_loss_check(ticker, current_price)

        # ── Target Check ──
        await alert_engine.process_target_check(ticker, current_price)

        # ── Technical Exit Signals ──
        rsi = snapshot.get("rsi", 50)
        macd_bearish = snapshot.get("macd_bearish_crossover", False)

        if rsi > 75:
            await alert_engine.process_technical_alert(ticker, snapshot, "RSI_OVERBOUGHT")

        if macd_bearish:
            await alert_engine.process_technical_alert(ticker, snapshot, "MACD_BEARISH")

        # ── Full Exit Signal Evaluation ──
        exit_signal = signal_engine.evaluate_exit(
            position=position.to_dict(),
            snapshot=snapshot,
        )

        if exit_signal.urgency in ["HIGH", "CRITICAL"] and exit_signal.alert_user:
            logger.warning(f"Exit signal for {ticker}: {exit_signal.urgency}")


# Singleton
stop_loss_monitor = StopLossMonitor()

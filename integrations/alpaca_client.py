"""
integrations/alpaca_client.py
==============================
Alpaca Markets integration — paper trading mirror of Robinhood.

This is how Fred "watches" your portfolio 24/7 without
touching your real Robinhood account.

Flow:
1. You send a Robinhood screenshot
2. Fred reads it and syncs Alpaca paper account to match
3. Fred watches Alpaca via official API for price monitoring
4. Alerts fire based on Alpaca position data

Paper trading URL: https://paper-api.alpaca.markets
Live trading URL:  https://api.alpaca.markets  (FUTURE — paper first)
"""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestBarRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime
from typing import Optional
import logging as _logging; logger = _logging.getLogger(__name__)

from config.settings import settings


class AlpacaClient:
    """
    Alpaca paper trading client.
    Mirrors Robinhood positions and provides real-time price data.
    """

    def __init__(self):
        self.trading_client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=True,  # ALWAYS paper — never flip this to False without explicit decision
        )
        self.data_client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        logger.info("Alpaca paper trading client initialized")

    # ── Account Info ─────────────────────────────────────────────────────────

    async def get_account(self) -> dict:
        """Get account details — cash, equity, buying power."""
        try:
            account = self.trading_client.get_account()
            return {
                "equity": float(account.equity),
                "cash": float(account.cash),
                "buying_power": float(account.buying_power),
                "portfolio_value": float(account.portfolio_value),
                "last_equity": float(account.last_equity),
                "daytrade_count": account.daytrade_count,
                "pattern_day_trader": account.pattern_day_trader,
            }
        except Exception as e:
            logger.error(f"Failed to get Alpaca account: {e}")
            return {}

    # ── Positions ─────────────────────────────────────────────────────────────

    async def get_positions(self) -> list[dict]:
        """Get all open positions in Alpaca paper account."""
        try:
            positions = self.trading_client.get_all_positions()
            return [
                {
                    "ticker": p.symbol,
                    "shares": float(p.qty),
                    "entry_price": float(p.avg_entry_price),
                    "current_price": float(p.current_price),
                    "market_value": float(p.market_value),
                    "unrealized_pl": float(p.unrealized_pl),
                    "unrealized_plpc": float(p.unrealized_plpc) * 100,
                    "side": p.side,
                }
                for p in positions
            ]
        except Exception as e:
            logger.error(f"Failed to get Alpaca positions: {e}")
            return []

    async def get_position(self, ticker: str) -> Optional[dict]:
        """Get a single position by ticker."""
        try:
            position = self.trading_client.get_open_position(ticker.upper())
            return {
                "ticker": position.symbol,
                "shares": float(position.qty),
                "entry_price": float(position.avg_entry_price),
                "current_price": float(position.current_price),
                "market_value": float(position.market_value),
                "unrealized_pl": float(position.unrealized_pl),
                "unrealized_plpc": float(position.unrealized_plpc) * 100,
            }
        except Exception as e:
            logger.debug(f"No Alpaca position for {ticker}: {e}")
            return None

    # ── Orders ────────────────────────────────────────────────────────────────

    async def place_order(
        self,
        ticker: str,
        qty: float,
        side: str = "buy",
        order_type: str = "market",
        limit_price: Optional[float] = None,
    ) -> Optional[str]:
        """
        Place a paper trade order to mirror Robinhood position.
        Returns order ID.
        """
        try:
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

            if order_type == "market":
                request = MarketOrderRequest(
                    symbol=ticker.upper(),
                    qty=qty,
                    side=order_side,
                    time_in_force=TimeInForce.DAY,
                )
            elif order_type == "limit" and limit_price:
                request = LimitOrderRequest(
                    symbol=ticker.upper(),
                    qty=qty,
                    side=order_side,
                    time_in_force=TimeInForce.DAY,
                    limit_price=limit_price,
                )
            else:
                raise ValueError(f"Unknown order type: {order_type}")

            order = self.trading_client.submit_order(order_data=request)
            logger.info(
                f"Alpaca paper order placed: {side.upper()} {qty} {ticker} — Order ID: {order.id}"
            )
            return str(order.id)

        except Exception as e:
            logger.error(f"Alpaca order failed for {ticker}: {e}")
            return None

    async def close_position(self, ticker: str) -> bool:
        """Close/sell entire position in Alpaca paper account."""
        try:
            self.trading_client.close_position(ticker.upper())
            logger.info(f"Alpaca paper position closed: {ticker}")
            return True
        except Exception as e:
            logger.error(f"Failed to close Alpaca position {ticker}: {e}")
            return False

    async def close_all_positions(self) -> bool:
        """Emergency — close all positions at once."""
        try:
            self.trading_client.close_all_positions(cancel_orders=True)
            logger.warning("All Alpaca paper positions closed")
            return True
        except Exception as e:
            logger.error(f"Failed to close all positions: {e}")
            return False

    # ── Sync from Screenshot ─────────────────────────────────────────────────

    async def sync_from_robinhood_data(self, robinhood_positions: list[dict]) -> dict:
        """
        Sync Alpaca paper account to match parsed Robinhood data.
        Called after user sends a Robinhood screenshot.

        robinhood_positions format:
        [{"ticker": "NVDA", "shares": 20, "avg_cost": 127.50}, ...]
        """
        results = {
            "synced": [],
            "failed": [],
            "closed_in_alpaca": [],
        }

        # Get current Alpaca positions
        current_alpaca = {p["ticker"]: p for p in await self.get_positions()}
        robinhood_tickers = {p["ticker"].upper() for p in robinhood_positions}

        # Close positions in Alpaca that are no longer in Robinhood
        for ticker in list(current_alpaca.keys()):
            if ticker not in robinhood_tickers:
                success = await self.close_position(ticker)
                if success:
                    results["closed_in_alpaca"].append(ticker)

        # Sync each Robinhood position to Alpaca
        for rh_pos in robinhood_positions:
            ticker = rh_pos.get("ticker", "").upper()
            rh_shares = float(rh_pos.get("shares", 0))

            if not ticker or rh_shares <= 0:
                continue

            alpaca_pos = current_alpaca.get(ticker)
            alpaca_shares = float(alpaca_pos["shares"]) if alpaca_pos else 0

            try:
                if abs(rh_shares - alpaca_shares) < 0.01:
                    # Already synced
                    results["synced"].append(ticker)
                    continue

                if alpaca_shares > 0:
                    # Close existing and replace with correct size
                    await self.close_position(ticker)

                # Buy the correct number of shares
                order_id = await self.place_order(
                    ticker=ticker,
                    qty=rh_shares,
                    side="buy",
                    order_type="market",
                )

                if order_id:
                    results["synced"].append(ticker)
                else:
                    results["failed"].append(ticker)

            except Exception as e:
                logger.error(f"Sync failed for {ticker}: {e}")
                results["failed"].append(ticker)

        logger.info(
            f"Alpaca sync complete: {len(results['synced'])} synced, "
            f"{len(results['failed'])} failed, "
            f"{len(results['closed_in_alpaca'])} closed"
        )
        return results

    # ── Market Hours ──────────────────────────────────────────────────────────

    def is_market_open(self) -> bool:
        """Check if market is currently open."""
        try:
            clock = self.trading_client.get_clock()
            return clock.is_open
        except Exception as e:
            logger.error(f"Failed to check market status: {e}")
            # Default to checking time-based
            now = datetime.now()
            is_weekday = now.weekday() < 5
            market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
            return is_weekday and market_open <= now <= market_close

    def get_next_market_open(self) -> Optional[datetime]:
        """Get the next market open time."""
        try:
            calendar = self.trading_client.get_calendar()
            for day in calendar:
                if day.date >= datetime.now().date():
                    return day.open
            return None
        except Exception as e:
            logger.error(f"Failed to get market calendar: {e}")
            return None


# Global singleton
alpaca_client = AlpacaClient()

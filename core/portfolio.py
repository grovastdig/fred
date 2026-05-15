"""
core/portfolio.py
=================
Portfolio manager. Tracks all positions, P&L, and account state.
Source of truth is Notion. Alpaca paper account mirrors positions.

This module is the central hub that other components query
to understand the current state of the portfolio.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging as _logging; logger = _logging.getLogger(__name__)

from core.market import market_data as md


@dataclass
class Position:
    """A single open position."""
    id: str                          # Notion page ID
    ticker: str
    shares: float
    entry_price: float
    current_price: float = 0.0
    stop_loss: float = 0.0
    target: float = 0.0
    entry_date: Optional[str] = None
    thesis: str = ""
    catalyst_type: str = ""
    sector: str = ""
    confidence_at_entry: float = 0.0

    @property
    def cost_basis(self) -> float:
        return self.shares * self.entry_price

    @property
    def market_value(self) -> float:
        return self.shares * self.current_price

    @property
    def pnl_dollars(self) -> float:
        return self.market_value - self.cost_basis

    @property
    def pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0
        return ((self.current_price - self.entry_price) / self.entry_price) * 100

    @property
    def pct_to_stop(self) -> Optional[float]:
        if not self.stop_loss or not self.current_price:
            return None
        return ((self.current_price - self.stop_loss) / self.current_price) * 100

    @property
    def pct_to_target(self) -> Optional[float]:
        if not self.target or not self.current_price:
            return None
        return ((self.target - self.current_price) / self.current_price) * 100

    @property
    def is_profitable(self) -> bool:
        return self.pnl_dollars > 0

    @property
    def is_winner(self) -> bool:
        """Alias for is_profitable — used in portfolio summary."""
        return self.pnl_dollars > 0

    @property
    def stop_is_near(self) -> bool:
        """True if price is within 3% of stop loss."""
        pct = self.pct_to_stop
        return pct is not None and pct <= 3.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "shares": self.shares,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "stop_loss": self.stop_loss,
            "target": self.target,
            "entry_date": self.entry_date,
            "thesis": self.thesis,
            "catalyst_type": self.catalyst_type,
            "sector": self.sector,
            "confidence_at_entry": self.confidence_at_entry,
            "pnl_dollars": self.pnl_dollars,
            "pnl_pct": self.pnl_pct,
        }

    def status_line(self) -> str:
        """One-line status for SMS."""
        pnl_str = f"{self.pnl_pct:+.1f}% (${self.pnl_dollars:+.0f})"
        stop_str = f"Stop ${self.stop_loss:.2f}" if self.stop_loss else "No stop set ⚠️"
        return f"{self.ticker}: {self.shares:.0f}sh @ ${self.entry_price:.2f} | ${self.current_price:.2f} {pnl_str} | {stop_str}"


class PortfolioManager:
    """
    Manages the full portfolio state.

    - Reads positions from Notion (source of truth)
    - Updates current prices via market data
    - Calculates P&L and portfolio metrics
    - Syncs changes back to Notion and Alpaca
    """

    def __init__(self):
        self._positions: dict[str, Position] = {}
        self._last_refresh: Optional[datetime] = None
        self._account_value: float = 500.0  # Starting capital
        self._cash: float = 500.0

        # Lazy imports to avoid circular dependencies
        self._notion = None
        self._alpaca = None

    def _get_notion(self):
        if not self._notion:
            from integrations.notion_client import notion_client
            self._notion = notion_client
        return self._notion

    def _get_alpaca(self):
        if not self._alpaca:
            from integrations.alpaca_client import alpaca_client
            self._alpaca = alpaca_client
        return self._alpaca

    # ── Position Management ──────────────────────────────────────────────────

    async def load_positions(self) -> list[Position]:
        """Load all open positions from Notion."""
        try:
            notion = self._get_notion()
            raw_positions = await notion.get_open_positions()
            self._positions = {}

            for raw in raw_positions:
                ticker = raw.get("ticker", "").upper()
                if not ticker:
                    continue

                pos = Position(
                    id=raw.get("id", ticker),
                    ticker=ticker,
                    shares=float(raw.get("shares", 0)),
                    entry_price=float(raw.get("entry_price", 0)),
                    current_price=float(raw.get("current_price", raw.get("entry_price", 0))),
                    stop_loss=float(raw.get("stop_loss", 0)),
                    target=float(raw.get("target", 0)),
                    entry_date=raw.get("entry_date"),
                    thesis=raw.get("thesis", ""),
                    catalyst_type=raw.get("catalyst_type", ""),
                    sector=raw.get("sector", ""),
                    confidence_at_entry=float(raw.get("confidence_at_entry", 0)),
                )
                self._positions[ticker] = pos

            self._last_refresh = datetime.now()
            logger.info(f"Loaded {len(self._positions)} positions from Notion")
            return list(self._positions.values())

        except Exception as e:
            logger.error(f"Failed to load positions: {e}")
            return list(self._positions.values())  # Return cached if available

    async def refresh_prices(self) -> None:
        """Update current prices for all open positions."""
        if not self._positions:
            return

        tickers = list(self._positions.keys())
        snapshots = md.get_bulk_snapshots(tickers)

        for ticker, snapshot in snapshots.items():
            if ticker in self._positions and "price" in snapshot:
                self._positions[ticker].current_price = snapshot["price"]

        logger.debug(f"Refreshed prices for {len(tickers)} positions")

    async def add_position(
        self,
        ticker: str,
        shares: float,
        entry_price: float,
        stop_loss: float,
        target: float,
        thesis: str = "",
        catalyst_type: str = "",
        confidence_score: float = 0,
    ) -> Position:
        """
        Add a new position. Logs to Notion and mirrors to Alpaca.
        Called when user texts "bought NVDA 20 shares at 127..."
        """
        ticker = ticker.upper()

        # Create Notion entry
        notion = self._get_notion()
        notion_id = await notion.add_position({
            "ticker": ticker,
            "shares": shares,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "target": target,
            "thesis": thesis,
            "catalyst_type": catalyst_type,
            "confidence_at_entry": confidence_score,
            "entry_date": datetime.now().isoformat(),
            "status": "Open",
        })

        # Mirror to Alpaca paper account
        try:
            alpaca = self._get_alpaca()
            await alpaca.place_order(
                ticker=ticker,
                qty=int(shares),
                side="buy",
                order_type="market",
            )
        except Exception as e:
            logger.warning(f"Alpaca mirror failed for {ticker}: {e}")

        # Create local position object
        pos = Position(
            id=notion_id or ticker,
            ticker=ticker,
            shares=shares,
            entry_price=entry_price,
            current_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            thesis=thesis,
            catalyst_type=catalyst_type,
            confidence_at_entry=confidence_score,
            entry_date=datetime.now().isoformat(),
        )

        self._positions[ticker] = pos
        logger.info(f"Added position: {ticker} {shares}sh @ ${entry_price:.2f}")
        return pos

    async def close_position(
        self,
        ticker: str,
        exit_price: float,
        exit_reason: str = "manual",
    ) -> Optional[dict]:
        """
        Close a position. Logs trade to journal. Updates Notion.
        """
        ticker = ticker.upper()
        if ticker not in self._positions:
            logger.warning(f"Cannot close {ticker} — not in positions")
            return None

        pos = self._positions[ticker]
        pnl_dollars = (exit_price - pos.entry_price) * pos.shares
        pnl_pct = ((exit_price - pos.entry_price) / pos.entry_price) * 100

        trade_result = {
            "ticker": ticker,
            "shares": pos.shares,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "pnl_dollars": pnl_dollars,
            "pnl_pct": pnl_pct,
            "exit_reason": exit_reason,
            "entry_date": pos.entry_date,
            "exit_date": datetime.now().isoformat(),
            "thesis": pos.thesis,
            "confidence_at_entry": pos.confidence_at_entry,
            "outcome": "WIN" if pnl_dollars > 0 else "LOSS",
        }

        # Update Notion
        try:
            notion = self._get_notion()
            await notion.close_position(pos.id, trade_result)
            await notion.add_journal_entry(trade_result)
        except Exception as e:
            logger.error(f"Notion close failed for {ticker}: {e}")

        # Close on Alpaca
        try:
            alpaca = self._get_alpaca()
            await alpaca.close_position(ticker)
        except Exception as e:
            logger.warning(f"Alpaca close failed for {ticker}: {e}")

        # Remove from local cache
        del self._positions[ticker]

        logger.info(
            f"Closed {ticker}: {pnl_pct:+.1f}% (${pnl_dollars:+.2f}) — {exit_reason}"
        )
        return trade_result

    async def update_stop_loss(self, ticker: str, new_stop: float) -> bool:
        """Update stop loss for a position in Notion and locally."""
        ticker = ticker.upper()
        if ticker not in self._positions:
            return False

        self._positions[ticker].stop_loss = new_stop

        try:
            notion = self._get_notion()
            await notion.update_position(
                self._positions[ticker].id,
                {"stop_loss": new_stop}
            )
        except Exception as e:
            logger.error(f"Failed to update stop for {ticker}: {e}")
            return False

        return True

    # ── Portfolio Metrics ────────────────────────────────────────────────────

    def get_portfolio_summary(self) -> dict:
        """
        Full portfolio snapshot. Used in morning brief and SMS responses.
        """
        positions = list(self._positions.values())

        total_invested = sum(p.cost_basis for p in positions)
        total_value = sum(p.market_value for p in positions)
        total_pnl = sum(p.pnl_dollars for p in positions)
        total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0

        winners = [p for p in positions if p.is_profitable]
        losers = [p for p in positions if not p.is_profitable]

        return {
            "position_count": len(positions),
            "positions": [p.to_dict() for p in positions],
            "total_invested": total_invested,
            "total_value": total_value,
            "total_pnl_dollars": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "winners": len(winners),
            "losers": len(losers),
            "cash": self._cash,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
        }

    def get_portfolio_context_str(self) -> str:
        """
        Formatted portfolio context for injecting into Claude prompts.
        """
        summary = self.get_portfolio_summary()
        positions = self._positions

        if not positions:
            return "No open positions. Portfolio is 100% cash."

        lines = [
            f"Portfolio: {summary['position_count']} positions | "
            f"Total P&L: {summary['total_pnl_pct']:+.1f}% (${summary['total_pnl_dollars']:+.0f})",
            "",
        ]

        for ticker, pos in positions.items():
            lines.append(pos.status_line())

        return "\n".join(lines)

    def get_position_tickers(self) -> list[str]:
        """Returns list of all open position tickers."""
        return list(self._positions.keys())

    def get_position(self, ticker: str) -> Optional[Position]:
        """Get a single position by ticker."""
        return self._positions.get(ticker.upper())

    def has_position(self, ticker: str) -> bool:
        return ticker.upper() in self._positions

    def get_exposure_pct(self, account_value: float) -> float:
        """What % of account is currently invested."""
        if account_value <= 0:
            return 0
        invested = sum(p.cost_basis for p in self._positions.values())
        return (invested / account_value) * 100

    def parse_buy_message(self, message: str) -> Optional[dict]:
        """
        Parse a buy command from SMS.
        "bought NVDA 20 shares at 127 stop 122 target 138"
        "buy TSLA 10 @ 280 stop 270 target 300"
        """
        import re
        message = message.lower()

        # Extract ticker (all caps word)
        # Skip command words, find actual ticker symbol
        SKIP_WORDS = {'BUY', 'BOUGHT', 'SELL', 'SOLD', 'LONG', 'SHORT', 'AT', 'STOP', 'TARGET', 'SHARES', 'SH', 'IN', 'THE', 'FOR', 'A', 'AN'}
        ticker = None
        for word in message.upper().split():
            cleaned = re.sub(r'[^A-Z]', '', word)
            if cleaned and 1 <= len(cleaned) <= 5 and cleaned not in SKIP_WORDS:
                ticker = cleaned
                break

        # Extract shares — handles: "20 shares", "20 sh", "20 @", or just "20 at"
        shares_match = (
            re.search(r'(\d+\.?\d*)\s*(?:shares?|sh|@)', message) or
            re.search(r'(?:buy|bought|long)\s+[a-z]+\s+(\d+\.?\d*)\s+(?:at|@|shares?)', message)
        )
        shares = float(shares_match.group(1)) if shares_match else None

        # Extract price (after "at" or "@")
        price_match = re.search(r'(?:at|@)\s*\$?(\d+\.?\d*)', message)
        price = float(price_match.group(1)) if price_match else None

        # Extract stop
        stop_match = re.search(r'stop\s+\$?(\d+\.?\d*)', message)
        stop = float(stop_match.group(1)) if stop_match else None

        # Extract target
        target_match = re.search(r'target\s+\$?(\d+\.?\d*)', message)
        target = float(target_match.group(1)) if target_match else None

        if ticker and shares and price:
            return {
                "ticker": ticker,
                "shares": shares,
                "entry_price": price,
                "stop_loss": stop,
                "target": target,
            }
        return None


# Global singleton
portfolio_manager = PortfolioManager()

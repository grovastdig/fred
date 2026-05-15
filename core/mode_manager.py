"""
core/mode_manager.py
=====================
Fred operates in Builder Mode. One mode. Intelligent sizing. Compounding.

Position sizing by confidence score:
  90-100  →  25-28% of portfolio  (conviction)
  70-89   →  15-20%               (strong)
  50-69   →  8-12%                (moderate)
  Below 50 → skip                 (no half-baked trades)

State persists to both local file and Notion.
Survives Railway redeploys.
"""

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("fred.mode_manager")

STATE_FILE = Path("data/fred_state.json")


@dataclass
class FredState:
    """Fred's persistent runtime state."""
    # Portfolio
    current_balance: float = 0.0
    starting_balance: float = 0.0

    # PDT tracking (under $25k = max 3 day trades per rolling 5 business days)
    day_trade_dates: list = field(default_factory=list)

    # Performance
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl: float = 0.0

    # All-time high (for milestone texts)
    all_time_high: float = 0.0

    def to_dict(self) -> dict:
        return {
            "current_balance": self.current_balance,
            "starting_balance": self.starting_balance,
            "day_trade_dates": self.day_trade_dates,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "total_pnl": self.total_pnl,
            "all_time_high": self.all_time_high,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FredState":
        s = cls()
        s.current_balance = d.get("current_balance", 0.0)
        s.starting_balance = d.get("starting_balance", 0.0)
        s.day_trade_dates = d.get("day_trade_dates", [])
        s.total_trades = d.get("total_trades", 0)
        s.winning_trades = d.get("winning_trades", 0)
        s.total_pnl = d.get("total_pnl", 0.0)
        s.all_time_high = d.get("all_time_high", 0.0)
        return s


# Milestone thresholds — Fred sends a text when these are crossed
MILESTONES = [
    (1_000,    "Grand. First thousand. That's real."),
    (2_500,    "Two and a half thousand. Building now."),
    (5_000,    "Five grand. Halfway to something serious."),
    (10_000,   "Ten thousand. This is where it starts to matter."),
    (25_000,   "Twenty-five grand. PDT restrictions are gone. Different game now."),
    (50_000,   "Fifty thousand. Mate. That's serious capital."),
    (100_000,  "Six figures. Everything you've built to get here was worth it."),
]


class ModeManager:
    """
    Manages Fred's runtime state.
    Builder Mode only — intelligent sizing, sustainable compounding.
    """

    def __init__(self):
        self._state = self._load_state()
        self._milestone_thresholds = [m[0] for m in MILESTONES]
        logger.info(
            f"ModeManager ready — "
            f"balance: ${self._state.current_balance:,.2f} | "
            f"PDT remaining: {self.day_trades_remaining}"
        )

    # ── Position Sizing ───────────────────────────────────────────────────────

    def get_position_size(self, balance: float, confidence_score: float) -> float:
        """
        Returns position size as a fraction of portfolio.
        Builder Mode sizing — intelligent, sustainable.
        """
        if confidence_score >= 90:
            return 0.27   # 27% midpoint of conviction tier
        elif confidence_score >= 70:
            return 0.175  # 17.5% midpoint of strong tier
        elif confidence_score >= 50:
            return 0.10   # 10% midpoint of moderate tier
        return 0.0        # Skip anything below 50

    def get_position_size_label(self, confidence_score: float) -> str:
        if confidence_score >= 90:
            return "25-28% of portfolio (conviction)"
        elif confidence_score >= 70:
            return "15-20% of portfolio (strong)"
        elif confidence_score >= 50:
            return "8-12% of portfolio (moderate)"
        return "Skip — below minimum confidence"

    def get_dollar_size(self, confidence_score: float) -> float:
        """Dollar amount to put in this trade."""
        balance = self._state.current_balance
        if balance <= 0:
            return 0.0
        return balance * self.get_position_size(balance, confidence_score)

    # ── PDT Tracking ─────────────────────────────────────────────────────────

    def record_day_trade(self) -> None:
        """Record a day trade. Called when a same-day open+close occurs."""
        today = date.today().isoformat()
        self._state.day_trade_dates.append(today)
        self._save_state()
        logger.info(f"Day trade recorded. Remaining today: {self.day_trades_remaining}")

    @property
    def day_trades_remaining(self) -> int:
        """Day trades remaining in the rolling 5-business-day window."""
        cutoff = (datetime.now() - timedelta(days=7)).date()
        recent = [
            d for d in self._state.day_trade_dates
            if date.fromisoformat(d) >= cutoff
        ]
        return max(0, 3 - len(recent))

    @property
    def pdt_warning(self) -> Optional[str]:
        """Returns a warning string if at or near PDT limit. None if clear."""
        remaining = self.day_trades_remaining
        if remaining == 0:
            return (
                "⚠️ PDT LIMIT REACHED — 0 day trades left this week.\n"
                "Swing entries only. Hold overnight."
            )
        elif remaining == 1:
            return (
                "⚠️ PDT: 1 day trade left this week.\n"
                "Use it wisely or hold overnight."
            )
        return None

    # ── Balance + Performance ─────────────────────────────────────────────────

    def update_balance(self, new_balance: float) -> Optional[str]:
        """
        Update current balance. Returns milestone text if one was crossed.
        Called after every trade close.
        """
        old = self._state.current_balance
        self._state.current_balance = new_balance

        if new_balance > self._state.all_time_high:
            self._state.all_time_high = new_balance

        self._save_state()
        return self._check_milestones(new_balance)

    def _check_milestones(self, balance: float) -> Optional[str]:
        """Check if balance crossed a milestone. Returns celebration text."""
        for threshold, message in MILESTONES:
            if balance >= threshold and self._state.all_time_high < threshold:
                return f"💰 ${threshold:,.0f}\n{message}"
        return None

    def record_trade_result(self, pnl_dollars: float, won: bool) -> None:
        self._state.total_trades += 1
        if won:
            self._state.winning_trades += 1
        self._state.total_pnl += pnl_dollars
        self._save_state()

    # ── Context for prompts ───────────────────────────────────────────────────

    def get_mode_context_for_prompt(self) -> str:
        """Context string injected into Fred's system prompt."""
        balance = self._state.current_balance
        win_rate = (
            (self._state.winning_trades / self._state.total_trades * 100)
            if self._state.total_trades > 0 else 0
        )
        pdt_note = self.pdt_warning or f"PDT: {self.day_trades_remaining} day trades available"

        return (
            f"CURRENT STATE\n"
            f"Portfolio: ${balance:,.2f}\n"
            f"All-time high: ${self._state.all_time_high:,.2f}\n"
            f"Win rate: {win_rate:.0f}% ({self._state.winning_trades}W/{self._state.total_trades - self._state.winning_trades}L)\n"
            f"Total P&L: ${self._state.total_pnl:+,.2f}\n"
            f"{pdt_note}"
        )

    def get_performance_summary(self) -> str:
        """SMS-formatted performance summary."""
        balance = self._state.current_balance
        wins = self._state.winning_trades
        total = self._state.total_trades
        losses = total - wins
        win_rate = (wins / total * 100) if total > 0 else 0

        lines = [
            "📊 FRED — PERFORMANCE",
            f"Balance: ${balance:,.2f}",
            f"All-time high: ${self._state.all_time_high:,.2f}",
            f"Total P&L: ${self._state.total_pnl:+,.2f}",
            f"Trades: {total} ({wins}W / {losses}L)",
            f"Win rate: {win_rate:.0f}%",
            f"PDT remaining: {self.day_trades_remaining}/3",
        ]
        return "\n".join(lines)

    # ── State persistence ─────────────────────────────────────────────────────

    def _load_state(self) -> FredState:
        """Load from local file first, Notion fallback."""
        STATE_FILE.parent.mkdir(exist_ok=True)
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE) as f:
                    data = json.load(f)
                logger.info("State loaded from local file")
                return FredState.from_dict(data)
            except Exception as e:
                logger.warning(f"Local state load failed: {e}")

        try:
            import asyncio
            loop = asyncio.new_event_loop()
            notion_state = loop.run_until_complete(self._load_from_notion())
            loop.close()
            if notion_state:
                logger.info("State loaded from Notion")
                return FredState.from_dict(notion_state)
        except Exception as e:
            logger.debug(f"Notion state load failed: {e}")

        logger.info("Starting with fresh state")
        return FredState()

    async def _load_from_notion(self) -> dict:
        try:
            from integrations.notion_client import notion_client
            return await notion_client.load_fred_state()
        except Exception as e:
            logger.debug(f"Notion load error: {e}")
            return {}

    def _save_state(self) -> None:
        """Save to local file + Notion in background."""
        STATE_FILE.parent.mkdir(exist_ok=True)
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(self._state.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Local state save failed: {e}")

        def _save_async():
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self._save_to_notion())
                loop.close()
            except Exception as ex:
                logger.debug(f"Notion state save failed: {ex}")

        threading.Thread(target=_save_async, daemon=True).start()

    async def _save_to_notion(self) -> None:
        try:
            from integrations.notion_client import notion_client
            await notion_client.save_fred_state(self._state.to_dict())
        except Exception as e:
            logger.debug(f"Notion save error: {e}")


# Global singleton
mode_manager = ModeManager()

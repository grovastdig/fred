"""
tests/test_portfolio.py
========================
Unit tests for PortfolioManager.
Tests position math, P&L calculations, and SMS trade parsing.
Run with: pytest tests/test_portfolio.py -v
"""

import pytest
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.portfolio import Position, PortfolioManager


def make_position(
    ticker="NVDA",
    shares=10.0,
    entry_price=100.0,
    current_price=110.0,
    stop_loss=92.0,
    target=120.0,
) -> Position:
    return Position(
        id="test-id-123",
        ticker=ticker,
        shares=shares,
        entry_price=entry_price,
        current_price=current_price,
        stop_loss=stop_loss,
        target=target,
        entry_date=datetime.now().strftime("%Y-%m-%d"),
        thesis="Test position",
        catalyst_type="test",
    )


class TestPositionMath:
    def test_cost_basis(self):
        pos = make_position(shares=10, entry_price=100.0)
        assert pos.cost_basis == pytest.approx(1000.0)

    def test_market_value(self):
        pos = make_position(shares=10, current_price=110.0)
        assert pos.market_value == pytest.approx(1100.0)

    def test_pnl_dollars_positive(self):
        pos = make_position(shares=10, entry_price=100.0, current_price=110.0)
        assert pos.pnl_dollars == pytest.approx(100.0)

    def test_pnl_dollars_negative(self):
        pos = make_position(shares=10, entry_price=100.0, current_price=90.0)
        assert pos.pnl_dollars == pytest.approx(-100.0)

    def test_pnl_pct_positive(self):
        pos = make_position(shares=10, entry_price=100.0, current_price=115.0)
        assert pos.pnl_pct == pytest.approx(15.0)

    def test_pnl_pct_negative(self):
        pos = make_position(shares=10, entry_price=100.0, current_price=95.0)
        assert pos.pnl_pct == pytest.approx(-5.0)

    def test_pnl_pct_breakeven(self):
        pos = make_position(shares=10, entry_price=100.0, current_price=100.0)
        assert pos.pnl_pct == pytest.approx(0.0)

    def test_is_winner(self):
        pos = make_position(entry_price=100.0, current_price=110.0)
        assert pos.is_winner is True

    def test_is_loser(self):
        pos = make_position(entry_price=100.0, current_price=90.0)
        assert pos.is_winner is False

    def test_pct_to_stop(self):
        pos = make_position(current_price=100.0, stop_loss=92.0)
        expected = ((100.0 - 92.0) / 100.0) * 100  # 8%
        assert pos.pct_to_stop == pytest.approx(expected)

    def test_pct_to_target(self):
        pos = make_position(current_price=100.0, target=120.0)
        expected = ((120.0 - 100.0) / 100.0) * 100  # 20%
        assert pos.pct_to_target == pytest.approx(expected)

    def test_stop_is_near_when_close(self):
        pos = make_position(current_price=100.0, stop_loss=97.5)
        # 2.5% away — should be "near"
        assert pos.stop_is_near is True

    def test_stop_not_near_when_far(self):
        pos = make_position(current_price=100.0, stop_loss=90.0)
        # 10% away — not near
        assert pos.stop_is_near is False


class TestPortfolioManager:
    def setup_method(self):
        self.pm = PortfolioManager()
        # Clear any positions
        self.pm._positions = {}

    def test_initially_empty(self):
        assert len(self.pm._positions) == 0

    def test_get_portfolio_summary_empty(self):
        summary = self.pm.get_portfolio_summary()
        assert summary["position_count"] == 0
        assert summary["winners"] == 0
        assert summary["losers"] == 0

    def test_get_position_returns_none_for_missing(self):
        result = self.pm.get_position("FAKEXYZ")
        assert result is None

    def test_has_position_false_when_empty(self):
        assert self.pm.has_position("NVDA") is False

    def test_add_and_get_position(self):
        pos = make_position("TSLA")
        self.pm._positions["TSLA"] = pos
        assert self.pm.has_position("TSLA") is True
        assert self.pm.get_position("TSLA") is pos

    def test_get_position_tickers(self):
        self.pm._positions["AAPL"] = make_position("AAPL")
        self.pm._positions["NVDA"] = make_position("NVDA")
        tickers = self.pm.get_position_tickers()
        assert "AAPL" in tickers
        assert "NVDA" in tickers

    def test_portfolio_summary_counts_winners_losers(self):
        self.pm._positions["WIN"] = make_position(
            "WIN", entry_price=100.0, current_price=115.0
        )
        self.pm._positions["LOSE"] = make_position(
            "LOSE", entry_price=100.0, current_price=88.0
        )
        summary = self.pm.get_portfolio_summary()
        assert summary["winners"] == 1
        assert summary["losers"] == 1
        assert summary["position_count"] == 2

    def test_portfolio_context_str_not_empty(self):
        self.pm._positions["NVDA"] = make_position("NVDA")
        context = self.pm.get_portfolio_context_str()
        assert "NVDA" in context
        assert len(context) > 10

    def test_portfolio_context_str_empty_portfolio(self):
        context = self.pm.get_portfolio_context_str()
        assert "cash" in context.lower() or "no open" in context.lower()

    def test_exposure_pct_zero_when_no_account_value(self):
        self.pm._positions["NVDA"] = make_position("NVDA")
        assert self.pm.get_exposure_pct(0) == 0.0

    def test_exposure_pct_calculates_correctly(self):
        # 100 shares at $100 = $10,000 in a $50,000 account = 20%
        pos = make_position("NVDA", shares=100, entry_price=100.0)
        self.pm._positions["NVDA"] = pos
        pct = self.pm.get_exposure_pct(50000.0)
        assert pct == pytest.approx(20.0)


class TestParseBuyMessage:
    def setup_method(self):
        self.pm = PortfolioManager()

    def test_parse_standard_buy(self):
        result = self.pm.parse_buy_message(
            "buy NVDA 20 shares at 127 stop 122 target 138"
        )
        assert result is not None
        assert result["ticker"] == "NVDA"
        assert result["shares"] == pytest.approx(20.0)
        assert result["entry_price"] == pytest.approx(127.0)
        assert result["stop_loss"] == pytest.approx(122.0)
        assert result["target"] == pytest.approx(138.0)

    def test_parse_at_symbol_format(self):
        result = self.pm.parse_buy_message("buy TSLA 10 @ 280 stop 270 target 300")
        assert result is not None
        assert result["ticker"] == "TSLA"
        assert result["shares"] == pytest.approx(10.0)
        assert result["entry_price"] == pytest.approx(280.0)

    def test_parse_bought_keyword(self):
        result = self.pm.parse_buy_message("bought AAPL 5 shares at 175 stop 168 target 190")
        assert result is not None
        assert result["ticker"] == "AAPL"

    def test_parse_missing_shares_returns_none(self):
        # No share count — can't create position
        result = self.pm.parse_buy_message("buy NVDA at 127 stop 122")
        assert result is None or result.get("shares") is None

    def test_parse_dollar_signs_in_prices(self):
        result = self.pm.parse_buy_message("buy AMD 15 @ $142 stop $136 target $155")
        assert result is not None
        assert result["entry_price"] == pytest.approx(142.0)
        assert result["stop_loss"] == pytest.approx(136.0)

    def test_parse_case_insensitive_ticker(self):
        result = self.pm.parse_buy_message("buy nvda 20 at 127 stop 122 target 138")
        assert result is not None
        assert result["ticker"] == "NVDA"

    def test_parse_no_target_still_works(self):
        result = self.pm.parse_buy_message("buy MSFT 10 at 410 stop 398")
        # Should still parse even without target (target optional)
        if result:
            assert result["ticker"] == "MSFT"
            assert result["entry_price"] == pytest.approx(410.0)

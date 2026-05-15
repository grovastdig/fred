"""
Market Hours Utilities
======================
Helpers for knowing when markets are open, upcoming events,
and Eastern Time conversions. Fred needs to know what time it is
in the market's timezone at all times.
"""

from datetime import datetime, time, date, timedelta
from zoneinfo import ZoneInfo
import logging
log = logging.getLogger("fred.time_utils")

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def now_et() -> datetime:
    """Current time in Eastern Time."""
    return datetime.now(ET)


def now_utc() -> datetime:
    """Current time in UTC."""
    return datetime.now(UTC)


def is_market_open() -> bool:
    """Is the US stock market currently open for regular trading?"""
    now = now_et()

    # Weekend
    if now.weekday() >= 5:
        return False

    # Regular hours: 9:30 AM - 4:00 PM ET
    market_open = time(9, 30)
    market_close = time(16, 0)

    return market_open <= now.time() <= market_close


def is_premarket() -> bool:
    """Is it pre-market hours? (4:00 AM - 9:30 AM ET)"""
    now = now_et()
    if now.weekday() >= 5:
        return False
    return time(4, 0) <= now.time() < time(9, 30)


def is_afterhours() -> bool:
    """Is it after-hours? (4:00 PM - 8:00 PM ET)"""
    now = now_et()
    if now.weekday() >= 5:
        return False
    return time(16, 0) < now.time() <= time(20, 0)


def is_trading_day() -> bool:
    """Is today a trading day (weekday)?"""
    return now_et().weekday() < 5


def minutes_to_open() -> int:
    """Minutes until market opens. Returns 0 if already open."""
    now = now_et()
    if is_market_open():
        return 0
    if now.weekday() >= 5:
        days_ahead = 7 - now.weekday()
        next_open = now.replace(hour=9, minute=30, second=0) + timedelta(days=days_ahead)
    elif now.time() < time(9, 30):
        next_open = now.replace(hour=9, minute=30, second=0)
    else:
        # After close — next trading day
        next_open = (now + timedelta(days=1)).replace(hour=9, minute=30, second=0)
        while next_open.weekday() >= 5:
            next_open += timedelta(days=1)

    delta = next_open - now
    return max(0, int(delta.total_seconds() / 60))


def minutes_to_close() -> int:
    """Minutes until market closes. Returns 0 if already closed."""
    if not is_market_open():
        return 0
    now = now_et()
    close = now.replace(hour=16, minute=0, second=0)
    delta = close - now
    return max(0, int(delta.total_seconds() / 60))


def market_session() -> str:
    """
    Returns current session string:
    'pre-market' | 'open' | 'after-hours' | 'closed'
    """
    if is_premarket():
        return "pre-market"
    if is_market_open():
        return "open"
    if is_afterhours():
        return "after-hours"
    return "closed"


def today_et() -> date:
    """Today's date in Eastern Time."""
    return now_et().date()


def format_et(dt: datetime) -> str:
    """Format a datetime in Eastern Time for display."""
    if dt.tzinfo is None:
        dt = UTC.localize(dt)
    et = dt.astimezone(ET)
    return et.strftime("%I:%M %p ET")


def is_friday_close() -> bool:
    """Is it within 30 minutes of Friday's close?"""
    now = now_et()
    return now.weekday() == 4 and time(15, 30) <= now.time() <= time(16, 0)


def next_earnings_season() -> str:
    """Rough indicator of which earnings season we're in."""
    month = now_et().month
    if month in [1, 2]:
        return "Q4 Earnings (Jan-Feb)"
    elif month in [4, 5]:
        return "Q1 Earnings (Apr-May)"
    elif month in [7, 8]:
        return "Q2 Earnings (Jul-Aug)"
    elif month in [10, 11]:
        return "Q3 Earnings (Oct-Nov)"
    else:
        return "Off-Season"

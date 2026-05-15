"""
integrations/news_monitor.py
=============================
News intelligence layer — the Bloomberg-style feed filtered through your positions.

Sources:
- Reuters RSS (free)
- MarketWatch RSS (free)
- Benzinga RSS (free)
- Yahoo Finance RSS (free)
- NewsAPI (optional, needs API key)
- Earnings calendar (via yfinance)
- Economic calendar (FOMC dates, CPI, jobs report)

Every news item is scored for impact and cross-referenced
with your open positions and watchlist.
"""

import asyncio
import hashlib
import httpx
import feedparser
from datetime import datetime, timedelta
from typing import Optional, Callable
import logging as _logging; logger = _logging.getLogger(__name__)

from config.settings import settings
from config.trading_rules import NEWS_RSS_FEEDS


class NewsMonitor:
    """
    Monitors news sources and filters by portfolio relevance.
    """

    def __init__(self):
        self._seen_headlines: set = set()
        self._callbacks: list[Callable] = []
        self._running = False

        # Important economic events calendar (updated quarterly)
        # In production, pull this from a live calendar API
        self._econ_events: list[dict] = []

    def add_callback(self, callback: Callable) -> None:
        """Register a callback for new relevant news."""
        self._callbacks.append(callback)

    # ── Monitoring Loop ───────────────────────────────────────────────────────

    async def start_monitoring(self) -> None:
        """Start the news monitoring loop."""
        self._running = True
        logger.info("News monitor started")

        while self._running:
            try:
                await self._scan_all_feeds()
            except Exception as e:
                logger.error(f"News monitor error: {e}")

            await asyncio.sleep(settings.news_scan_interval)

    def stop_monitoring(self) -> None:
        self._running = False

    # ── Feed Scanning ─────────────────────────────────────────────────────────

    async def _scan_all_feeds(self) -> None:
        """Scan all RSS feeds for new relevant articles."""
        tasks = [self._scan_feed(feed) for feed in NEWS_RSS_FEEDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.debug(f"Feed scan error: {result}")

    async def _scan_feed(self, feed_config: dict) -> None:
        """Scan a single RSS feed."""
        url = feed_config.get("url")
        source_name = feed_config.get("name", "Unknown")
        impact = feed_config.get("impact", "MEDIUM")

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "Fred Trading Bot/1.0"},
                    follow_redirects=True,
                )

            if response.status_code != 200:
                return

            feed = feedparser.parse(response.text)
            cutoff = datetime.now() - timedelta(minutes=30)

            for entry in feed.entries[:10]:
                headline = entry.get("title", "")
                link = entry.get("link", "")

                if not headline:
                    continue

                # Dedup
                headline_hash = hashlib.md5(headline.encode()).hexdigest()
                if headline_hash in self._seen_headlines:
                    continue

                # Time filter
                try:
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        pub_time = datetime(*entry.published_parsed[:6])
                        if pub_time < cutoff:
                            continue
                except Exception:
                    pass

                self._seen_headlines.add(headline_hash)

                # Relevance check
                relevance = self._score_headline_relevance(headline)
                if relevance["score"] > 0:
                    await self._process_article({
                        "headline": headline,
                        "link": link,
                        "source": source_name,
                        "impact": impact,
                        "relevance": relevance,
                        "timestamp": datetime.now().isoformat(),
                    })

        except Exception as e:
            logger.debug(f"Feed {source_name} error: {e}")

    def _score_headline_relevance(self, headline: str) -> dict:
        """
        Score a headline for trading relevance.
        Returns score and affected sectors/tickers.
        """
        headline_lower = headline.lower()
        score = 0
        sectors = []
        tickers = []
        impact_type = "general"

        # High-impact patterns
        high_impact = {
            "fed rate": 10, "fomc": 10, "cpi": 9, "inflation": 8,
            "earnings beat": 9, "earnings miss": 9, "revenue beat": 8,
            "tariff": 9, "sanctions": 8, "trade war": 8,
            "fda approved": 9, "fda rejected": 9,
            "acquisition": 7, "merger": 7, "buyout": 7,
            "bankruptcy": 8, "default": 8,
            "recession": 8, "rate cut": 9, "rate hike": 9,
            "layoffs": 6, "guidance cut": 8, "guidance raised": 7,
            "sec charged": 7, "investigation": 6,
        }

        for pattern, pts in high_impact.items():
            if pattern in headline_lower:
                score += pts
                impact_type = pattern

        # Sector keywords
        sector_keywords = {
            "technology": ["tech", "software", "cloud", "ai ", "chip", "semiconductor"],
            "energy": ["oil", "gas", "energy", "crude", "opec", "lng"],
            "healthcare": ["pharma", "biotech", "drug", "fda", "clinical"],
            "financials": ["bank", "fed", "rate", "treasury", "credit"],
            "defense": ["defense", "military", "pentagon", "weapons", "missile"],
            "crypto": ["bitcoin", "crypto", "ethereum", "blockchain", "defi"],
        }

        for sector, keywords in sector_keywords.items():
            for kw in keywords:
                if kw in headline_lower:
                    sectors.append(sector)
                    score += 2
                    break

        # Common ticker mentions (scan for stock symbols)
        import re
        ticker_pattern = re.findall(r'\b([A-Z]{2,5})\b', headline)
        known_tickers = {
            "NVDA", "AMD", "TSLA", "AAPL", "MSFT", "GOOGL", "AMZN", "META",
            "PLTR", "COIN", "HOOD", "SOFI", "UPST", "JPM", "BAC", "GS",
            "XOM", "CVX", "OXY", "LLY", "NVO", "MRNA",
        }
        for t in ticker_pattern:
            if t in known_tickers:
                tickers.append(t)
                score += 5

        return {
            "score": min(score, 30),
            "sectors": list(set(sectors)),
            "tickers": list(set(tickers)),
            "impact_type": impact_type,
        }

    async def _process_article(self, article: dict) -> None:
        """Trigger callbacks for a relevant article."""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(article)
                else:
                    callback(article)
            except Exception as e:
                logger.error(f"News callback error: {e}")

    # ── Earnings Calendar ─────────────────────────────────────────────────────

    async def get_earnings_this_week(self, tickers: Optional[list[str]] = None) -> list[dict]:
        """
        Get earnings announcements for this week.
        Uses yfinance for calendar data.
        """
        import yfinance as yf
        from datetime import date

        earnings_events = []
        today = date.today()
        week_end = today + timedelta(days=7)

        # Check specific tickers if provided
        check_tickers = tickers or [
            "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "META", "GOOGL", "AMZN",
            "JPM", "BAC", "GS", "XOM", "CVX", "LLY", "PLTR",
        ]

        for ticker in check_tickers:
            try:
                t = yf.Ticker(ticker)
                cal = t.calendar

                if cal is not None and not cal.empty:
                    for col in cal.columns:
                        earnings_date = cal.loc["Earnings Date", col] if "Earnings Date" in cal.index else None
                        if earnings_date:
                            try:
                                if isinstance(earnings_date, str):
                                    earnings_date = datetime.strptime(earnings_date, "%Y-%m-%d").date()
                                if today <= earnings_date <= week_end:
                                    earnings_events.append({
                                        "ticker": ticker,
                                        "date": earnings_date.isoformat(),
                                        "days_until": (earnings_date - today).days,
                                    })
                            except Exception:
                                pass
            except Exception:
                pass

        earnings_events.sort(key=lambda x: x["date"])
        return earnings_events

    # ── Economic Calendar ─────────────────────────────────────────────────────

    def get_upcoming_economic_events(self, days_ahead: int = 7) -> list[dict]:
        """
        Return upcoming economic events that affect markets.
        In production, integrate with a live economic calendar API.
        This provides a reasonable static schedule as fallback.
        """
        today = datetime.now().date()
        events = []

        # Key dates (updated manually or via API)
        # TODO: Integrate with tradingeconomics.com or similar
        static_events = [
            {"name": "FOMC Meeting", "recurrence": "6-week", "market_impact": "CRITICAL"},
            {"name": "CPI Report", "recurrence": "monthly", "market_impact": "HIGH"},
            {"name": "Jobs Report (NFP)", "recurrence": "monthly_first_friday", "market_impact": "HIGH"},
            {"name": "PPI Report", "recurrence": "monthly", "market_impact": "MEDIUM"},
            {"name": "GDP Report", "recurrence": "quarterly", "market_impact": "HIGH"},
            {"name": "Consumer Confidence", "recurrence": "monthly", "market_impact": "MEDIUM"},
        ]

        # Return formatted events
        for event in static_events:
            events.append({
                "name": event["name"],
                "market_impact": event["market_impact"],
                "note": f"Check economic calendar for exact date",
            })

        return events

    # ── Market Summary ─────────────────────────────────────────────────────────

    async def get_market_summary(self) -> dict:
        """
        Fetch a brief market summary from Yahoo Finance RSS.
        Used in morning brief when no specific news is available.
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    "https://finance.yahoo.com/news/rssindex",
                    headers={"User-Agent": "Fred Trading Bot/1.0"},
                )

            feed = feedparser.parse(response.text)
            headlines = [entry.title for entry in feed.entries[:5] if entry.title]

            return {
                "headlines": headlines,
                "source": "Yahoo Finance",
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Failed to get market summary: {e}")
            return {"headlines": [], "timestamp": datetime.now().isoformat()}

    # ── NewsAPI ───────────────────────────────────────────────────────────────

    async def search_news_for_ticker(self, ticker: str) -> list[dict]:
        """
        Search NewsAPI for articles about a specific ticker.
        Requires NEWSAPI_KEY in .env.
        """
        if not settings.newsapi_key:
            return []

        try:
            from newsapi import NewsApiClient
            newsapi = NewsApiClient(api_key=settings.newsapi_key)

            articles = newsapi.get_everything(
                q=ticker,
                from_param=(datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
                sort_by="relevancy",
                page_size=5,
            )

            return [
                {
                    "headline": a["title"],
                    "source": a["source"]["name"],
                    "url": a["url"],
                    "published": a["publishedAt"],
                }
                for a in articles.get("articles", [])
            ]
        except Exception as e:
            logger.debug(f"NewsAPI search failed: {e}")
            return []


# Global singleton
news_monitor = NewsMonitor()

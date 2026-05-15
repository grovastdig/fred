"""
integrations/truth_social_monitor.py
======================================
Monitors Trump's Truth Social RSS feed directly.

Truth Social is the PRIMARY source — posts appear here first,
sometimes 5-10 minutes before they propagate to X.
That gap is where the alpha is.

No API key. No scraper complexity. Just RSS — same as any news feed.
Poll interval: 30 seconds market hours, 2 minutes pre/post market.
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Callable, Optional

from utils.time_utils import is_market_open, is_premarket, is_afterhours

logger = logging.getLogger("fred.truth_social")

TRUTH_SOCIAL_RSS = "https://truthsocial.com/@realDonaldTrump.rss"

# Words that make a post market-relevant
MARKET_KEYWORDS = [
    # Trade / tariffs
    "tariff", "tariffs", "trade", "china", "mexico", "canada",
    "import", "export", "deal", "sanction",
    # Sectors
    "oil", "energy", "crypto", "bitcoin", "steel", "pharma",
    "defense", "military", "bank", "banking",
    # Direct companies
    "tesla", "elon", "apple", "amazon", "google", "nvidia",
    "tiktok", "truth social", "djt",
    # Policy / macro
    "tax", "rate", "fed", "interest", "executive order",
    "investigation", "fine", "ban", "regulation",
    # Market language
    "stock", "market", "economy", "jobs", "gdp", "inflation",
    "trillion", "billion", "recession",
]

BEARISH_KEYWORDS = [
    "tariff", "sanction", "ban", "investigation", "fine",
    "illegal", "indict", "arrest", "fraud",
]


class TruthSocialMonitor:
    """
    Monitors Trump's Truth Social RSS feed.
    Faster and more reliable than X scraper as the primary alert source.
    """

    def __init__(self):
        self._seen_ids: set[str] = set()
        self._running = False
        self._callbacks: list[Callable] = []
        self._last_post_time: Optional[datetime] = None
        self._last_post_text: str = ""
        self._poll_count = 0
        self._last_successful_poll: float = 0

    def add_callback(self, fn: Callable) -> None:
        self._callbacks.append(fn)

    async def start(self) -> None:
        self._running = True
        logger.info("Truth Social monitor started")
        # Pre-load seen IDs so we don't blast old posts on startup
        await self._preload_seen()
        asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._running = False
        logger.info("Truth Social monitor stopped")

    async def _preload_seen(self) -> None:
        """Mark current posts as seen on startup — don't alert on old content."""
        try:
            import feedparser
            loop = asyncio.get_event_loop()
            feed = await loop.run_in_executor(None, feedparser.parse, TRUTH_SOCIAL_RSS)
            for entry in feed.entries:
                self._seen_ids.add(self._get_id(entry))
            logger.info(f"Truth Social pre-loaded {len(self._seen_ids)} existing posts")
        except Exception as e:
            logger.warning(f"Truth Social pre-load failed: {e}")

    async def _poll_loop(self) -> None:
        health_counter = 0
        while self._running:
            try:
                await self._check_feed()
                self._poll_count += 1
                health_counter += 1
                import time
                self._last_successful_poll = time.time()

                # Health check every 120 polls (~1 hour at 30s interval)
                if health_counter >= 120:
                    await self._health_check()
                    health_counter = 0

            except Exception as e:
                logger.error(f"Truth Social poll error: {e}")

            # Poll faster during market hours
            if is_market_open():
                interval = 30
            elif is_premarket() or is_afterhours():
                interval = 60
            else:
                interval = 120
            await asyncio.sleep(interval)

    async def _check_feed(self) -> None:
        """Fetch and process the RSS feed."""
        try:
            import feedparser
        except ImportError:
            logger.warning("feedparser not installed — pip install feedparser")
            return

        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, TRUTH_SOCIAL_RSS)

        for entry in feed.entries:
            post_id = self._get_id(entry)
            if post_id in self._seen_ids:
                continue

            self._seen_ids.add(post_id)
            # Keep seen set manageable
            if len(self._seen_ids) > 2000:
                self._seen_ids = set(list(self._seen_ids)[-1000:])

            text = self._get_text(entry)
            published = entry.get("published", "")

            if not text or len(text) < 5:
                continue

            logger.info(f"NEW Truth Social post: {text[:80]}...")
            self._last_post_time = datetime.now()
            self._last_post_text = text

            relevance = self._analyze_relevance(text)

            for callback in self._callbacks:
                try:
                    await callback(
                        source="truth_social",
                        account="realDonaldTrump",
                        text=text,
                        published=published,
                        relevance=relevance,
                    )
                except Exception as e:
                    logger.error(f"Truth Social callback error: {e}")

    def _analyze_relevance(self, text: str) -> dict:
        """Quick keyword relevance check — no API call needed."""
        text_lower = text.lower()
        market_hits = [kw for kw in MARKET_KEYWORDS if kw in text_lower]
        bearish_hits = [kw for kw in BEARISH_KEYWORDS if kw in text_lower]
        score = min(len(market_hits) * 15, 100)
        return {
            "score": score,
            "is_market_relevant": score > 0,
            "market_keywords": market_hits,
            "bearish_signals": bearish_hits,
            "likely_bullish": len(bearish_hits) == 0 and score > 0,
            "likely_bearish": len(bearish_hits) > 0,
        }

    def _get_id(self, entry) -> str:
        if hasattr(entry, "id") and entry.id:
            return str(entry.id)
        text = entry.get("link", "") + entry.get("title", "")
        return hashlib.md5(text.encode()).hexdigest()

    def _get_text(self, entry) -> str:
        text = entry.get("summary", "") or entry.get("title", "")
        return re.sub(r"<[^>]+>", "", text).strip()

    async def _health_check(self) -> None:
        """Alert if feed appears broken during market hours."""
        if not is_market_open():
            return

        import time
        if not self._last_post_time:
            return

        hours_silent = (datetime.now() - self._last_post_time).seconds / 3600
        if hours_silent > 8:
            try:
                from integrations.telegram_client import telegram_client
                telegram_client.send(
                    f"⚠️ TRUTH SOCIAL: No posts seen in {hours_silent:.0f}h.\n"
                    f"Feed may be down. Check manually.",
                    alert_key="truth_social_health"
                )
            except Exception as e:
                logger.error(f"Health check alert failed: {e}")

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "polls_completed": self._poll_count,
            "last_post_seen": (
                self._last_post_time.isoformat()
                if self._last_post_time else None
            ),
            "last_post_preview": self._last_post_text[:80] if self._last_post_text else None,
            "unique_posts_seen": len(self._seen_ids),
            "mode": "rss_direct",
        }


# Global singleton
truth_social_monitor = TruthSocialMonitor()

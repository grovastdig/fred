"""
integrations/twitter_monitor.py
================================
Reads Fred's burner Twitter account's HOME TIMELINE.

The simplest possible approach:
1. Create a burner Twitter account
2. Follow ONLY the accounts you want Fred to watch
   (Trump, Elon, Fed speakers, options flow accounts, etc.)
3. Fred reads that timeline on a 60-second loop
4. Every new post gets analyzed for market impact

No complex per-account polling. Just read the timeline
of a curated follow list — exactly like checking your phone,
but every 60 seconds, automatically.

Two modes:
- API mode: Official Twitter API ($100/mo Basic tier) — real-time
- Scraper mode: Nitter RSS proxies — free, ~2-5 min delay
"""

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

import requests

from config.settings import settings
from config.trading_rules import SOCIAL_MONITOR_CONFIG

logger = logging.getLogger("fred.twitter")

# Accounts whose posts ALWAYS get analyzed regardless of content
HIGH_PRIORITY_ACCOUNTS = {
    "realdonaldtrump", "realDonaldTrump",
    "elonmusk",
    "jpowell_fed", "JPowell_Fed",
    "federalreserve",
}

# Nitter instances for scraper mode (public mirrors of Twitter)
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
]


class TwitterMonitor:
    """
    Monitors Fred's curated follow list via home timeline polling.
    Posts get sent to registered callbacks for market impact analysis.
    """

    def __init__(self):
        self._callbacks: list[Callable] = []
        self._seen_ids: set[str] = set()
        self._running = False
        self._api_client = None
        self._use_api = bool(
            settings.twitter_bearer_token
            and not settings.twitter_use_scraper
        )
        self._poll_interval = SOCIAL_MONITOR_CONFIG.get("poll_interval_seconds", 60)
        self._accounts = [
            a["username"] for a in SOCIAL_MONITOR_CONFIG.get("accounts", [])
        ]

        if self._use_api:
            self._init_api_client()
            logger.info(f"Twitter monitor — API mode | {len(self._accounts)} accounts")
        else:
            logger.info(
                f"Twitter monitor — scraper mode (free) | "
                f"{len(self._accounts)} accounts | "
                f"~2-5 min delay"
            )

    def _init_api_client(self):
        """Initialize Tweepy client for API mode."""
        try:
            import tweepy
            self._api_client = tweepy.Client(
                bearer_token=settings.twitter_bearer_token,
                consumer_key=settings.twitter_api_key,
                consumer_secret=settings.twitter_api_secret,
                access_token=settings.twitter_access_token,
                access_token_secret=settings.twitter_access_secret,
                wait_on_rate_limit=True,
            )
            logger.info("Twitter API client connected")
        except Exception as e:
            logger.warning(f"Twitter API init failed, falling back to scraper: {e}")
            self._use_api = False

    def add_callback(self, callback: Callable) -> None:
        """Register a function to call when a relevant post is found."""
        self._callbacks.append(callback)

    async def start_monitoring(self) -> None:
        """Start the monitoring loop. Runs until stop() is called."""
        self._running = True
        self._last_successful_poll: dict[str, float] = {}
        logger.info(
            f"Twitter monitoring started — "
            f"polling every {self._poll_interval}s"
        )
        health_check_counter = 0
        while self._running:
            try:
                await self._poll_all_accounts()
                health_check_counter += 1
                # Run health check every 60 polls (~1 hour at 60s interval)
                if health_check_counter >= 60:
                    await self._health_check()
                    health_check_counter = 0
            except Exception as e:
                logger.error(f"Twitter poll error: {e}")
            await asyncio.sleep(self._poll_interval)

    async def _health_check(self) -> None:
        """
        Fix #7: Detect silent feed failures.
        Trump posts multiple times per day — 4+ hours of silence means the
        scraper is broken. Sends a warning text so you know to check manually.
        """
        from utils.time_utils import is_market_open
        if not is_market_open():
            return  # Only check during market hours

        import time
        now = time.time()
        high_priority = {"realDonaldTrump", "realdonaldtrump", "elonmusk", "JPowell_Fed"}

        for account in self._accounts:
            if account.lower() not in {a.lower() for a in high_priority}:
                continue

            last_poll = self._last_successful_poll.get(account.lower(), 0)
            hours_silent = (now - last_poll) / 3600 if last_poll else 0

            if last_poll > 0 and hours_silent > 4:
                logger.warning(f"Health check: @{account} silent for {hours_silent:.1f}h")
                try:
                    from integrations.telegram_client import telegram_client
                    telegram_client.send(
                        f"⚠️ SOCIAL MONITOR WARNING\n"
                        f"@{account} — no posts seen in {hours_silent:.0f}+ hours.\n"
                        f"Feed may be broken. Check manually.",
                        alert_key=f"health_{account}"
                    )
                except Exception as e:
                    logger.error(f"Health check alert failed: {e}")

    def stop(self) -> None:
        self._running = False
        logger.info("Twitter monitoring stopped")

    # ── Polling ───────────────────────────────────────────────────────────────

    async def _poll_all_accounts(self) -> None:
        """Poll all watched accounts for new posts."""
        for username in self._accounts:
            try:
                posts = await self._fetch_recent_posts(username)
                for post in posts:
                    await self._process_post(username, post)
            except Exception as e:
                logger.debug(f"Poll failed for @{username}: {e}")
            # Small delay between accounts to be respectful
            await asyncio.sleep(1)

    async def _fetch_recent_posts(self, username: str) -> list[dict]:
        """Fetch recent posts. Uses API if available, scraper as fallback."""
        if self._use_api and self._api_client:
            return await self._fetch_via_api(username)
        return await self._fetch_via_scraper(username)

    async def _fetch_via_api(self, username: str) -> list[dict]:
        """Fetch via official Twitter API v2."""
        try:
            import tweepy
            # Look up user ID first (cache this in production)
            user = self._api_client.get_user(username=username)
            if not user.data:
                return []
            user_id = user.data.id

            # Get recent tweets
            response = self._api_client.get_users_tweets(
                id=user_id,
                max_results=5,
                tweet_fields=["created_at", "text", "id"],
                exclude=["retweets"],  # Skip retweets — focus on original posts
            )
            if not response.data:
                return []

            return [
                {
                    "id": str(tweet.id),
                    "text": tweet.text,
                    "created_at": str(tweet.created_at),
                    "username": username,
                    "source": "api",
                }
                for tweet in response.data
            ]
        except Exception as e:
            logger.debug(f"API fetch failed for @{username}: {e}")
            return await self._fetch_via_scraper(username)

    async def _fetch_via_scraper(self, username: str) -> list[dict]:
        """
        Fetch via Nitter RSS (free, no API key).
        ~2-5 minute delay vs real-time API.
        Still catches 95% of market-moving posts with enough time to act.
        """
        for instance in NITTER_INSTANCES:
            try:
                url = f"{instance}/{username}/rss"
                resp = requests.get(url, timeout=8, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; FredBot/1.0)"
                })
                if resp.status_code == 200:
                    return self._parse_rss_feed(resp.text, username)
            except Exception as e:
                logger.debug(f"Nitter {instance} failed for @{username}: {e}")
                continue
        return []

    def _parse_rss_feed(self, rss_text: str, username: str) -> list[dict]:
        """Parse Nitter RSS feed into post dicts."""
        try:
            import feedparser
            feed = feedparser.parse(rss_text)
            posts = []
            cutoff = datetime.utcnow() - timedelta(hours=4)  # Only last 4 hours

            for entry in feed.entries[:10]:
                # Parse date
                try:
                    import email.utils
                    pub_date = datetime(*email.utils.parsedate(entry.published)[:6])
                    if pub_date < cutoff:
                        continue
                except Exception:
                    pass

                # Clean up the text (Nitter adds some HTML)
                import re
                text = re.sub(r'<[^>]+>', '', entry.get("summary", "")).strip()
                if not text:
                    text = entry.get("title", "")

                post_id = hashlib.md5(
                    f"{username}{entry.get('link', '')}{text[:50]}".encode()
                ).hexdigest()

                posts.append({
                    "id": post_id,
                    "text": text,
                    "created_at": entry.get("published", ""),
                    "username": username,
                    "source": "scraper",
                    "link": entry.get("link", ""),
                })

            return posts
        except Exception as e:
            logger.debug(f"RSS parse error for @{username}: {e}")
            return []

    # ── Processing ────────────────────────────────────────────────────────────

    async def _process_post(self, username: str, post: dict) -> None:
        """Process a single post — dedup, filter, callback."""
        post_id = post.get("id", "")
        if not post_id or post_id in self._seen_ids:
            return

        self._seen_ids.add(post_id)

        # Trim seen set to prevent memory growth
        if len(self._seen_ids) > 5000:
            self._seen_ids = set(list(self._seen_ids)[-2000:])

        text = post.get("text", "")
        if not text or len(text) < 10:
            return

        # Check if market-relevant (skip trivial posts)
        if not self._is_market_relevant(username, text):
            logger.debug(f"@{username} post filtered (not market relevant): {text[:60]}")
            return

        logger.info(f"📱 New post from @{username}: {text[:80]}...")
        import time
        self._last_successful_poll[username.lower()] = time.time()

        # Fire all callbacks
        for callback in self._callbacks:
            try:
                await callback(username=username, text=text, post=post)
            except Exception as e:
                logger.error(f"Twitter callback error: {e}")

    def _is_market_relevant(self, username: str, text: str) -> bool:
        """
        Quick filter — is this post potentially market-moving?
        High-priority accounts (Trump, Fed) always pass.
        Others need at least one market keyword.
        """
        username_lower = username.lower()

        # High-priority accounts always pass — every word matters
        if username_lower in {a.lower() for a in HIGH_PRIORITY_ACCOUNTS}:
            return True

        # For other accounts, check for market keywords
        text_lower = text.lower()
        market_keywords = [
            "buy", "sell", "bullish", "bearish", "trade", "position",
            "stock", "market", "fed", "rate", "inflation", "earnings",
            "tariff", "sanction", "deal", "acquisition", "merger",
            "sec", "doj", "regulation", "ban", "announce", "report",
            "$", "%", "billion", "million", "quarter", "revenue",
        ]
        return any(kw in text_lower for kw in market_keywords)

    def get_status(self) -> dict:
        """Current monitoring status."""
        return {
            "running": self._running,
            "mode": "api" if self._use_api else "scraper",
            "accounts_watched": len(self._accounts),
            "posts_seen": len(self._seen_ids),
            "poll_interval_seconds": self._poll_interval,
        }


# Global singleton
twitter_monitor = TwitterMonitor()

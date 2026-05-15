"""
integrations/article_reader.py
================================
Fetches and cleans full article content from URLs.

Headlines are useless. Fred reads the actual article.
A Reuters headline says "Fed signals caution" — the article
says exactly which words Powell used and what the market
should expect. That context is everything.

This module fetches the full text of any article URL
and returns clean, readable content for Claude to analyze.
"""

import re
import logging
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError
from html.parser import HTMLParser

logger = logging.getLogger("fred.article_reader")


class ArticleTextExtractor(HTMLParser):
    """Simple HTML parser that strips tags and extracts readable text."""

    def __init__(self):
        super().__init__()
        self.text_parts = []
        self._skip_tags = {"script", "style", "nav", "header", "footer",
                           "aside", "form", "button", "input", "meta",
                           "noscript", "iframe", "svg", "figure"}
        self._current_tag = ""
        self._skip = False
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        self._current_tag = tag
        if tag in self._skip_tags:
            self._skip = True
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._skip_tags and self._skip:
            self._skip_depth -= 1
            if self._skip_depth == 0:
                self._skip = False

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text and len(text) > 20:
                self.text_parts.append(text)

    def get_text(self) -> str:
        return " ".join(self.text_parts)


class ArticleReader:
    """
    Fetches full article content from news URLs.
    Used to give Fred real context, not just headlines.
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    MAX_CONTENT_LENGTH = 8000   # Characters — enough for Claude, not too much
    MIN_CONTENT_LENGTH = 200    # Below this, the fetch probably failed

    def fetch_article(self, url: str) -> Optional[dict]:
        """
        Fetch and extract the full text of an article.

        Returns:
            dict with 'url', 'text', 'word_count', 'success'
            or None if fetch failed.
        """
        if not url or not url.startswith("http"):
            return None

        try:
            req = Request(url, headers=self.HEADERS)
            with urlopen(req, timeout=10) as response:
                charset = "utf-8"
                content_type = response.headers.get("Content-Type", "")
                if "charset=" in content_type:
                    charset = content_type.split("charset=")[-1].strip()

                html = response.read().decode(charset, errors="replace")

            text = self._extract_text(html)

            if len(text) < self.MIN_CONTENT_LENGTH:
                logger.debug(f"Article too short ({len(text)} chars): {url}")
                return {
                    "url": url,
                    "text": text,
                    "word_count": len(text.split()),
                    "success": False,
                    "reason": "content_too_short",
                }

            # Trim to max length
            trimmed = text[: self.MAX_CONTENT_LENGTH]
            if len(text) > self.MAX_CONTENT_LENGTH:
                trimmed += "... [article continues]"

            return {
                "url": url,
                "text": trimmed,
                "word_count": len(trimmed.split()),
                "success": True,
            }

        except URLError as e:
            logger.debug(f"Could not fetch {url}: {e}")
            return None
        except Exception as e:
            logger.debug(f"Article read error for {url}: {e}")
            return None

    def fetch_multiple(self, urls: list[str]) -> list[dict]:
        """Fetch multiple articles. Returns only successful ones."""
        results = []
        for url in urls[:5]:  # Cap at 5 to avoid rate limits
            result = self.fetch_article(url)
            if result and result.get("success"):
                results.append(result)
        return results

    def _extract_text(self, html: str) -> str:
        """Extract clean text from HTML."""
        # Try to find the main article content first
        # Most news sites wrap articles in <article> tags
        article_match = re.search(
            r"<article[^>]*>(.*?)</article>",
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if article_match:
            html = article_match.group(1)
        else:
            # Try common article containers
            for selector in [
                r'<div[^>]*class="[^"]*article[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*class="[^"]*story[^"]*"[^>]*>(.*?)</div>',
                r'<main[^>]*>(.*?)</main>',
            ]:
                match = re.search(selector, html, re.DOTALL | re.IGNORECASE)
                if match:
                    html = match.group(1)
                    break

        parser = ArticleTextExtractor()
        parser.feed(html)
        raw = parser.get_text()

        # Clean up whitespace
        cleaned = re.sub(r"\s{3,}", "  ", raw)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        return cleaned.strip()

    def summarize_for_prompt(self, article: dict, ticker: str = "") -> str:
        """
        Format a fetched article for injection into a Claude prompt.
        Keeps it tight — Claude doesn't need the full 8k chars for a trade decision.
        """
        if not article or not article.get("success"):
            return ""

        text = article["text"]
        url = article["url"]

        # Trim to ~2000 chars for prompt efficiency
        if len(text) > 2000:
            text = text[:2000] + "..."

        prefix = f"[Article: {url}]\n\n" if url else ""
        return f"{prefix}{text}"


# Global singleton
article_reader = ArticleReader()

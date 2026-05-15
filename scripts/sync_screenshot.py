"""
scripts/sync_screenshot.py
===========================
Robinhood screenshot → Alpaca paper sync.

Usage:
    python scripts/sync_screenshot.py path/to/screenshot.png

Or via SMS: send a screenshot as a photo message
(handled by server/sms_handler.py which calls this logic)

How it works:
1. You send a Robinhood portfolio screenshot
2. Fred sends it to Claude Vision
3. Claude reads: ticker, shares, avg cost for each position
4. Fred diffs against current Alpaca paper positions
5. Fred syncs Alpaca to match
6. Fred updates Notion positions database
7. Fred texts you confirmation

This is how you "connect" Robinhood to Fred without API access.
Do this every Sunday evening for the weekly sync.
"""

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import anthropic
import logging as _logging; logger = _logging.getLogger(__name__)


class RobinhoodScreenshotParser:
    """
    Uses Claude Vision to extract position data from Robinhood screenshots.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def parse_screenshot(self, image_path: str) -> list[dict]:
        """
        Parse a Robinhood screenshot and extract position data.

        Returns list of:
        {
            "ticker": "NVDA",
            "shares": 20,
            "avg_cost": 127.50,
            "current_price": 131.20,
            "market_value": 2624.00,
        }
        """
        image_path = Path(image_path)

        if not image_path.exists():
            raise FileNotFoundError(f"Screenshot not found: {image_path}")

        # Read and encode image
        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        # Determine media type
        suffix = image_path.suffix.lower()
        media_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }
        media_type = media_types.get(suffix, "image/png")

        logger.info(f"Parsing screenshot: {image_path.name}")

        prompt = """This is a Robinhood portfolio screenshot. 
Extract ALL stock positions visible.

For each position, provide:
- ticker symbol (the stock symbol like NVDA, TSLA etc)
- shares (number of shares owned)
- avg_cost (average cost per share)
- current_price (current market price if visible)
- market_value (total market value if visible)

Return ONLY a JSON array with this exact format, nothing else:
[
    {
        "ticker": "NVDA",
        "shares": 20.0,
        "avg_cost": 127.50,
        "current_price": 131.20,
        "market_value": 2624.00
    }
]

If a field is not clearly visible, use null.
Include every position you can see. 
Do not include ETFs or cash."""

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        )

        raw = response.content[0].text.strip()
        logger.debug(f"Claude vision response: {raw[:200]}")

        # Parse JSON
        import re
        json_match = re.search(r"\[[\s\S]*\]", raw)
        if json_match:
            positions = json.loads(json_match.group())
        else:
            positions = json.loads(raw)

        logger.info(f"Found {len(positions)} positions in screenshot")
        return positions

    async def sync_to_alpaca_and_notion(self, positions: list[dict]) -> dict:
        """
        Sync parsed positions to Alpaca paper account and Notion.
        """
        from integrations.alpaca_client import alpaca_client
        from integrations.notion_client import notion_client
        from core.portfolio import portfolio_manager

        results = {
            "positions_found": len(positions),
            "alpaca_synced": [],
            "alpaca_failed": [],
            "notion_updated": [],
        }

        # Sync to Alpaca
        alpaca_result = await alpaca_client.sync_from_robinhood_data(positions)
        results["alpaca_synced"] = alpaca_result.get("synced", [])
        results["alpaca_failed"] = alpaca_result.get("failed", [])

        # Sync to Notion
        for pos in positions:
            ticker = pos.get("ticker", "").upper()
            shares = pos.get("shares") or 0
            avg_cost = pos.get("avg_cost") or 0

            if not ticker or not shares:
                continue

            # Check if position already exists in Notion
            existing = portfolio_manager.get_position(ticker)

            if existing:
                # Update current price
                await notion_client.update_position(
                    existing.id,
                    {"current_price": pos.get("current_price") or avg_cost},
                )
            else:
                # Add new position (no stop/target — user needs to set these)
                await notion_client.add_position({
                    "ticker": ticker,
                    "shares": shares,
                    "entry_price": avg_cost,
                    "stop_loss": 0,
                    "target": 0,
                    "thesis": "Synced from Robinhood screenshot",
                    "catalyst_type": "technical_only",
                    "status": "Open",
                })
                results["notion_updated"].append(ticker)

        return results


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/sync_screenshot.py path/to/screenshot.png")
        print()
        print("This syncs your Robinhood positions to Fred's Notion database")
        print("and mirrors them to the Alpaca paper trading account.")
        sys.exit(1)

    image_path = sys.argv[1]
    parser = RobinhoodScreenshotParser()

    print(f"\n🔍 Parsing screenshot: {image_path}")

    try:
        positions = parser.parse_screenshot(image_path)

        print(f"\n📊 Found {len(positions)} positions:")
        for pos in positions:
            ticker = pos.get("ticker", "?")
            shares = pos.get("shares", 0)
            avg_cost = pos.get("avg_cost", 0)
            current = pos.get("current_price", avg_cost) or avg_cost
            pnl_pct = ((current - avg_cost) / avg_cost * 100) if avg_cost else 0
            print(f"  {ticker}: {shares:.0f}sh @ ${avg_cost:.2f} | ${current:.2f} ({pnl_pct:+.1f}%)")

        print("\n⏳ Syncing to Alpaca and Notion...")
        results = await parser.sync_to_alpaca_and_notion(positions)

        print(f"\n✅ Sync complete:")
        print(f"  Alpaca synced: {results['alpaca_synced']}")
        print(f"  Alpaca failed: {results['alpaca_failed']}")
        print(f"  Notion updated: {results['notion_updated']}")

        print("\n⚠️  IMPORTANT: Stop losses not set on new positions!")
        print("Text Fred 'stop TICKER price' for each position to set stops.")

    except FileNotFoundError as e:
        print(f"❌ File not found: {e}")
    except json.JSONDecodeError as e:
        print(f"❌ Could not parse Claude's response as JSON: {e}")
    except Exception as e:
        print(f"❌ Sync failed: {e}")
        logger.exception(e)


if __name__ == "__main__":
    asyncio.run(main())

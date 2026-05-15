"""
scripts/setup_notion.py
========================
First-run Notion database setup.

Run this ONCE after creating your Notion integration.
Creates all 6 databases Fred needs and writes the
database IDs back to your .env file.

Usage:
    python scripts/setup_notion.py

Requirements:
- NOTION_API_KEY set in .env
- Notion integration created at notion.so/my-integrations
- Integration shared with the page where databases will be created
"""

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv, set_key
load_dotenv()

from notion_client import AsyncClient
import logging as _logging; logger = _logging.getLogger(__name__)

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
if not NOTION_API_KEY:
    print("❌ NOTION_API_KEY not found in .env")
    sys.exit(1)

client = AsyncClient(auth=NOTION_API_KEY)


async def create_positions_db(parent_page_id: str) -> str:
    """Create the Open Positions database."""
    response = await client.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        title=[{"type": "text", "text": {"content": "📈 Open Positions"}}],
        properties={
            "Ticker": {"title": {}},
            "Status": {
                "select": {
                    "options": [
                        {"name": "Open", "color": "green"},
                        {"name": "Closed", "color": "red"},
                        {"name": "Partial", "color": "yellow"},
                    ]
                }
            },
            "Shares": {"number": {"format": "number"}},
            "Entry Price": {"number": {"format": "dollar"}},
            "Current Price": {"number": {"format": "dollar"}},
            "Stop Loss": {"number": {"format": "dollar"}},
            "Target": {"number": {"format": "dollar"}},
            "Exit Price": {"number": {"format": "dollar"}},
            "P&L ($)": {"number": {"format": "dollar"}},
            "P&L (%)": {"number": {"format": "percent"}},
            "Confidence Score": {"number": {"format": "number"}},
            "Thesis": {"rich_text": {}},
            "Catalyst Type": {
                "select": {
                    "options": [
                        {"name": "earnings_beat", "color": "green"},
                        {"name": "political_trump", "color": "red"},
                        {"name": "political_social", "color": "orange"},
                        {"name": "breakout_52w_high", "color": "blue"},
                        {"name": "sector_rotation", "color": "purple"},
                        {"name": "analyst_upgrade", "color": "yellow"},
                        {"name": "technical_only", "color": "gray"},
                    ]
                }
            },
            "Sector": {"rich_text": {}},
            "Entry Date": {"date": {}},
            "Exit Date": {"date": {}},
            "Exit Reason": {"rich_text": {}},
            "Outcome": {
                "select": {
                    "options": [
                        {"name": "WIN", "color": "green"},
                        {"name": "LOSS", "color": "red"},
                        {"name": "BREAKEVEN", "color": "yellow"},
                    ]
                }
            },
        },
    )
    return response["id"]


async def create_watchlist_db(parent_page_id: str) -> str:
    """Create the Watchlist database."""
    response = await client.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        title=[{"type": "text", "text": {"content": "👀 Watchlist"}}],
        properties={
            "Ticker": {"title": {}},
            "Active": {"checkbox": {}},
            "Thesis": {"rich_text": {}},
            "Entry Zone": {"rich_text": {}},
            "Stop Loss": {"number": {"format": "dollar"}},
            "Target": {"number": {"format": "dollar"}},
            "Catalyst Type": {
                "select": {
                    "options": [
                        {"name": "earnings_beat", "color": "green"},
                        {"name": "political_trump", "color": "red"},
                        {"name": "political_social", "color": "orange"},
                        {"name": "breakout_52w_high", "color": "blue"},
                        {"name": "sector_rotation", "color": "purple"},
                        {"name": "technical_only", "color": "gray"},
                    ]
                }
            },
            "Added Date": {"date": {}},
            "Notes": {"rich_text": {}},
        },
    )
    return response["id"]


async def create_journal_db(parent_page_id: str) -> str:
    """Create the Trade Journal database."""
    response = await client.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        title=[{"type": "text", "text": {"content": "📓 Trade Journal"}}],
        properties={
            "Trade": {"title": {}},
            "Ticker": {"rich_text": {}},
            "Entry Price": {"number": {"format": "dollar"}},
            "Exit Price": {"number": {"format": "dollar"}},
            "Shares": {"number": {"format": "number"}},
            "P&L ($)": {"number": {"format": "dollar"}},
            "P&L (%)": {"number": {"format": "percent"}},
            "Outcome": {
                "select": {
                    "options": [
                        {"name": "WIN", "color": "green"},
                        {"name": "LOSS", "color": "red"},
                        {"name": "BREAKEVEN", "color": "yellow"},
                    ]
                }
            },
            "Exit Reason": {"rich_text": {}},
            "Thesis": {"rich_text": {}},
            "Lesson": {"rich_text": {}},
            "Confidence at Entry": {"number": {"format": "number"}},
            "Entry Date": {"date": {}},
            "Exit Date": {"date": {}},
        },
    )
    return response["id"]


async def create_rules_db(parent_page_id: str) -> str:
    """Create the Trading Rules database."""
    response = await client.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        title=[{"type": "text", "text": {"content": "📋 Trading Rules"}}],
        properties={
            "Rule": {"title": {}},
            "Category": {
                "select": {
                    "options": [
                        {"name": "Entry", "color": "green"},
                        {"name": "Exit", "color": "red"},
                        {"name": "Safety", "color": "orange"},
                        {"name": "Sizing", "color": "blue"},
                    ]
                }
            },
            "Description": {"rich_text": {}},
            "Active": {"checkbox": {}},
        },
    )
    return response["id"]


async def create_alerts_log_db(parent_page_id: str) -> str:
    """Create the Alerts Log database."""
    response = await client.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        title=[{"type": "text", "text": {"content": "🔔 Alert Log"}}],
        properties={
            "Alert": {"title": {}},
            "Type": {
                "select": {
                    "options": [
                        {"name": "STOP_LOSS", "color": "red"},
                        {"name": "STOP_APPROACHING", "color": "orange"},
                        {"name": "TARGET_HIT", "color": "green"},
                        {"name": "ENTRY_SIGNAL", "color": "blue"},
                        {"name": "SOCIAL", "color": "purple"},
                        {"name": "NEWS", "color": "yellow"},
                        {"name": "TECHNICAL_RSI_OVERBOUGHT", "color": "orange"},
                        {"name": "TECHNICAL_MACD_BEARISH", "color": "red"},
                    ]
                }
            },
            "Ticker": {"rich_text": {}},
            "Message": {"rich_text": {}},
            "Urgency": {
                "select": {
                    "options": [
                        {"name": "CRITICAL", "color": "red"},
                        {"name": "HIGH", "color": "orange"},
                        {"name": "MEDIUM", "color": "yellow"},
                        {"name": "LOW", "color": "gray"},
                    ]
                }
            },
            "Action Taken": {"rich_text": {}},
            "Timestamp": {"date": {}},
        },
    )
    return response["id"]


async def create_social_triggers_db(parent_page_id: str) -> str:
    """Create the Social Triggers database."""
    response = await client.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        title=[{"type": "text", "text": {"content": "🐦 Social Triggers"}}],
        properties={
            "Post": {"title": {}},
            "Account": {"rich_text": {}},
            "Post Text": {"rich_text": {}},
            "Impact Level": {
                "select": {
                    "options": [
                        {"name": "CRITICAL", "color": "red"},
                        {"name": "HIGH", "color": "orange"},
                        {"name": "MEDIUM", "color": "yellow"},
                        {"name": "LOW", "color": "gray"},
                    ]
                }
            },
            "Affected Tickers": {"rich_text": {}},
            "Fred's Analysis": {"rich_text": {}},
            "Timestamp": {"date": {}},
        },
    )
    return response["id"]


async def main():
    print("🤖 FRED — Notion Database Setup")
    print("=" * 40)

    # Get parent page ID
    print("\nOpen Notion and create a blank page called 'Fred HQ'")
    print("Then get the page ID from the URL:")
    print("  notion.so/your-workspace/Fred-HQ-[PAGE_ID_HERE]")
    print()
    parent_page_id = input("Enter your Notion page ID: ").strip()

    if not parent_page_id:
        print("❌ No page ID provided")
        return

    # Remove dashes if present
    parent_page_id = parent_page_id.replace("-", "")

    print("\nCreating databases...")

    try:
        print("  Creating Open Positions database...")
        positions_id = await create_positions_db(parent_page_id)
        print(f"  ✅ Open Positions: {positions_id}")

        print("  Creating Watchlist database...")
        watchlist_id = await create_watchlist_db(parent_page_id)
        print(f"  ✅ Watchlist: {watchlist_id}")

        print("  Creating Trade Journal database...")
        journal_id = await create_journal_db(parent_page_id)
        print(f"  ✅ Trade Journal: {journal_id}")

        print("  Creating Trading Rules database...")
        rules_id = await create_rules_db(parent_page_id)
        print(f"  ✅ Trading Rules: {rules_id}")

        print("  Creating Alert Log database...")
        alerts_id = await create_alerts_log_db(parent_page_id)
        print(f"  ✅ Alert Log: {alerts_id}")

        print("  Creating Social Triggers database...")
        social_id = await create_social_triggers_db(parent_page_id)
        print(f"  ✅ Social Triggers: {social_id}")

        # Write IDs to .env
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")

        if os.path.exists(env_file):
            set_key(env_file, "NOTION_POSITIONS_DB", positions_id)
            set_key(env_file, "NOTION_WATCHLIST_DB", watchlist_id)
            set_key(env_file, "NOTION_JOURNAL_DB", journal_id)
            set_key(env_file, "NOTION_RULES_DB", rules_id)
            set_key(env_file, "NOTION_ALERTS_LOG_DB", alerts_id)
            set_key(env_file, "NOTION_SOCIAL_TRIGGERS_DB", social_id)
            print("\n✅ Database IDs written to .env")
        else:
            print("\n⚠️ .env file not found. Add these to your .env manually:")
            print(f"NOTION_POSITIONS_DB={positions_id}")
            print(f"NOTION_WATCHLIST_DB={watchlist_id}")
            print(f"NOTION_JOURNAL_DB={journal_id}")
            print(f"NOTION_RULES_DB={rules_id}")
            print(f"NOTION_ALERTS_LOG_DB={alerts_id}")
            print(f"NOTION_SOCIAL_TRIGGERS_DB={social_id}")

        print("\n🎉 Notion setup complete!")
        print("Next step: python scripts/health_check.py")

    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        print("Check your NOTION_API_KEY and make sure the integration is shared with the page.")


if __name__ == "__main__":
    asyncio.run(main())

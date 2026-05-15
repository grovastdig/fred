"""
main.py
=======
Fred's entry point. This is the file you run.

Usage:
    python main.py              # Start Fred (production mode)
    python main.py --dev        # Development mode (auto-reload)
    python main.py --health     # Quick health check, then exit

Fred starts the FastAPI server which in turn boots:
  - Twilio SMS webhook listener
  - APScheduler cron jobs (morning brief, EOD, position checks)
  - Twitter/X social monitor
  - News/RSS monitor
  - Stop loss price watcher
  - Technical breakout scanner
"""

import sys
import os
import argparse
import uvicorn

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging as _logging; logger = _logging.getLogger(__name__)
from config.settings import settings


def run_health_check():
    """Quick check that all integrations are reachable. Exit 0 = good, 1 = fail."""
    print("🩺 Running Fred health check...\n")
    exit_code = 0

    # Anthropic
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        client.models.list()
        print("✅ Anthropic API — connected")
    except Exception as e:
        print(f"❌ Anthropic API — FAILED: {e}")
        exit_code = 1

    # Twilio
    try:
        from twilio.rest import Client
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.api.accounts(settings.twilio_account_sid).fetch()
        print("✅ Twilio — connected")
    except Exception as e:
        print(f"❌ Twilio — FAILED: {e}")
        exit_code = 1

    # Notion
    try:
        from notion_client import Client as NotionClient
        nc = NotionClient(auth=settings.notion_api_key)
        nc.users.me()
        print("✅ Notion — connected")
    except Exception as e:
        print(f"❌ Notion — FAILED: {e}")
        exit_code = 1

    # Alpaca
    try:
        from alpaca.trading.client import TradingClient
        tc = TradingClient(settings.alpaca_api_key, settings.alpaca_secret_key, paper=True)
        tc.get_account()
        print("✅ Alpaca (paper) — connected")
    except Exception as e:
        print(f"❌ Alpaca — FAILED: {e}")
        exit_code = 1

    # Market data (yfinance — no API key needed)
    try:
        import yfinance as yf
        spy = yf.Ticker("SPY")
        info = spy.fast_info
        price = getattr(info, "last_price", 0)
        print(f"✅ Market data (yfinance) — SPY ${price:.2f}")
    except Exception as e:
        print(f"❌ Market data — FAILED: {e}")
        exit_code = 1

    # Twitter (optional)
    if settings.has_twitter_api:
        try:
            import tweepy
            auth = tweepy.OAuth1UserHandler(
                settings.twitter_api_key,
                settings.twitter_api_secret,
                settings.twitter_access_token,
                settings.twitter_access_secret,
            )
            api = tweepy.API(auth)
            api.verify_credentials()
            print("✅ Twitter API — connected")
        except Exception as e:
            print(f"⚠️  Twitter API — optional, not connected: {e}")
    else:
        print("ℹ️  Twitter API — not configured (using scraper fallback)")

    print(f"\n{'✅ All systems go!' if exit_code == 0 else '❌ Some checks failed — see above'}")
    return exit_code


def main():
    parser = argparse.ArgumentParser(description="Fred — AI Swing Trading Assistant")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Development mode: auto-reload on code changes",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Run health check and exit",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.port,
        help=f"Port to run on (default: {settings.port})",
    )
    args = parser.parse_args()

    if args.health:
        sys.exit(run_health_check())

    # ── Configure logging ────────────────────────────────────────────────────
    os.makedirs("logs", exist_ok=True)
    import logging
    os.makedirs("logs", exist_ok=True)
    level = "DEBUG" if args.dev else "INFO"
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    logging.basicConfig(
        level=getattr(logging, level),
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f"logs/fred.log"),
        ]
    )
    logger = logging.getLogger("fred.main")

    # ── Startup banner ───────────────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("🤖 FRED — AI Swing Trading Assistant")
    logger.info(f"   Environment: {settings.environment}")
    logger.info(f"   Port:        {args.port}")
    logger.info(f"   Model:       {settings.anthropic_model}")
    logger.info(f"   Timezone:    {settings.timezone}")
    logger.info("=" * 50)

    # ── Run ──────────────────────────────────────────────────────────────────
    uvicorn.run(
        "server.app:app",
        host="0.0.0.0",
        port=args.port,
        reload=args.dev,
        log_level="debug" if args.dev else "info",
        # Production settings
        workers=1,  # Single worker — we use async, not multi-process
        loop="asyncio",
    )


if __name__ == "__main__":
    main()

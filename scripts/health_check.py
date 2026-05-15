"""
scripts/health_check.py
========================
Pre-deployment health check. Run this before deploying to Railway
to verify all API keys and connections work.

Usage:
    python scripts/health_check.py

A green check on every item = you're ready to deploy.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

# Colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def ok(label: str, detail: str = "") -> None:
    print(f"  {GREEN}✅ {label}{RESET}" + (f" — {detail}" if detail else ""))


def fail(label: str, detail: str = "") -> None:
    print(f"  {RED}❌ {label}{RESET}" + (f" — {detail}" if detail else ""))


def warn(label: str, detail: str = "") -> None:
    print(f"  {YELLOW}⚠️  {label}{RESET}" + (f" — {detail}" if detail else ""))


async def check_anthropic() -> bool:
    print(f"\n{BOLD}🧠 Anthropic (Fred's Brain){RESET}")
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key == "sk-ant-your-key-here":
        fail("API key not set")
        return False
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=20,
            messages=[{"role": "user", "content": "Say 'Fred online' in 3 words."}],
        )
        reply = msg.content[0].text
        ok("Connected", reply.strip())
        return True
    except Exception as e:
        fail("Connection failed", str(e)[:60])
        return False


async def check_notion() -> bool:
    print(f"\n{BOLD}📋 Notion{RESET}")
    api_key = os.getenv("NOTION_API_KEY", "")
    if not api_key or api_key.startswith("secret_your"):
        fail("API key not set")
        return False

    try:
        from notion_client import AsyncClient
        client = AsyncClient(auth=api_key)
        response = await client.users.me()
        ok("Connected", f"User: {response.get('name', 'unknown')}")

        # Check database IDs
        db_vars = [
            "NOTION_POSITIONS_DB",
            "NOTION_WATCHLIST_DB",
            "NOTION_JOURNAL_DB",
        ]
        all_set = True
        for var in db_vars:
            val = os.getenv(var, "")
            if val:
                ok(f"{var} set")
            else:
                warn(f"{var} not set — run setup_notion.py")
                all_set = False

        return True
    except Exception as e:
        fail("Connection failed", str(e)[:60])
        return False


async def check_twilio() -> bool:
    print(f"\n{BOLD}📱 Twilio (SMS){RESET}")
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    phone = os.getenv("TWILIO_PHONE_NUMBER", "")

    if not sid or sid.startswith("ACyour"):
        fail("Account SID not set")
        return False

    try:
        from twilio.rest import Client
        client = Client(sid, token)
        account = client.api.accounts(sid).fetch()
        ok("Connected", f"Account: {account.friendly_name}")
        ok("Phone number", phone)

        your_phone = os.getenv("YOUR_PHONE_NUMBER", "")
        if your_phone:
            ok("Your phone", your_phone)
        else:
            fail("YOUR_PHONE_NUMBER not set")
            return False

        return True
    except Exception as e:
        fail("Connection failed", str(e)[:60])
        return False


async def check_alpaca() -> bool:
    print(f"\n{BOLD}📊 Alpaca (Paper Trading){RESET}")
    api_key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")

    if not api_key or api_key == "your-alpaca-key":
        fail("API key not set")
        return False

    try:
        from alpaca.trading.client import TradingClient
        client = TradingClient(api_key=api_key, secret_key=secret, paper=True)
        account = client.get_account()
        ok("Connected (paper)", f"Portfolio: ${float(account.portfolio_value):.2f}")
        ok("Buying power", f"${float(account.buying_power):.2f}")
        return True
    except Exception as e:
        fail("Connection failed", str(e)[:60])
        return False


async def check_market_data() -> bool:
    print(f"\n{BOLD}📈 Market Data (yfinance){RESET}")
    try:
        import yfinance as yf
        spy = yf.Ticker("SPY")
        hist = spy.history(period="1d")
        if not hist.empty:
            price = float(hist["Close"].iloc[-1])
            ok("yfinance connected", f"SPY: ${price:.2f}")
        else:
            warn("No data returned (market may be closed)")

        polygon_key = os.getenv("POLYGON_API_KEY", "")
        if polygon_key:
            ok("Polygon.io key configured")
        else:
            warn("No Polygon.io key — using yfinance (15min delay)")

        return True
    except Exception as e:
        fail("Market data failed", str(e)[:60])
        return False


async def check_twitter() -> bool:
    print(f"\n{BOLD}🐦 Twitter/X Monitor{RESET}")
    use_scraper = os.getenv("TWITTER_USE_SCRAPER", "true").lower() == "true"
    bearer = os.getenv("TWITTER_BEARER_TOKEN", "")

    if bearer and not use_scraper:
        try:
            import tweepy
            client = tweepy.Client(bearer_token=bearer)
            user = client.get_user(username="realDonaldTrump")
            ok("Twitter API connected", f"@realDonaldTrump found")
        except Exception as e:
            fail("Twitter API failed", str(e)[:60])
            warn("Falling back to scraper mode")

    if use_scraper or not bearer:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://nitter.privacydev.net/realDonaldTrump/rss",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
            if r.status_code == 200:
                ok("Nitter scraper accessible", "Using free scraper mode")
            else:
                warn(f"Nitter returned {r.status_code}", "May need to try another instance")
        except Exception as e:
            warn("Nitter scraper check failed", "Will retry different instances at runtime")

    accounts = os.getenv("TWITTER_WATCH_ACCOUNTS", "")
    if accounts:
        ok("Watch accounts", accounts)

    return True


async def main():
    print(f"\n{BOLD}{'='*50}")
    print("🤖 FRED — Pre-Deployment Health Check")
    print(f"{'='*50}{RESET}")

    results = []
    results.append(await check_anthropic())
    results.append(await check_notion())
    results.append(await check_twilio())
    results.append(await check_alpaca())
    results.append(await check_market_data())
    results.append(await check_twitter())

    passed = sum(results)
    total = len(results)

    print(f"\n{BOLD}{'='*50}")
    print(f"Results: {passed}/{total} checks passed")
    print(f"{'='*50}{RESET}\n")

    if passed == total:
        print(f"{GREEN}{BOLD}✅ All systems go! Deploy Fred with: railway up{RESET}\n")
    elif passed >= 4:
        print(f"{YELLOW}{BOLD}⚠️  Most systems ready. Review failures above.{RESET}\n")
    else:
        print(f"{RED}{BOLD}❌ Multiple failures. Fix above before deploying.{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())

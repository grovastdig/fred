# 🤖 Fred — AI Swing Trading Assistant

Fred is a personal swing trading Jarvis built on Claude Sonnet 4.6. He watches the market 24/7, texts you alerts, scores every setup, enforces your rules, and mirrors your Robinhood positions to an Alpaca paper account for automated monitoring.

**Goal:** Beat the S&P 500 every single month via momentum-first swing trading.

---

## Architecture

```
You (iPhone SMS)
     ↕  Twilio
  FastAPI Server  (Railway)
     ├── SMS Handler     ← routes your texts to the right action
     ├── APScheduler     ← morning brief, EOD, position checks
     ├── Alert Engine    ← coordinates all alerts
     │     ├── Stop Loss Monitor   (every 5 min)
     │     ├── Technical Scanner   (every 15 min)
     │     ├── Social Alerts       (every 60 sec)
     │     └── News Monitor        (continuous)
     └── Fred's Brain (Claude)
           ├── Setup Analysis
           ├── Portfolio Context
           ├── Morning/EOD Briefs
           └── Natural Language SMS
     
  Data Layer
     ├── Market Data   (yfinance + Polygon.io)
     ├── Notion        (source of truth for positions)
     └── Alpaca Paper  (execution mirror + price monitoring)
```

---

## Stack

| Component        | Tool                    | Cost          |
|-----------------|-------------------------|---------------|
| Brain           | Claude Sonnet 4.6       | ~$5-15/mo     |
| SMS             | Twilio                  | ~$1/mo + usage|
| Deployment      | Railway                 | ~$5/mo        |
| Market Data     | yfinance (free)         | $0            |
| Market Data+    | Polygon.io (optional)   | Free tier ok  |
| Portfolio DB    | Notion                  | Free          |
| Paper Trading   | Alpaca                  | Free          |
| Twitter Monitor | Tweepy (API optional)   | Free          |

**Total: ~$11-21/mo**

---

## SMS Commands

```
status          → Full portfolio health check
brief           → On-demand morning brief
scan            → Fresh market scan (top setups)
watchlist       → Your current watchlist
NVDA            → Full analysis of any ticker
how am I doing  → P&L stats

buy NVDA 20 shares at 127 stop 122 target 138
sell NVDA       → Close position
stop NVDA 125   → Update stop loss
add NVDA [thesis] → Add to watchlist
remove NVDA     → Remove from watchlist
sync            → Re-sync from Notion
rules           → View trading rules
help            → Command list

[anything else] → Fred answers naturally
```

---

## Trading Rules (Shark Mode)

**Entry — ALL required:**
- Price above 20 EMA (trend confirmed)
- RSI between 40-65 (momentum building, not extended)
- MACD bullish crossover or expanding histogram
- Volume above 20-day average (no conviction = no trade)
- Catalyst present (news, earnings, political, sector rotation)
- Confidence score ≥ 50
- Minimum 2:1 risk/reward ratio

**Exit — ANY triggers:**
- Stop loss hit → EXIT IMMEDIATELY, no exceptions
- RSI > 75 → take profits or tighten stop
- MACD bearish crossover → momentum shifting
- Target price reached → lock profits or trail stop
- Thesis-breaking news → EXIT IMMEDIATELY
- Volume drying up → tighten stop

**Position Sizing by Confidence:**
| Score  | Grade       | Size        |
|--------|-------------|-------------|
| 90-100 | 🔥 Conviction | 25-30%    |
| 70-89  | ✅ Strong     | 15-20%    |
| 50-69  | 👀 Moderate   | 8-12%     |
| <50    | ❌ Skip       | 0%        |

---

## Setup (15 minutes)

### 1. Prerequisites

```bash
# macOS
brew install python@3.11 git
pip install -r requirements.txt

# Windows
# Install Python 3.11 from python.org
# Install Git from git-scm.com
pip install -r requirements.txt
```

### 2. Clone and configure

```bash
git clone <your-repo-url> fred
cd fred
cp .env.example .env
# Open .env and fill in your API keys (see below)
```

### 3. Get API keys

**Required:**
- [Anthropic](https://console.anthropic.com) → API key
- [Twilio](https://console.twilio.com) → Account SID, Auth Token, phone number
- [Notion](https://www.notion.so/my-integrations) → Integration token
- [Alpaca](https://app.alpaca.markets) → Paper trading keys

**Optional but recommended:**
- [Polygon.io](https://polygon.io) → Free tier is fine (better data)
- [Twitter API](https://developer.twitter.com) → Or use scraper mode (no key needed)
- [NewsAPI](https://newsapi.org) → Free tier

### 4. Create Notion databases

```bash
# This creates all 6 databases and writes IDs to .env
python scripts/setup_notion.py
```

### 5. Health check

```bash
python main.py --health
```

All green? You're ready.

### 6. Start Fred

```bash
# Development (auto-reload)
python main.py --dev

# Production
python main.py
```

### 7. Configure Twilio webhook

In Twilio Console → Phone Numbers → Your number → SMS webhook:
```
https://your-railway-url.up.railway.app/sms/incoming
```

---

## Deploy to Railway

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and deploy
railway login
railway init
railway up

# Set environment variables in Railway dashboard
# (same as your .env file)
```

Your webhook URL will be: `https://<your-project>.up.railway.app/sms/incoming`

---

## iPhone Setup

1. **Claude app** — for manual analysis sessions
2. **Notion app** — to view positions, journal, watchlist
3. Save Fred's Twilio number as a contact: **Fred 🤖**

---

## Syncing Robinhood → Alpaca

Fred can't access Robinhood directly (no API). Instead:

1. Take a screenshot of your Robinhood positions
2. Send it to Fred via SMS or email to `scripts/sync_screenshot.py`
3. Fred reads it with Claude Vision and mirrors to Alpaca paper account
4. From that point, Fred monitors via Alpaca's real-time data

```bash
python scripts/sync_screenshot.py path/to/screenshot.png
```

---

## Project Structure

```
fred/
├── main.py                 ← Entry point
├── config/
│   ├── settings.py         ← All env config (pydantic-settings)
│   └── trading_rules.py    ← Rulebook, prompts, scan universe
├── core/
│   ├── brain.py            ← Claude API wrapper + all prompts
│   ├── confidence.py       ← 0-100 scoring system
│   ├── indicators.py       ← RSI, MACD, EMA, BB, ATR, OBV
│   ├── market.py           ← Market data (yfinance + Polygon)
│   ├── portfolio.py        ← Positions, P&L, SMS trade parsing
│   ├── scanner.py          ← Market scanner (watchlist → setups)
│   └── signals.py          ← Entry/exit gate enforcement
├── integrations/
│   ├── alpaca_client.py    ← Paper trading mirror
│   ├── news_monitor.py     ← RSS + NewsAPI scanning
│   ├── notion_client.py    ← 6-database Notion integration
│   ├── twilio_client.py    ← SMS send/receive
│   └── twitter_monitor.py  ← Trump/Elon/Fed monitoring
├── alerts/
│   ├── engine.py           ← Alert orchestration hub
│   ├── morning_brief.py    ← 8:30 AM daily brief
│   ├── social_alerts.py    ← Twitter callback handler
│   ├── stop_loss.py        ← Position stop monitoring
│   └── technical_alerts.py ← Breakout/setup scanner
├── server/
│   ├── app.py              ← FastAPI + startup lifecycle
│   ├── health.py           ← /health endpoints
│   ├── scheduler.py        ← APScheduler cron jobs
│   └── sms_handler.py      ← Inbound SMS routing
├── scripts/
│   ├── setup_notion.py     ← First-run Notion setup
│   ├── health_check.py     ← Integration connectivity test
│   ├── sync_screenshot.py  ← Robinhood → Alpaca sync
│   └── morning_run.py      ← Manual morning brief trigger
├── tests/
│   ├── conftest.py         ← Shared fixtures
│   ├── test_indicators.py  ← Indicator math tests
│   ├── test_confidence.py  ← Scoring system tests
│   ├── test_signals.py     ← Entry/exit gate tests
│   └── test_portfolio.py   ← Position math + parse tests
└── utils/
    ├── formatters.py       ← SMS message formatters
    ├── logger.py           ← Logging setup
    └── time_utils.py       ← Market hours (ET timezone)
```

---

## Safety Rules (Fred never breaks these)

- Never risk more than 30% of portfolio in a single position
- Always set a stop loss before entering any trade
- Gas, golf, and girlfriend money is never at risk
- Never trade on FOMO — confidence score must be ≥ 50
- Paper account only (Alpaca paper trading mirror)
- You make ALL final trade decisions — Fred advises, you decide

---

*Built with Claude Sonnet 4.6. Strategy: Shark Mode. Goal: Beat the S&P every month.*

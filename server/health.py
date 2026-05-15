"""
server/health.py
================
Health check endpoints for Railway monitoring.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from datetime import datetime
import logging as _logging; logger = _logging.getLogger(__name__)

from config.settings import settings

health_router = APIRouter()


@health_router.get("/health")
async def health_check():
    """Basic liveness check. Railway pings this to verify service is up."""
    return JSONResponse({
        "status": "healthy",
        "service": "fred",
        "timestamp": datetime.now().isoformat(),
        "environment": settings.environment,
    })


@health_router.get("/health/full")
async def full_health_check():
    """
    Deep health check — verifies all integrations are reachable.
    Use for debugging, not for Railway liveness probe.
    """
    checks = {}

    # Check Anthropic
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        checks["anthropic"] = "ok"
    except Exception as e:
        checks["anthropic"] = f"error: {str(e)[:50]}"

    # Check Notion
    try:
        from integrations.notion_client import notion_client
        await notion_client.get_open_positions()
        checks["notion"] = "ok"
    except Exception as e:
        checks["notion"] = f"error: {str(e)[:50]}"

    # Check Alpaca
    try:
        from integrations.alpaca_client import alpaca_client
        account = await alpaca_client.get_account()
        checks["alpaca"] = f"ok — equity ${account.get('equity', 0):.2f}"
    except Exception as e:
        checks["alpaca"] = f"error: {str(e)[:50]}"

    # Check Twitter monitor
    try:
        from integrations.twitter_monitor import twitter_monitor
        status = twitter_monitor.get_monitoring_status()
        checks["twitter"] = f"{'running' if status['running'] else 'stopped'} ({status['mode']})"
    except Exception as e:
        checks["twitter"] = f"error: {str(e)[:50]}"

    # Check Market Data
    try:
        from core.market import market_data
        snap = market_data.get_snapshot("SPY")
        checks["market_data"] = f"ok — SPY ${snap.get('price', 0):.2f}"
    except Exception as e:
        checks["market_data"] = f"error: {str(e)[:50]}"

    all_ok = all("ok" in str(v) for v in checks.values())

    return JSONResponse({
        "status": "healthy" if all_ok else "degraded",
        "checks": checks,
        "timestamp": datetime.now().isoformat(),
    })


@health_router.get("/portfolio")
async def get_portfolio():
    """Current portfolio state. Useful for debugging."""
    from core.portfolio import portfolio_manager
    return JSONResponse(portfolio_manager.get_portfolio_summary())

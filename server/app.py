"""
server/app.py
=============
Fred's FastAPI server. Runs 24/7 on Railway.

Handles:
- Twilio SMS webhooks (text + photo messages)
- Health check endpoints
- Startup / shutdown lifecycle
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from server.health import health_router
from server.scheduler import scheduler
from server.sms_handler import sms_handler

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("fred.app")


# ── Startup / Shutdown ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Boot all background services when the server starts."""
    logger.info("🤖 Fred is waking up...")

    # Load portfolio from Notion
    try:
        from core.portfolio import portfolio_manager
        await portfolio_manager.load_positions()
        logger.info(f"Portfolio: {len(portfolio_manager._positions)} positions loaded")
    except Exception as e:
        logger.warning(f"Portfolio load skipped: {e}")

    # Register alert callbacks
    try:
        from alerts.social_alerts import social_alert_handler
        from alerts.engine import alert_engine
        from integrations.twitter_monitor import twitter_monitor
        from integrations.truth_social_monitor import truth_social_monitor
        from integrations.news_monitor import news_monitor

        social_alert_handler.register_callbacks()
        news_monitor.add_callback(alert_engine.process_news_article)

        # Start Twitter monitor as background task
        asyncio.create_task(twitter_monitor.start_monitoring())
        # Start Truth Social monitor (Trump posts — primary source)
        truth_social_monitor.add_callback(alert_engine.process_truth_social_post)
        await truth_social_monitor.start()
        logger.info("Truth Social monitor started")
        # Start news monitor as background task
        asyncio.create_task(news_monitor.start_monitoring())
        logger.info("Social + news monitors started")
    except Exception as e:
        logger.warning(f"Monitor startup skipped: {e}")

    # Start scheduler
    try:
        scheduler.start()
        logger.info("Scheduler started")
    except Exception as e:
        logger.warning(f"Scheduler startup issue: {e}")

    # Send startup notification
    try:
        from integrations.telegram_client import telegram_client
        from core.mode_manager import mode_manager
        mode_ctx = mode_manager.get_mode_context_for_prompt()[:100]
        await telegram_client.send_async(
            f"🤖 Fred is online.\n{mode_ctx}\nText 'help' for commands."
        )
    except Exception as e:
        logger.debug(f"Startup SMS skipped: {e}")

    # Set Telegram webhook
    try:
        from config.settings import settings as _settings
        if _settings.telegram_bot_token:
            railway_url = f"https://fred-production-4a70.up.railway.app"
            await telegram_client.set_webhook(railway_url)
    except Exception as e:
        logger.debug(f"Telegram webhook setup: {e}")

    logger.info("✅ Fred is ready")
    yield

    # Shutdown
    logger.info("Fred shutting down...")
    try:
        scheduler.shutdown()
        from integrations.twitter_monitor import twitter_monitor
        from integrations.truth_social_monitor import truth_social_monitor
        twitter_monitor.stop()
        await truth_social_monitor.stop()
    except Exception:
        pass


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Fred — AI Trading Assistant",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)


# ── Twilio SMS Webhook ────────────────────────────────────────────────────────

@app.post("/sms/incoming")
async def incoming_sms(
    request: Request,
    Body: str = Form(default=""),
    From: str = Form(default=""),
    NumMedia: str = Form(default="0"),
    MediaUrl0: str = Form(default=""),
    MediaContentType0: str = Form(default=""),
):
    """
    Twilio sends all incoming messages here.
    Handles both text and photo (MMS) messages.
    Photos = chart screenshots → trade plan analysis.
    """
    # Security: verify it's from your number
    if settings.your_phone_number and From and From != settings.your_phone_number:
        logger.warning(f"SMS from unknown number: {From}")
        return PlainTextResponse("", status_code=200)

    body = Body.strip()
    num_media = int(NumMedia) if NumMedia.isdigit() else 0

    logger.info(
        f"SMS received — from: {From} | "
        f"body: '{body[:50]}' | "
        f"media: {num_media}"
    )

    # Run handler as background task so Twilio doesn't time out
    asyncio.create_task(
        sms_handler.handle_incoming(
            body=body,
            from_number=From,
            media_url=MediaUrl0 if num_media > 0 else None,
            media_type=MediaContentType0 if num_media > 0 else None,
        )
    )

    # Return empty TwiML — Fred sends the response separately via API
    return PlainTextResponse(
        '<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="text/xml",
    )




@app.post("/telegram/incoming")
async def incoming_telegram(request: Request):
    """
    Telegram sends all incoming messages here.
    Handles text messages and photo messages (chart screenshots).
    """
    try:
        data = await request.json()
        message = data.get("message", {})
        
        if not message:
            return {"ok": True}

        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "").strip()
        
        # Save chat_id automatically on first message
        if chat_id and not settings.telegram_chat_id:
            logger.info(f"New Telegram chat_id: {chat_id}")

        # Handle photo messages (chart screenshots)
        photos = message.get("photo", [])
        if photos:
            # Get the largest photo
            largest = max(photos, key=lambda p: p.get("file_size", 0))
            file_id = largest.get("file_id", "")
            caption = message.get("caption", "")
            
            asyncio.create_task(
                sms_handler.handle_telegram_photo(
                    file_id=file_id,
                    caption=caption,
                    chat_id=chat_id,
                )
            )
            return {"ok": True}

        # Handle text messages
        if text:
            asyncio.create_task(
                sms_handler.handle_incoming(
                    body=text,
                    from_number=chat_id,
                    chat_id=chat_id,
                )
            )

        return {"ok": True}
    except Exception as e:
        logger.error(f"Telegram webhook error: {e}")
        return {"ok": True}  # Always return 200 to Telegram

@app.get("/")
async def root():
    return {"status": "Fred is alive", "version": "2.0.0"}

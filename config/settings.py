"""
config/settings.py
==================
Central configuration for Fred. All values loaded from environment.
Never hardcode secrets. Use .env for local dev, Railway env vars for prod.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional, List
from functools import lru_cache
import os


class Settings(BaseSettings):
    # ── Anthropic ─────────────────────────────────────────────
    anthropic_api_key: str = Field(..., env="ANTHROPIC_API_KEY")
    anthropic_model: str = Field("claude-sonnet-4-20250514", env="ANTHROPIC_MODEL")

    # ── Notion ────────────────────────────────────────────────
    notion_api_key: str = Field(..., env="NOTION_API_KEY")
    notion_positions_db: str = Field("", env="NOTION_POSITIONS_DB")
    notion_watchlist_db: str = Field("", env="NOTION_WATCHLIST_DB")
    notion_journal_db: str = Field("", env="NOTION_JOURNAL_DB")
    notion_rules_db: str = Field("", env="NOTION_RULES_DB")
    notion_alerts_log_db: str = Field("", env="NOTION_ALERTS_LOG_DB")
    notion_social_triggers_db: str = Field("", env="NOTION_SOCIAL_TRIGGERS_DB")
    notion_freds_brain_page_id: str = Field("", env="NOTION_FREDS_BRAIN_PAGE_ID")

    # ── Alpaca ────────────────────────────────────────────────
    alpaca_api_key: Optional[str] = Field(None, env="ALPACA_API_KEY")
    alpaca_secret_key: Optional[str] = Field(None, env="ALPACA_SECRET_KEY")
    alpaca_base_url: str = Field(
        "https://paper-api.alpaca.markets", env="ALPACA_BASE_URL"
    )

    # ── Polygon ───────────────────────────────────────────────
    polygon_api_key: Optional[str] = Field(None, env="POLYGON_API_KEY")
    use_yfinance_fallback: bool = Field(True, env="USE_YFINANCE_FALLBACK")

    # ── Twitter/X ─────────────────────────────────────────────
    twitter_bearer_token: Optional[str] = Field(None, env="TWITTER_BEARER_TOKEN")
    twitter_api_key: Optional[str] = Field(None, env="TWITTER_API_KEY")
    twitter_api_secret: Optional[str] = Field(None, env="TWITTER_API_SECRET")
    twitter_access_token: Optional[str] = Field(None, env="TWITTER_ACCESS_TOKEN")
    twitter_access_secret: Optional[str] = Field(None, env="TWITTER_ACCESS_SECRET")
    twitter_use_scraper: bool = Field(True, env="TWITTER_USE_SCRAPER")

    # ── Twilio ────────────────────────────────────────────────────────────────
    twilio_account_sid: Optional[str] = Field(None, env="TWILIO_ACCOUNT_SID")
    twilio_auth_token: Optional[str] = Field(None, env="TWILIO_AUTH_TOKEN")
    twilio_phone_number: Optional[str] = Field(None, env="TWILIO_PHONE_NUMBER")
    your_phone_number: Optional[str] = Field(None, env="YOUR_PHONE_NUMBER")

    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_bot_token: str = Field("", env="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field("", env="TELEGRAM_CHAT_ID")
    twitter_watch_accounts_raw: str = Field(
        "realDonaldTrump,elonmusk", env="TWITTER_WATCH_ACCOUNTS"
    )

    @property
    def twitter_watch_accounts(self) -> List[str]:
        return [a.strip() for a in self.twitter_watch_accounts_raw.split(",")]

    # ── News ──────────────────────────────────────────────────
    enable_news_monitor: bool = Field(True, env="ENABLE_NEWS_MONITOR")
    newsapi_key: Optional[str] = Field(None, env="NEWSAPI_KEY")

    # ── Server ────────────────────────────────────────────────
    port: int = Field(8000, env="PORT")
    base_url: str = Field("http://localhost:8000", env="BASE_URL")
    webhook_secret: str = Field("change-me", env="WEBHOOK_SECRET")

    # ── Trading ───────────────────────────────────────────────
    max_position_size_pct: float = Field(30.0, env="MAX_POSITION_SIZE_PCT")
    min_confidence_score: int = Field(50, env="MIN_CONFIDENCE_SCORE")
    circuit_breaker_pct: float = Field(3.0, env="CIRCUIT_BREAKER_PCT")
    position_check_interval: int = Field(300, env="POSITION_CHECK_INTERVAL")
    setup_scan_interval: int = Field(900, env="SETUP_SCAN_INTERVAL")
    news_scan_interval: int = Field(900, env="NEWS_SCAN_INTERVAL")
    morning_brief_time: str = Field("08:30", env="MORNING_BRIEF_TIME")
    eod_debrief_time: str = Field("16:30", env="EOD_DEBRIEF_TIME")
    sunday_sync_time: str = Field("19:00", env="SUNDAY_SYNC_TIME")

    # ── Timezone ──────────────────────────────────────────────
    timezone: str = Field("America/Indiana/Indianapolis", env="TIMEZONE")

    # ── Logging ───────────────────────────────────────────────
    log_level: str = Field("INFO", env="LOG_LEVEL")
    log_file: str = Field("logs/fred.log", env="LOG_FILE")

    # ── Environment ───────────────────────────────────────────
    environment: str = Field("development", env="ENVIRONMENT")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def has_twitter_api(self) -> bool:
        return bool(self.twitter_bearer_token and self.twitter_api_key)

    @property
    def has_polygon(self) -> bool:
        return bool(self.polygon_api_key)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Cached settings singleton. Call get_settings() anywhere."""
    return Settings()


# Convenience alias
settings = get_settings()

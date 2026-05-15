"""
server/scheduler.py
====================
Fred's complete daily schedule. All times Eastern.

THREE CORE DAILY UPDATES:
  8:00 AM   Discovery scan (volume surges, gappers, sector rotation)
  8:30 AM   Morning brief → your positions, market overview, top setups
  12:00 PM  Midday check → how the day is going, setups since morning
  6:00 PM   Evening report → EOD summary, positions overnight, tomorrow's setups

CONTINUOUS MONITORING (market hours):
  Every 5 min   Stop loss checks
  Every 10 min  Watchlist scanner — surfaces new setups as they form
  Every 60 sec  Social / RSS monitors (running in background loops)

GAP SCANS:
  8:00 PM   After-hours gap scan (earnings reactions settling)
  4:30 AM   Pre-market gap scan (gap forming before retail)
  9:15 AM   Confirmation scan (is it still holding?)

WEEKLY:
  Sunday 7 PM   Weekly game plan
"""

import logging
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings

logger = logging.getLogger("fred.scheduler")

ET = ZoneInfo("America/New_York")


class FredScheduler:

    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=ET)
        self._configured = False

    def start(self) -> None:
        if not self._configured:
            self._configure_jobs()
            self._configured = True
        self.scheduler.start()
        jobs = self.scheduler.get_jobs()
        logger.info(f"Scheduler started — {len(jobs)} jobs")
        for job in jobs:
            logger.info(f"  [{job.id}] next: {job.next_run_time}")

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    def _configure_jobs(self) -> None:

        # ── 8:00 AM — Discovery scan (runs BEFORE morning brief) ──────────────
        self.scheduler.add_job(
            self._discovery_scan,
            CronTrigger(hour=8, minute=0, day_of_week="mon-fri"),
            id="discovery_am", name="8am Discovery",
            replace_existing=True, misfire_grace_time=300,
        )

        # ── 8:30 AM — Morning brief ────────────────────────────────────────────
        self.scheduler.add_job(
            self._morning_brief,
            CronTrigger(hour=8, minute=30, day_of_week="mon-fri"),
            id="morning_brief", name="8:30am Morning Brief",
            replace_existing=True, misfire_grace_time=300,
        )

        # ── 9:00 AM — Pre-market setup scan ───────────────────────────────────
        self.scheduler.add_job(
            self._premarket_scan,
            CronTrigger(hour=9, minute=0, day_of_week="mon-fri"),
            id="premarket_scan", name="9am Pre-market Scan",
            replace_existing=True, misfire_grace_time=300,
        )

        # ── 9:15 AM — Gap confirmation ─────────────────────────────────────────
        self.scheduler.add_job(
            self._gap_scan_confirm,
            CronTrigger(hour=9, minute=15, day_of_week="mon-fri"),
            id="gap_confirm", name="9:15am Gap Confirmation",
            replace_existing=True, misfire_grace_time=120,
        )

        # ── Every 5 min — Stop loss monitor (market hours) ────────────────────
        self.scheduler.add_job(
            self._stop_loss_check,
            CronTrigger(minute="*/5", hour="9-16", day_of_week="mon-fri"),
            id="stop_loss", name="Stop Loss Monitor",
            replace_existing=True,
        )

        # ── Every 10 min — Watchlist scanner (market hours) ───────────────────
        self.scheduler.add_job(
            self._watchlist_scan,
            CronTrigger(minute="*/10", hour="9-16", day_of_week="mon-fri"),
            id="watchlist_scan", name="Watchlist Scanner",
            replace_existing=True,
        )

        # ── 12:00 PM — Midday update ───────────────────────────────────────────
        self.scheduler.add_job(
            self._midday_report,
            CronTrigger(hour=12, minute=0, day_of_week="mon-fri"),
            id="midday_report", name="12pm Midday Update",
            replace_existing=True, misfire_grace_time=300,
        )

        # ── 6:00 PM — Evening report (EOD + tomorrow setup) ───────────────────
        self.scheduler.add_job(
            self._evening_report,
            CronTrigger(hour=18, minute=0, day_of_week="mon-fri"),
            id="evening_report", name="6pm Evening Report",
            replace_existing=True, misfire_grace_time=300,
        )

        # ── 8:00 PM — After-hours gap scan ────────────────────────────────────
        self.scheduler.add_job(
            self._gap_scan_afterhours,
            CronTrigger(hour=20, minute=0, day_of_week="mon-fri"),
            id="gap_afterhours", name="8pm AH Gap Scan",
            replace_existing=True, misfire_grace_time=600,
        )

        # ── 4:30 AM — Pre-market gap scan ─────────────────────────────────────
        self.scheduler.add_job(
            self._gap_scan_premarket,
            CronTrigger(hour=4, minute=30, day_of_week="tue-sat"),
            id="gap_premarket", name="4:30am PM Gap Scan",
            replace_existing=True, misfire_grace_time=600,
        )

        # ── Sunday 7 PM — Weekly game plan ────────────────────────────────────
        self.scheduler.add_job(
            self._sunday_sync,
            CronTrigger(day_of_week="sun", hour=19, minute=0),
            id="sunday_sync", name="Sunday Game Plan",
            replace_existing=True, misfire_grace_time=600,
        )

        # ── Every 30 min — Notion sync ─────────────────────────────────────────
        self.scheduler.add_job(
            self._notion_sync,
            IntervalTrigger(minutes=30),
            id="notion_sync", name="Notion Sync",
            replace_existing=True,
        )

    # ── 8am ───────────────────────────────────────────────────────────────────

    async def _discovery_scan(self):
        """8:00 AM — Find volume surges, gappers, sector rotation."""
        logger.info("⏰ 8am discovery scan")
        try:
            from core.discovery import discovery_engine
            from integrations.telegram_client import telegram_client
            discoveries = discovery_engine.run_full_discovery()
            if discoveries:
                sms = discovery_engine.get_discovery_summary_sms(discoveries)
                telegram_client.send(sms, alert_key="discovery_am")
        except Exception as e:
            logger.error(f"8am discovery error: {e}")

    async def _morning_brief(self):
        """8:30 AM — Full morning brief with positions, market, setups."""
        logger.info("⏰ 8:30am morning brief")
        try:
            from alerts.morning_brief import MorningBriefGenerator
            gen = MorningBriefGenerator()
            await gen.generate_and_send()
        except Exception as e:
            logger.error(f"Morning brief error: {e}")

    # ── 9am ───────────────────────────────────────────────────────────────────

    async def _premarket_scan(self):
        """9:00 AM — Pre-market technical setup scan."""
        logger.info("⏰ 9am pre-market scan")
        try:
            from alerts.technical_alerts import technical_scanner
            await technical_scanner._run_scan()
        except Exception as e:
            logger.error(f"Pre-market scan error: {e}")

    async def _gap_scan_confirm(self):
        """9:15 AM — Confirm overnight gaps are still holding."""
        logger.info("⏰ 9:15am gap confirmation")
        try:
            from core.gap_scanner import gap_scanner
            from core.portfolio import portfolio_manager
            from core.mode_manager import mode_manager
            from integrations.telegram_client import telegram_client
            balance = portfolio_manager.get_account_value()
            result = await gap_scanner.confirmation_scan(balance, "builder")
            telegram_client.send(result, alert_key="gap_confirm")
        except Exception as e:
            logger.error(f"Gap confirmation error: {e}")

    # ── Market hours continuous ────────────────────────────────────────────────

    async def _stop_loss_check(self):
        logger.debug("⏰ Stop loss check")
        try:
            from alerts.stop_loss import stop_loss_monitor
            await stop_loss_monitor._check_all_positions()
        except Exception as e:
            logger.error(f"Stop loss error: {e}")

    async def _watchlist_scan(self):
        """Every 10 min — scan watchlist and surface setups as they form."""
        logger.debug("⏰ Watchlist scan")
        try:
            from alerts.technical_alerts import technical_scanner
            await technical_scanner._run_scan()
        except Exception as e:
            logger.error(f"Watchlist scan error: {e}")

    # ── 12pm ──────────────────────────────────────────────────────────────────

    async def _midday_report(self):
        """12:00 PM — How the day is going, setups since morning."""
        logger.info("⏰ 12pm midday report")
        try:
            from alerts.midday_report import MidDayReportGenerator
            gen = MidDayReportGenerator()
            await gen.generate_and_send()
        except Exception as e:
            logger.error(f"Midday report error: {e}")

    # ── 6pm ───────────────────────────────────────────────────────────────────

    async def _evening_report(self):
        """
        6:00 PM — Combined EOD + tomorrow setup.
        What happened today, positions overnight, what to watch pre-market.
        """
        logger.info("⏰ 6pm evening report")
        try:
            from core.portfolio import portfolio_manager
            from core.market import market_data
            from core.mode_manager import mode_manager
            from core.gap_scanner import gap_scanner
            from core.brain import fred_brain
            from integrations.telegram_client import telegram_client
            from datetime import datetime

            await portfolio_manager.refresh_prices()
            positions = list(portfolio_manager._positions.values())

            # Get gap plays for tomorrow
            balance = portfolio_manager.get_account_value()
            gap_text = await gap_scanner.scan_and_alert(balance, "builder")

            # Market close data
            try:
                spy = market_data.get_snapshot("SPY")
                qqq = market_data.get_snapshot("QQQ")
                spy_pct = spy.get("change_pct", 0)
                qqq_pct = qqq.get("change_pct", 0)
                market_close = f"SPY {spy_pct:+.1f}% | QQQ {qqq_pct:+.1f}%"
            except Exception:
                market_close = "Market close data unavailable"

            positions_str = "\n".join([
                f"{pos.ticker}: {pos.pnl_pct:+.1f}% | Stop ${pos.stop_loss:.2f}"
                for pos in positions
            ]) if positions else "No open positions"

            challenge_status = (
                "Builder Mode — intelligent compounding."
                if False else ""
            )

            eod = await fred_brain.generate_eod_debrief_async(context={
                "date": datetime.now().strftime("%A, %b %d"),
                "mode": "builder",
                "positions": positions_str,
                "closed_today": "Check Notion for today's closes",
                "day_pnl": f"${sum(p.pnl_dollars for p in positions):+.2f}" if positions else "$0",
                "challenge_status": challenge_status,
            })

            # Combine EOD + gap plays for tomorrow
            full_report = f"{eod}\n\n---\n\n🌙 TONIGHT'S GAPS\n\n{gap_text[:400]}"
            telegram_client.send(full_report, alert_key="evening_report")
            logger.info("Evening report sent")

        except Exception as e:
            logger.error(f"Evening report error: {e}")

    # ── Gap scans ─────────────────────────────────────────────────────────────

    async def _gap_scan_afterhours(self):
        logger.info("⏰ 8pm AH gap scan")
        try:
            from core.gap_scanner import gap_scanner
            from core.portfolio import portfolio_manager
            from core.mode_manager import mode_manager
            from integrations.telegram_client import telegram_client
            balance = portfolio_manager.get_account_value()
            result = await gap_scanner.scan_and_alert(balance, "builder")
            telegram_client.send(result, alert_key="gap_afterhours")
        except Exception as e:
            logger.error(f"AH gap scan error: {e}")

    async def _gap_scan_premarket(self):
        logger.info("⏰ 4:30am gap scan")
        try:
            from core.gap_scanner import gap_scanner
            from core.portfolio import portfolio_manager
            from core.mode_manager import mode_manager
            from integrations.telegram_client import telegram_client
            balance = portfolio_manager.get_account_value()
            result = await gap_scanner.scan_and_alert(balance, "builder")
            telegram_client.send(result, alert_key="gap_premarket")
        except Exception as e:
            logger.error(f"Premarket gap scan error: {e}")

    # ── Weekly + sync ─────────────────────────────────────────────────────────

    async def _sunday_sync(self):
        logger.info("⏰ Sunday game plan")
        try:
            from alerts.engine import alert_engine
            await alert_engine.send_sunday_sync()
        except Exception as e:
            logger.error(f"Sunday sync error: {e}")

    async def _notion_sync(self):
        logger.debug("⏰ Notion sync")
        try:
            from core.portfolio import portfolio_manager
            await portfolio_manager.load_positions()
            await portfolio_manager.refresh_prices()
        except Exception as e:
            logger.error(f"Notion sync error: {e}")


# Global singleton
scheduler = FredScheduler()

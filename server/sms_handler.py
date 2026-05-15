"""
server/sms_handler.py
======================
Every text you send to Fred lands here first.

Routes commands, handles photos (chart screenshots → trade plan),
manages conversation history, and keeps Fred's context current.

SMS Commands:
  status / portfolio      full health check
  brief                   morning brief on demand
  scan                    market scan now
  discover                run discovery scan
  watchlist               your current list
  add NVDA [reason]       add to watchlist
  remove NVDA             remove from watchlist
  buy NVDA 20 at 127...   log a new position
  sell / sold NVDA        close a position
  stop NVDA 122           update stop loss
  NVDA                    full analysis
  progress — performance stats
  builder                 activate Builder Mode
  pdt                     check day trade count
  rules                   your trading rules
  how am i doing          performance stats
  help                    command list
  [photo]                 chart screenshot → trade plan
  [anything]              Fred answers naturally
"""

import asyncio
import base64
import logging
import re
from datetime import datetime
from typing import Optional

from core.brain import fred_brain
from core.market import market_data
from core.portfolio import portfolio_manager
from core.mode_manager import mode_manager
from core.scanner import market_scanner
from integrations.notion_client import notion_client
from integrations.telegram_client import telegram_client
from utils.formatters import sms_help_menu
from utils.time_utils import market_session

logger = logging.getLogger("fred.sms")


class SMSHandler:
    """Routes and handles all incoming SMS messages and media."""

    def __init__(self):
        self._history: dict[str, list] = {}

    async def handle_incoming(
        self,
        body: str,
        from_number: str,
        media_url: Optional[str] = None,
        media_type: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> None:
        """
        Main entry point. Handles both text and photo messages.
        Photos (chart screenshots) go straight to trade plan analysis.
        """
        # ── Photo message — chart screenshot ─────────────────────────────────
        if media_url and media_type and "image" in media_type:
            await self._handle_chart_photo(media_url, body, from_number)
            return

        # ── Text message ──────────────────────────────────────────────────────
        cmd = body.strip().lower()
        history = self._get_history(from_number)

        logger.info(f"SMS from {from_number}: '{body[:60]}'")

        try:
            response = await self._route(cmd, body, history)
        except Exception as e:
            logger.error(f"SMS route error: {e}")
            response = "⚠️ Something went wrong. Try again or text 'help'."

        if response:
            telegram_client.send(response, to=from_number)
            self._update_history(from_number, body, response)

    # ── Photo Handler ─────────────────────────────────────────────────────────

    async def handle_telegram_photo(
        self, file_id: str, caption: str, chat_id: str
    ) -> None:
        """Handle a photo sent via Telegram."""
        telegram_client.send("📸 Chart received. Analyzing setup...", to=chat_id)
        try:
            import httpx
            from config.settings import settings
            # Get file path from Telegram
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile",
                    params={"file_id": file_id},
                )
                file_path = resp.json()["result"]["file_path"]
                file_url = f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}"
                img_resp = await client.get(file_url)
                img_b64 = base64.b64encode(img_resp.content).decode("utf-8")

            positions = portfolio_manager.get_position_tickers()
            balance = portfolio_manager.get_account_value()
            trade_plan = fred_brain.analyze_chart_screenshot(
                image_base64=img_b64,
                current_balance=balance,
                open_positions=positions,
            )
            telegram_client.send(trade_plan, to=chat_id)
        except Exception as e:
            logger.error(f"Telegram photo handler error: {e}")
            telegram_client.send(
                "Couldn't analyze that chart. Try a cleaner screenshot or send me the ticker directly.",
                to=chat_id,
            )

    async def _handle_chart_photo(
        self, media_url: str, caption: str, from_number: str
    ) -> None:
        """
        Trader sent a chart screenshot.
        Fred reads it, picks the stop from chart structure,
        and returns a complete trade plan.
        """
        telegram_client.send(
            "📸 Chart received. Analyzing setup...", to=from_number
        )

        try:
            # Download the image
            import requests
            img_resp = requests.get(
                media_url,
                timeout=15,
            )
            if img_resp.status_code != 200:
                telegram_client.send(
                    "Couldn't download the image. Try again.", to=from_number
                )
                return

            img_b64 = base64.b64encode(img_resp.content).decode("utf-8")

            # Build context
            positions = portfolio_manager.get_position_tickers()
            balance = portfolio_manager.get_account_value()

            # Get trade plan from Fred's brain
            trade_plan = fred_brain.analyze_chart_screenshot(
                image_base64=img_b64,
                current_balance=balance,
                open_positions=positions,
            )

            telegram_client.send(trade_plan, to=from_number)
            self._update_history(from_number, "[chart photo]", trade_plan)

        except Exception as e:
            logger.error(f"Chart photo handler error: {e}")
            telegram_client.send(
                "Couldn't analyze that chart. Try a cleaner screenshot "
                "or send me the ticker directly.",
                to=from_number,
            )

    # ── Command Router ────────────────────────────────────────────────────────

    async def _route(self, cmd: str, original: str, history: list) -> str:
        # Status / portfolio
        if cmd in ("status", "portfolio", "positions"):
            return await self._status()

        # Morning brief on demand
        if cmd in ("brief", "morning brief", "morning"):
            return await self._brief()

        # Midday report on demand
        if cmd in ("midday", "noon", "check in", "midday report"):
            return await self._midday()

        # Market scan
        if cmd in ("scan", "scan now", "find trades"):
            return await self._scan()

        # Discovery scan
        if cmd in ("discover", "discovery", "find new stocks"):
            return await self._discover()

        # Progress / challenge
        if cmd in ("progress", "challenge", "how far", "stats"):
            return mode_manager.get_challenge_progress()

        # Mode switch attempts — Fred only runs Builder Mode now
        if any(c in cmd for c in ("shark mode", "activate shark", "activate builder", "switch mode")):
            return (
                "Running Builder Mode — intelligent sizing, sustainable compounding.\n"
                "25-28% on conviction, 15-20% on strong setups, 8-12% on moderate.\n"
                "This is how you grow capital without blowing it."
            )

        # PDT check
        if cmd in ("pdt", "day trades", "day trade count", "trades left"):
            return self._pdt_status()

        # Watchlist
        if cmd in ("watchlist", "watch list", "my watchlist"):
            return await self._watchlist()

        # Rules
        if cmd in ("rules", "my rules", "trading rules"):
            from config.trading_rules import get_rules_summary
            return get_rules_summary()

        # Performance
        if any(p in cmd for p in ("how am i doing", "performance", "stats", "win rate")):
            return await self._performance()

        # Help
        if cmd in ("help", "commands", "?"):
            return sms_help_menu()

        # Sync from Notion
        if cmd in ("sync", "refresh", "reload"):
            return await self._sync()

        # Buy command
        if self._is_buy(cmd):
            return await self._handle_buy(original)

        # Sell command
        if self._is_sell(cmd):
            ticker = self._extract_ticker_from_sell(cmd)
            return await self._handle_sell(ticker)

        # Stop update
        if self._is_stop_update(cmd):
            return await self._handle_stop_update(cmd)

        # Watchlist add
        if cmd.startswith("add "):
            return await self._handle_add(original)

        # Watchlist remove
        if cmd.startswith("remove ") or cmd.startswith("drop "):
            ticker = cmd.split()[1].upper() if len(cmd.split()) > 1 else ""
            return await self._handle_remove(ticker)

        # Gap plays
        if cmd in ("gaps", "gap plays", "gappers", "movers", "overnight"):
            return await self._gap_scan()

        # Truth Social / political monitor status
        if cmd in ("trump", "ts", "truth social", "truth"):
            return await self._trump_status()

        # Confidence weights analysis
        if cmd in ("weights", "weight analysis", "weights advice"):
            return await self._weights()

        # Single ticker — full analysis
        ticker = self._extract_single_ticker(cmd)
        if ticker:
            return await self._analyze_ticker(ticker)

        # Natural language fallback
        return await self._natural(original, history)

    # ── Handlers ─────────────────────────────────────────────────────────────

    async def _status(self) -> str:
        positions = list(portfolio_manager._positions.values())
        if not positions:
            regime = market_data.get_market_regime()
            mode_ctx = mode_manager.get_mode_context_for_prompt()
            return (
                f"💼 PORTFOLIO STATUS\n"
                f"No open positions.\n"
                f"Cash ready to deploy.\n"
                f"Market: {regime.get('regime','?').upper()}\n\n"
                f"{mode_ctx[:150]}"
            )

        lines = ["💼 PORTFOLIO\n"]
        total_pnl = 0.0
        for pos in positions:
            pnl = pos.pnl_dollars
            total_pnl += pnl
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(
                f"{emoji} {pos.ticker}\n"
                f"   Entry: ${pos.entry_price:.2f} | Now: ${pos.current_price:.2f}\n"
                f"   P&L: {'+' if pnl>=0 else ''}${pnl:.2f} ({pos.pnl_pct:+.1f}%)\n"
                f"   Stop: ${pos.stop_loss:.2f} | Target: ${pos.target:.2f}"
            )

        lines.append(f"\nTotal P&L: {'+' if total_pnl>=0 else ''}${total_pnl:.2f}")

        # Add mode status


        return "\n".join(lines)

    async def _brief(self) -> str:
        try:
            from alerts.morning_brief import MorningBriefGenerator
            gen = MorningBriefGenerator()
            return await gen.generate_and_send(send=False)
        except Exception as e:
            logger.error(f"Brief error: {e}")
            return "Generating brief failed. Check logs."

    async def _scan(self) -> str:
        try:
            regime = market_data.get_market_regime()

            pdt_warn = mode_manager.pdt_warning or ""

            result = market_scanner.scan_to_sms(max_results=3)

            if pdt_warn:
                result = f"{pdt_warn}\n\n{result}"

            return result
        except Exception as e:
            logger.error(f"Scan error: {e}")
            return "Scan failed. Try again in a minute."

    async def _discover(self) -> str:
        try:
            from core.discovery import discovery_engine
            telegram_client.send("🔍 Running discovery scan...", to="")
            discoveries = discovery_engine.run_full_discovery()
            return discovery_engine.get_discovery_summary_sms(discoveries)
        except Exception as e:
            logger.error(f"Discovery error: {e}")
            return "Discovery scan failed. Try again."



    def _pdt_status(self) -> str:
        remaining = mode_manager.day_trades_remaining
        used = 3 - remaining
        warn = mode_manager.pdt_warning

        status = (
            f"📋 PDT STATUS\n"
            f"Day trades used this week: {used}/3\n"
            f"Remaining: {remaining}\n"
        )
        if warn:
            status += f"\n{warn}"
        elif remaining == 3:
            status += "\nAll clear — full week available."
        return status

    async def _watchlist(self) -> str:
        try:
            items = await notion_client.get_watchlist()
            if not items:
                from config.trading_rules import SCAN_UNIVERSE
                return (
                    f"📋 WATCHLIST ({len(SCAN_UNIVERSE)} tickers)\n"
                    + ", ".join(SCAN_UNIVERSE)
                )
            lines = [f"📋 WATCHLIST ({len(items)})\n"]
            for item in items:
                ticker = item.get("ticker", "?")
                thesis = item.get("thesis", "")[:50]
                lines.append(f"  {ticker}" + (f" — {thesis}" if thesis else ""))
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Watchlist error: {e}")
            return "Couldn't load watchlist. Try 'sync' first."

    async def _performance(self) -> str:
        try:
            total = portfolio_manager._positions
            closed = getattr(portfolio_manager, "_closed_positions", [])

            wins = sum(1 for p in closed if p.get("pnl_dollars", 0) > 0)
            losses = sum(1 for p in closed if p.get("pnl_dollars", 0) <= 0)
            total_trades = wins + losses
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            total_pnl = sum(p.get("pnl_dollars", 0) for p in closed)

            lines = [
                f"📊 FRED STATS\n",
                f"Total trades: {total_trades}",
                f"Wins: {wins} | Losses: {losses}",
                f"Win rate: {win_rate:.0f}%",
                f"Total P&L: {'+' if total_pnl>=0 else ''}${total_pnl:.2f}",
                f"Open positions: {len(total)}",
            ]


            return "\n".join(lines)
        except Exception as e:
            return "Stats unavailable. Try 'status' for current positions."

    async def _sync(self) -> str:
        try:
            await portfolio_manager.load_positions()
            await portfolio_manager.refresh_prices()
            count = len(portfolio_manager._positions)
            return f"✅ Synced. {count} open position(s) loaded from Notion."
        except Exception as e:
            return f"Sync failed: {e}"

    async def _handle_buy(self, original: str) -> str:
        parsed = portfolio_manager.parse_buy_message(original)
        if not parsed or not parsed.get("ticker"):
            return (
                "Couldn't parse that trade. Try:\n"
                "buy NVDA 20 shares at 127 stop 122 target 138"
            )

        ticker = parsed["ticker"]
        entry = parsed.get("entry_price", 0)
        stop = parsed.get("stop_loss", 0)
        target = parsed.get("target", 0)
        shares = parsed.get("shares", 0)

        if not all([ticker, entry, shares]):
            return "Need at least: ticker, shares, and entry price."

        # Check R:R
        rr_ok = True
        if stop and target and entry:
            risk = entry - stop
            reward = target - entry
            rr = reward / risk if risk > 0 else 0
            rr_ok = rr >= 2.0

        # PDT check
        pdt_msg = ""
        pdt_warn = mode_manager.pdt_warning
        if pdt_warn:
            pdt_msg = f"\n\n{pdt_warn}"

        # Builder Mode sizing suggestion
        sizing_msg = ""

        # Log to Notion
        try:
            await notion_client.add_position({
                "ticker": ticker,
                "shares": shares,
                "entry_price": entry,
                "stop_loss": stop,
                "target": target,
                "mode": mode_manager.mode,
            })
        except Exception as e:
            logger.error(f"Notion position log error: {e}")

        rr_str = ""
        if stop and target and entry:
            risk = entry - stop
            reward = target - entry
            rr = reward / risk if risk > 0 else 0
            rr_str = f"\nR:R: {rr:.1f}:1 {'✅' if rr_ok else '⚠️ below 2:1'}"

        return (
            f"✅ LOGGED — {ticker}\n"
            f"{shares} shares @ ${entry:.2f}\n"
            f"Stop: ${stop:.2f} | Target: ${target:.2f}"
            f"{rr_str}\n"
            f"{sizing_msg}"
            f"{pdt_msg}\n"
            f"Set your stop in Robinhood NOW before anything else."
        )

    async def _handle_sell(self, ticker: str) -> str:
        if not ticker:
            return "Which ticker? Send: sold NVDA"

        pos = portfolio_manager.get_position(ticker.upper())
        if not pos:
            return f"No open position found for {ticker.upper()}."

        pnl = pos.pnl_dollars
        pnl_pct = pos.pnl_pct
        emoji = "✅" if pnl >= 0 else "📉"

        # Close in portfolio
        try:
            await portfolio_manager.close_position(
                ticker.upper(),
                reason="manual_sell",
                close_price=pos.current_price,
            )
        except Exception as e:
            logger.error(f"Close position error: {e}")

        # Update mode manager balance
        new_balance = portfolio_manager.get_account_value()
        milestone_msg = mode_manager.update_balance(new_balance) or ""
        mode_manager.record_trade_result(pnl, pnl >= 0)

        # Write brain note
        note_ctx = (
            f"Closed {ticker.upper()} — "
            f"entry ${pos.entry_price:.2f} → close ${pos.current_price:.2f} "
            f"P&L: {'+' if pnl>=0 else ''}${pnl:.2f} ({pnl_pct:+.1f}%)"
        )
        import threading
        threading.Thread(
            target=fred_brain._async_write_brain_note,
            args=(note_ctx, ticker.upper()),
            daemon=True,
        ).start()

        response = (
            f"{emoji} CLOSED — {ticker.upper()}\n"
            f"P&L: {'+' if pnl>=0 else ''}${pnl:.2f} ({pnl_pct:+.1f}%)\n"
            f"Entry: ${pos.entry_price:.2f} → Close: ${pos.current_price:.2f}"
        )

        if milestone_msg:
            response += f"\n\n{milestone_msg}"

        return response

    async def _handle_stop_update(self, cmd: str) -> str:
        parts = cmd.split()
        ticker = ""
        new_stop = 0.0
        for part in parts:
            clean = re.sub(r'[^A-Za-z]', '', part).upper()
            if 1 <= len(clean) <= 5 and clean not in {'STOP', 'UPDATE', 'SET', 'CHANGE', 'MOVE'}:
                ticker = clean
            try:
                val = float(re.sub(r'[^0-9.]', '', part))
                if val > 0:
                    new_stop = val
            except ValueError:
                pass

        if not ticker or not new_stop:
            return "Format: stop NVDA 122.50"

        pos = portfolio_manager.get_position(ticker)
        if not pos:
            return f"No open position for {ticker}."

        old_stop = pos.stop_loss
        try:
            await portfolio_manager.update_stop_loss(ticker, new_stop)
        except Exception as e:
            logger.error(f"Stop update error: {e}")
            return f"Failed to update stop for {ticker}."

        direction = "🔼 tightened" if new_stop > old_stop else "🔽 loosened"
        return (
            f"✅ {ticker} stop updated\n"
            f"${old_stop:.2f} → ${new_stop:.2f} ({direction})\n"
            f"Update in Robinhood too."
        )

    async def _handle_add(self, original: str) -> str:
        words = original.split()
        ticker = ""
        for w in words[1:]:
            clean = re.sub(r'[^A-Za-z]', '', w).upper()
            if 1 <= len(clean) <= 5 and clean not in {'ADD', 'TO', 'THE', 'WATCH', 'WATCHLIST'}:
                ticker = clean
                break
        if not ticker:
            return "Format: add NVDA [optional reason]"

        thesis = " ".join(words[words.index(ticker.lower() if ticker.lower() in original.lower() else ticker)+1:])[:100]

        try:
            await notion_client.add_to_watchlist(ticker, thesis)
        except Exception as e:
            logger.error(f"Add watchlist error: {e}")

        return f"✅ {ticker} added to watchlist.\n{thesis if thesis else 'No thesis noted.'}"

    async def _handle_remove(self, ticker: str) -> str:
        if not ticker:
            return "Which ticker? Send: remove NVDA"
        try:
            await notion_client.remove_from_watchlist(ticker)
        except Exception as e:
            logger.error(f"Remove watchlist error: {e}")
        return f"✅ {ticker} removed from watchlist."

    async def _analyze_ticker(self, ticker: str) -> str:
        try:
            snapshot = market_data.get_snapshot(ticker)
            if "error" in snapshot:
                return f"Couldn't get data for {ticker}. Check the ticker."

            news = []
            try:
                from integrations.news_monitor import news_monitor
                news = await news_monitor.search_news_for_ticker(ticker)
            except Exception:
                pass

            news_ctx = "\n".join([a.get("title", "") for a in news[:3]]) or "No recent news."
            regime = market_data.get_market_regime()
            portfolio_ctx = portfolio_manager.get_portfolio_context_str()

            result = fred_brain.analyze_setup(
                ticker=ticker,
                technical_data=snapshot,
                news_context=news_ctx,
                portfolio_context=portfolio_ctx,
                market_regime=regime.get("regime", "neutral"),
            )

            # Add PDT warning if relevant
            pdt_warn = mode_manager.pdt_warning
            if pdt_warn:
                return f"{result['analysis']}\n\n{pdt_warn}"

            return result["analysis"]

        except Exception as e:
            logger.error(f"Ticker analysis error for {ticker}: {e}")
            return f"Analysis failed for {ticker}. Try again."

    async def _natural(self, message: str, history: list) -> str:
        session = market_session()
        portfolio_ctx = portfolio_manager.get_portfolio_context_str()
        balance = portfolio_manager.get_account_value()
        mode_ctx = mode_manager.get_mode_context_for_prompt()

        return fred_brain.answer_sms(
            message=message,
            conversation_history=history,
            portfolio_context=f"{portfolio_ctx}\n\n{mode_ctx}",
            market_session=session,
            account_value=balance,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_history(self, number: str) -> list:
        """In-memory first, Notion as warm cache on cold start."""
        h = self._history.get(number)
        if h is not None:
            return h[-10:]
        # Cold start — try to load from Notion
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            h = loop.run_until_complete(
                self._load_history_from_notion(number)
            )
            loop.close()
            self._history[number] = h
            return h[-10:]
        except Exception:
            return []

    async def _load_history_from_notion(self, number: str) -> list:
        try:
            from integrations.notion_client import notion_client
            return await notion_client.load_sms_history(number)
        except Exception:
            return []

    def _update_history(self, number: str, user_msg: str, fred_msg: str) -> None:
        h = self._history.get(number, [])
        h.append({"role": "user", "content": user_msg})
        h.append({"role": "assistant", "content": fred_msg})
        self._history[number] = h[-20:]
        # Write-through to Notion in background
        import threading, asyncio
        def _save():
            try:
                loop = asyncio.new_event_loop()
                from integrations.notion_client import notion_client
                loop.run_until_complete(
                    notion_client.save_sms_history(number, h[-20:])
                )
                loop.close()
            except Exception:
                pass
        threading.Thread(target=_save, daemon=True).start()


    async def _midday(self) -> str:
        try:
            from alerts.midday_report import MidDayReportGenerator
            gen = MidDayReportGenerator()
            return await gen.generate_and_send(send=False)
        except Exception as e:
            logger.error(f"Midday error: {e}")
            return "Midday report failed. Try 'status' for positions."

    async def _gap_scan(self) -> str:
        try:
            from core.gap_scanner import gap_scanner
            from core.portfolio import portfolio_manager
            from core.mode_manager import mode_manager
            telegram_client.send(
                "🔍 Running gap scan...", to=""
            )
            balance = portfolio_manager.get_account_value()
            return await gap_scanner.scan_and_alert(balance, mode_manager.mode)
        except Exception as e:
            logger.error(f"Gap scan error: {e}")
            return "Gap scan failed mate. Try again."

    async def _trump_status(self) -> str:
        try:
            from integrations.truth_social_monitor import truth_social_monitor
            status = truth_social_monitor.get_status()
            last = status.get("last_post_seen", "Never")
            preview = status.get("last_post_preview", "None")
            running = "✅ Running" if status["running"] else "❌ Down"
            return (
                f"📱 SOCIAL MONITOR\n"
                f"Truth Social: {running}\n"
                f"Posts seen: {status['unique_posts_seen']}\n"
                f"Polls: {status['polls_completed']}\n"
                f"Last post: {last}\n"
                f"Preview: {preview}"
            )
        except Exception as e:
            return f"Couldn\'t get monitor status: {e}"

    async def _weights(self) -> str:
        try:
            from core.confidence import ConfidenceMeter
            meter = ConfidenceMeter()
            analysis = meter.get_weights_analysis()
            # If they want advice, get Claude's take
            if "advice" in analysis.lower():
                return analysis
            return analysis
        except Exception as e:
            return f"Weights analysis failed: {e}"

    def _is_buy(self, cmd: str) -> bool:
        return cmd.startswith(("buy ", "bought ", "long "))

    def _is_sell(self, cmd: str) -> bool:
        return cmd.startswith(("sell ", "sold ", "close ", "closed "))

    def _extract_ticker_from_sell(self, cmd: str) -> str:
        parts = cmd.split()
        skip = {"sell", "sold", "close", "closed", "my", "position", "in", "out", "of"}
        for p in parts[1:]:
            clean = re.sub(r'[^A-Za-z]', '', p).upper()
            if 1 <= len(clean) <= 5 and clean not in skip:
                return clean
        return ""

    def _is_stop_update(self, cmd: str) -> bool:
        return bool(re.match(r'(stop|update stop|set stop|move stop)\s+', cmd))

    def _extract_single_ticker(self, cmd: str) -> str:
        """Check if the message is just a ticker symbol."""
        clean = re.sub(r'[^A-Za-z]', '', cmd.strip()).upper()
        if 1 <= len(clean) <= 5 and clean.isalpha():
            # Exclude common words
            skip = {
                'HELP', 'SELL', 'SCAN', 'SYNC', 'RULES', 'ADD', 'BUY',
                'THE', 'AND', 'FOR', 'PDT', 'YES', 'NO', 'BRIEF',
            }
            if clean not in skip:
                return clean
        return ""


# Global singleton
sms_handler = SMSHandler()

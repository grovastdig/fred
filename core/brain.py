"""
core/brain.py
=============
Fred's intelligence layer. Async throughout — never blocks the server.

Uses anthropic.AsyncAnthropic so every Claude call is non-blocking.
Stop loss monitors, schedulers, and incoming SMS all run concurrently.

Also reads its own Notion notes before analysis — this is what makes
Fred smarter over time rather than approaching every ticker cold.
"""

import asyncio
import json
import logging
import re
import threading
from typing import Optional

import anthropic

from config.settings import settings
from config.trading_rules import (
    get_active_system_prompt,
    SCREENSHOT_TRADE_PLAN_PROMPT,
    FREDS_BRAIN_UPDATE_PROMPT,
    MORNING_BRIEF_PROMPT,
    EOD_DEBRIEF_PROMPT,
)

logger = logging.getLogger("fred.brain")


class FredBrain:
    """
    Fred's async reasoning core.
    All Claude API calls are non-blocking — server never freezes.
    Fred reads his own Notion notes before analysis — he remembers.
    """

    def __init__(self):
        # Async client — the fix for the blocking bug
        self.async_client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key
        )
        # Sync client for background threads only (note writing)
        self.sync_client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key
        )
        self.model = settings.anthropic_model
        self._conversation_history: list[dict] = []
        logger.info(f"FredBrain initialized (async) — model: {self.model}")

    def _get_system_prompt(self) -> str:
        """Fred's system prompt with current portfolio state injected."""
        try:
            from core.mode_manager import mode_manager
            context = mode_manager.get_mode_context_for_prompt()
            from config.trading_rules import get_system_prompt
            return get_system_prompt(mode_context=context)
        except Exception:
            from config.trading_rules import get_system_prompt
            return get_system_prompt()

    # ── Core async reasoning ──────────────────────────────────────────────────

    async def think(
        self,
        prompt: str,
        context: Optional[str] = None,
        max_tokens: int = 1500,
        use_history: bool = False,
    ) -> str:
        """
        Core async reasoning call. Never blocks the server.
        Injects current mode context automatically.
        """
        user_content = f"{context}\n\n---\n\n{prompt}" if context else prompt

        messages = (
            self._conversation_history + [{"role": "user", "content": user_content}]
            if use_history and self._conversation_history
            else [{"role": "user", "content": user_content}]
        )

        try:
            response = await self.async_client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=self._get_system_prompt(),
                messages=messages,
            )
            reply = response.content[0].text

            if use_history:
                self._conversation_history.append(
                    {"role": "user", "content": user_content}
                )
                self._conversation_history.append(
                    {"role": "assistant", "content": reply}
                )
                if len(self._conversation_history) > 20:
                    self._conversation_history = self._conversation_history[-20:]

            logger.debug(f"Brain response: {len(reply)} chars")
            return reply

        except anthropic.RateLimitError:
            logger.warning("Rate limited — waiting 5s and retrying")
            await asyncio.sleep(5)
            return await self.think(prompt, context, max_tokens, use_history)
        except Exception as e:
            logger.error(f"Brain.think error: {e}")
            return f"Something went wrong on my end mate. Try again. ({str(e)[:60]})"

    def reset_conversation(self):
        self._conversation_history = []

    # ── FIX #5: Read own notes before analysis ────────────────────────────────

    async def _fetch_brain_notes(self, ticker: str) -> str:
        """
        Fetch Fred's previous notes on this ticker from Notion.
        Injected into every analysis — Fred remembers what he's seen before.
        """
        try:
            from integrations.notion_client import notion_client
            notes = await notion_client.get_brain_notes_for_ticker(ticker)
            if not notes:
                return ""
            # Format last 5 notes for prompt injection
            note_lines = [f"- {n['text'][:150]}" for n in notes[-5:]]
            return "MY PREVIOUS NOTES ON THIS TICKER:\n" + "\n".join(note_lines)
        except Exception as e:
            logger.debug(f"Brain note fetch failed for {ticker}: {e}")
            return ""

    # ── Chart screenshot → trade plan ─────────────────────────────────────────

    async def analyze_chart_screenshot(
        self,
        image_base64: str,
        current_balance: float,
        open_positions: list,
    ) -> str:
        """
        Read a chart screenshot and return a complete trade plan.
        Fred picks the stop from chart structure.
        """
        try:
            from core.mode_manager import mode_manager
            mode = "builder"
            size_instruction = (
                f"Full port: ${current_balance * 0.95:.2f}"
"Position size: based on confidence score"
            )
        except Exception:
            mode = "builder"
            size_instruction = "Position size: based on confidence score"

        prompt = SCREENSHOT_TRADE_PLAN_PROMPT.format(
            mode=mode.upper(),
            balance=f"${current_balance:,.2f}",
            positions=", ".join(open_positions) if open_positions else "None",
            size_instruction=size_instruction,
        )

        try:
            response = await self.async_client.messages.create(
                model=self.model,
                max_tokens=800,
                system=self._get_system_prompt(),
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_base64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Chart analysis error: {e}")
            return (
                "Couldn't read the chart clearly mate. "
                "Try a cleaner screenshot or send me the ticker directly."
            )

    # ── Main setup analysis — reads brain notes first ─────────────────────────

    async def analyze_setup(
        self,
        ticker: str,
        technical_data: dict,
        news_context: str = "",
        portfolio_context: str = "",
        market_regime: str = "neutral",
    ) -> dict:
        """
        Full setup analysis. Reads previous brain notes before responding.
        Writes a new note after — Fred gets smarter with every analysis.
        """
        # Read previous notes on this ticker (Fix #5)
        brain_notes = await self._fetch_brain_notes(ticker)

        prompt = f"""Analyze this setup completely.

Ticker: {ticker}
Market regime: {market_regime}

Technical data:
{self._format_technical(technical_data)}

News/catalyst:
{news_context or "No specific news. Check for general sector catalyst."}

Open positions:
{portfolio_context or "No open positions."}

{brain_notes}

Provide a complete trade plan with entry, stop (from chart structure),
target, confidence score, position size, and thesis."""

        response = await self.think(prompt, max_tokens=700)

        # Write brain note in background — don't wait for it
        asyncio.create_task(
            self._write_brain_note_async(
                ticker=ticker,
                context=f"Analyzed {ticker} — {market_regime} regime. "
                        f"Response: {response[:200]}",
                note_type="analysis",
            )
        )

        return {"ticker": ticker, "analysis": response, "raw": response}

    async def analyze_social_post(
        self,
        account: str,
        post_text: str,
        timestamp: str,
        open_positions: list,
        watchlist: list,
        source: str = "twitter",
    ) -> dict:
        """Analyze a social/political post for market impact."""
        prompt = f"""Analyze this post for market impact.

Source: {source.upper()} | Account: @{account} | Time: {timestamp}
Post: "{post_text}"

Open positions: {', '.join(open_positions) if open_positions else 'None'}
Watchlist: {', '.join(watchlist[:10]) if watchlist else 'Standard universe'}

Respond:
IMPACT: HIGH / MEDIUM / LOW / NONE
SECTORS: [list]
AFFECTED TICKERS: [from positions/watchlist]
ACTION: SELL NOW / TIGHTEN STOP / WATCH / HOLD / NONE
URGENCY: IMMEDIATE / TODAY / THIS WEEK / MONITOR
REASON: [one sentence]"""

        response = await self.think(prompt, max_tokens=300)

        impact = "LOW"
        for level in ["HIGH", "MEDIUM", "LOW", "NONE"]:
            if level in response.upper():
                impact = level
                break

        urgency = "MONITOR"
        for u in ["IMMEDIATE", "TODAY", "THIS WEEK"]:
            if u in response.upper():
                urgency = u
                break

        return {
            "account": account,
            "impact": impact,
            "urgency": urgency,
            "analysis": response,
            "source": source,
        }

    async def answer_sms(
        self,
        message: str,
        conversation_history: list,
        portfolio_context: str,
        market_session: str,
        account_value: float,
    ) -> str:
        """Handle a natural language SMS with full conversation context."""
        context = (
            f"Current time: {market_session}\n"
            f"Account value: ${account_value:,.2f}\n"
            f"Portfolio: {portfolio_context}"
        )

        messages = list(conversation_history[-10:])
        messages.append({
            "role": "user",
            "content": f"{context}\n\nMessage: {message}"
        })

        try:
            response = await self.async_client.messages.create(
                model=self.model,
                max_tokens=500,
                system=self._get_system_prompt(),
                messages=messages,
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"SMS response error: {e}")
            return "Something went wrong. Try again."

    async def generate_morning_brief(self, context: dict) -> str:
        """Generate 8:30 AM morning brief."""
        try:
            from core.mode_manager import mode_manager
            challenge = (
                "Builder Mode — intelligent compounding."
                if False else ""
            )
            challenge_status = f"\nChallenge:\n{challenge}" if challenge else ""
            social_section = (
                "SOCIAL: [overnight social alerts]\n\n"
                if context.get("social_news") else ""
            )
        except Exception:
            challenge_status = ""
            social_section = ""

        prompt = MORNING_BRIEF_PROMPT.format(
            time=context.get("time", "8:30 AM"),
            mode=context.get("mode", "BUILDER").upper(),
            date=context.get("date", "Today"),
            futures=context.get("futures", "Checking..."),
            vix=context.get("vix", "N/A"),
            positions=context.get("positions", "None"),
            setups=context.get("setups", "Scanning..."),
            earnings=context.get("earnings", "None today"),
            events=context.get("events", "None today"),
            social_news=context.get("social_news", "Nothing overnight"),
            regime=context.get("regime", "Neutral"),
            challenge_status=challenge_status,
            social_section=social_section,
        )
        return await self.think(prompt, max_tokens=600)

    def generate_eod_debrief(self, context: dict) -> str:
        """
        Sync wrapper for EOD debrief (called from sync contexts).
        Uses asyncio.run if no event loop, otherwise schedules.
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule as task and return placeholder
                # Caller should await generate_eod_debrief_async instead
                return self._sync_think_fallback(context)
            else:
                return loop.run_until_complete(
                    self.generate_eod_debrief_async(context)
                )
        except Exception:
            return self._sync_think_fallback(context)

    async def generate_eod_debrief_async(self, context: dict) -> str:
        """Async EOD debrief generation."""
        try:
            from core.mode_manager import mode_manager
            challenge = (
                "Builder Mode — intelligent compounding."
                if False else ""
            )
            challenge_status = f"\nChallenge:\n{challenge}" if challenge else ""
        except Exception:
            challenge_status = ""

        closed = context.get("closed_today")
        closed_section = (
            f"CLOSED TODAY: {closed}\n\n" if closed else ""
        )

        prompt = EOD_DEBRIEF_PROMPT.format(
            date=context.get("date", "Today"),
            mode=context.get("mode", "BUILDER").upper(),
            positions=context.get("positions", "None"),
            closed_today=context.get("closed_today", "None"),
            day_pnl=context.get("day_pnl", "$0.00"),
            challenge_status=challenge_status,
            closed_section=closed_section,
        )
        return await self.think(prompt, max_tokens=500)

    def _sync_think_fallback(self, context: dict) -> str:
        """Fallback sync debrief using sync client — only when async unavailable."""
        try:
            system = self._get_system_prompt()
            prompt = f"Generate a brief EOD summary. Positions: {context.get('positions','None')}. P&L: {context.get('day_pnl','?')}."
            resp = self.sync_client.messages.create(
                model=self.model,
                max_tokens=400,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text
        except Exception as e:
            return f"EOD debrief failed: {e}"

    # ── Fred's Brain writer (async) ───────────────────────────────────────────

    async def _write_brain_note_async(
        self, ticker: str, context: str, note_type: str = "analysis"
    ) -> None:
        """Write a note to Fred's Brain in Notion. Async, non-blocking."""
        try:
            prompt = FREDS_BRAIN_UPDATE_PROMPT.format(context=context)
            response = await self.async_client.messages.create(
                model=self.model,
                max_tokens=200,
                system=self._get_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
            )
            note = response.content[0].text

            from integrations.notion_client import notion_client
            await notion_client.write_brain_note(
                ticker=ticker, note=note, note_type=note_type
            )
            logger.debug(f"Brain note written: {ticker}")
        except Exception as e:
            logger.debug(f"Brain note write error for {ticker}: {e}")

    def write_brain_note(self, context: str) -> str:
        """Sync wrapper for background thread use only."""
        try:
            prompt = FREDS_BRAIN_UPDATE_PROMPT.format(context=context)
            resp = self.sync_client.messages.create(
                model=self.model,
                max_tokens=200,
                system=self._get_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text
        except Exception as e:
            logger.debug(f"Brain note sync write error: {e}")
            return f"[Note failed: {e}]"

    def _async_write_brain_note(self, context: str, ticker: str) -> None:
        """Called from background threads — creates its own event loop."""
        try:
            note = self.write_brain_note(context)
            from integrations.notion_client import notion_client
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                notion_client.write_brain_note(
                    ticker=ticker, note=note, note_type="analysis"
                )
            )
            loop.close()
        except Exception as e:
            logger.debug(f"Async brain note thread error: {e}")

    async def score_discovery_setup(
        self, ticker: str, reason: str, technical_data: dict
    ) -> dict:
        """Quick score a discovery hit. Fast and cheap."""
        prompt = (
            f"Quick take on {ticker}. Discovery: {reason}. "
            f"RSI: {technical_data.get('rsi','?')} | "
            f"Price vs 20 EMA: {'above' if technical_data.get('price_above_ema_20') else 'below'} | "
            f"Volume: {technical_data.get('volume_ratio',0):.1f}x avg. "
            f"Worth a full analysis? Score 0-100 and one line.\n"
            f"Format: SCORE: XX — [reason]"
        )
        response = await self.think(prompt, max_tokens=80)
        score = 50
        match = re.search(r"SCORE:\s*(\d+)", response, re.IGNORECASE)
        if match:
            score = int(match.group(1))
        return {"ticker": ticker, "quick_score": score, "take": response}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _format_technical(self, data: dict) -> str:
        if not data:
            return "No technical data available"
        lines = []
        fields = [
            ("price", "Price", "${:.2f}"),
            ("ema_20", "20 EMA", "${:.2f}"),
            ("ema_50", "50 EMA", "${:.2f}"),
            ("rsi", "RSI", "{:.1f}"),
            ("macd", "MACD", "{:.3f}"),
            ("volume_ratio", "Volume", "{:.1f}x avg"),
            ("atr", "ATR", "{:.2f}"),
            ("bb_squeeze", "BB Squeeze", "{}"),
        ]
        for key, label, fmt in fields:
            val = data.get(key)
            if val is not None:
                try:
                    lines.append(f"  {label}: {fmt.format(val)}")
                except Exception:
                    lines.append(f"  {label}: {val}")
        signals = data.get("signals", [])
        if signals:
            lines.append(f"  Signals: {', '.join(signals[:5])}")
        return "\n".join(lines) if lines else "No data"

    def _parse_json(self, text: str, context: str = "") -> dict:
        try:
            clean = re.sub(r"```json|```", "", text).strip()
            return json.loads(clean)
        except Exception:
            return {"raw": text}


# Global singleton
fred_brain = FredBrain()

"""
alerts/midday_report.py
========================
Fred's 12pm midday update.

Three things you need at noon:
1. How your positions are doing right now
2. What setups have appeared since this morning
3. Any news or social activity worth knowing about

Concise. Actionable. Phone-readable.
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger("fred.midday_report")


class MidDayReportGenerator:
    """Generates the 12pm midday update."""

    async def generate_and_send(self, send: bool = True) -> str:
        """Build and optionally send the midday report."""
        from core.portfolio import portfolio_manager
        from core.market import market_data
        from core.scanner import market_scanner
        from core.mode_manager import mode_manager
        from core.brain import fred_brain
        from integrations.telegram_client import telegram_client

        try:
            # Refresh prices first
            await portfolio_manager.refresh_prices()
        except Exception as e:
            logger.warning(f"Price refresh failed: {e}")

        # ── Positions current status ─────────────────────────────────────────
        positions = list(portfolio_manager._positions.values())
        position_lines = []
        total_pnl = 0.0

        for pos in positions:
            pnl = pos.pnl_dollars
            total_pnl += pnl
            status = "✅" if pnl > 0 else "🔴" if pos.stop_is_near else "📊"
            position_lines.append(
                f"{status} {pos.ticker}: {'+' if pnl >= 0 else ''}"
                f"${pnl:.0f} ({pos.pnl_pct:+.1f}%)"
            )

        positions_str = "\n".join(position_lines) if position_lines else "No open positions."

        # ── Market pulse ─────────────────────────────────────────────────────
        try:
            regime = market_data.get_market_regime()
            spy = market_data.get_snapshot("SPY")
            qqq = market_data.get_snapshot("QQQ")
            spy_pct = spy.get("change_pct", 0)
            qqq_pct = qqq.get("change_pct", 0)
            market_pulse = (
                f"SPY {spy_pct:+.1f}% | QQQ {qqq_pct:+.1f}% | "
                f"Regime: {regime.get('regime','?').title()}"
            )
        except Exception:
            market_pulse = "Market data unavailable"

        # ── Best setups found since morning ──────────────────────────────────
        try:
            setups_text = market_scanner.scan_to_sms(max_results=2)
        except Exception:
            setups_text = "Scan unavailable."

        # ── Mode context ─────────────────────────────────────────────────────
        pdt_warn = mode_manager.pdt_warning or ""
        challenge_line = ""
        if False:
            state = mode_manager._state
            pct = (state.current_balance / 10000) * 100
            challenge_line = (
                f"Challenge: ${state.current_balance:,.2f} "
                f"({pct:.1f}% to target)"
            )

        # ── Build prompt for Fred ─────────────────────────────────────────────
        context = {
            "time": "12:00 PM",
            "date": datetime.now().strftime("%A, %b %d"),
            "market_pulse": market_pulse,
            "positions": positions_str,
            "total_pnl": f"${total_pnl:+.2f}" if positions else "N/A",
            "setups": setups_text[:300],
            "pdt_warn": pdt_warn,
            "challenge_line": challenge_line,
            "mode": "builder".upper(),
        }

        prompt = f"""Generate Fred's midday update for {context['date']} at noon.

Mode: {context['mode']}
Market: {context['market_pulse']}
Open positions P&L: {context['total_pnl']}
Positions detail: {context['positions']}
Top setups found since morning: {context['setups']}
{f"PDT: {context['pdt_warn']}" if context['pdt_warn'] else ""}
{context['challenge_line']}

Write a tight midday check-in in Fred's voice.
Structure:
FRED — NOON

MARKET: [one line — how today is tracking]

YOUR BOOK: [each position: ticker, P&L, one word status]

SETUPS: [top 1-2 only. If nothing new since morning, say so.]

AFTERNOON: [one specific thing to watch for this afternoon]

Under 15 lines. Direct. No fluff."""

        try:
            report = await fred_brain.think(prompt, max_tokens=400)
        except Exception as e:
            logger.error(f"Midday report generation failed: {e}")
            report = self._fallback_report(context)

        if send:
            try:
                telegram_client.send(report, alert_key="midday_report")
                logger.info("Midday report sent")
            except Exception as e:
                logger.error(f"Midday report send failed: {e}")

        return report

    def _fallback_report(self, context: dict) -> str:
        """Plain text fallback if Claude call fails."""
        return (
            f"FRED — NOON\n"
            f"Market: {context['market_pulse']}\n"
            f"\nPositions:\n{context['positions']}\n"
            f"\nTotal P&L: {context['total_pnl']}\n"
            f"\n{context.get('challenge_line', '')}"
        ).strip()

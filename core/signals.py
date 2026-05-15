"""
core/signals.py
===============
Entry and exit signal engine.

This is the rules engine that mechanically evaluates
whether all conditions are met for entries and exits.

The brain (Claude) provides reasoning and judgment.
The signal engine provides mechanical rule enforcement.
Together they create Fred's edge.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
import logging as _logging; logger = _logging.getLogger(__name__)

from core.confidence import ConfidenceMeter, ConfidenceScore
from config.trading_rules import ENTRY_RULES, EXIT_RULES, SAFETY_RULES


@dataclass
class EntrySignal:
    """Result of an entry signal evaluation."""
    ticker: str
    timestamp: datetime = field(default_factory=datetime.now)

    # Gate checks — ALL must pass for entry
    trend_confirmed: bool = False        # Price above 20 EMA
    rsi_in_range: bool = False           # RSI 40-65
    macd_bullish: bool = False           # MACD bullish crossover or expanding
    volume_confirmed: bool = False       # Volume above average
    catalyst_present: bool = False       # News/earnings/political catalyst
    rr_ratio_valid: bool = False         # Minimum 2:1 R:R
    confidence_sufficient: bool = False  # Score >= 50

    # Confidence score
    confidence: Optional[ConfidenceScore] = None

    # Signal metadata
    suggested_entry: float = 0.0
    suggested_stop: float = 0.0
    suggested_target: float = 0.0
    catalyst_description: str = ""
    fail_reasons: list = field(default_factory=list)

    @property
    def all_clear(self) -> bool:
        """True only when ALL entry gates pass."""
        return all([
            self.trend_confirmed,
            self.rsi_in_range,
            self.macd_bullish,
            self.volume_confirmed,
            self.catalyst_present,
            self.rr_ratio_valid,
            self.confidence_sufficient,
        ])

    @property
    def gates_passed(self) -> int:
        """Count of entry gates passed (out of 7)."""
        gates = [
            self.trend_confirmed, self.rsi_in_range, self.macd_bullish,
            self.volume_confirmed, self.catalyst_present,
            self.rr_ratio_valid, self.confidence_sufficient,
        ]
        return sum(gates)

    def summary_str(self) -> str:
        """SMS-ready summary."""
        status = "✅ ENTRY SIGNAL" if self.all_clear else "👀 WATCHING"
        score = self.confidence.total if self.confidence else 0
        label = self.confidence.label if self.confidence else "N/A"
        size = self.confidence.position_size_pct if self.confidence else 0

        lines = [
            f"{status}: {self.ticker}",
            f"Score: {score:.0f}/100 — {label}",
            f"Size: {size:.0f}% of portfolio",
            f"Entry: ${self.suggested_entry:.2f}",
            f"Stop: ${self.suggested_stop:.2f}",
            f"Target: ${self.suggested_target:.2f}",
            f"Gates: {self.gates_passed}/7",
        ]

        if self.fail_reasons:
            lines.append("Missing: " + " | ".join(self.fail_reasons))

        return "\n".join(lines)


@dataclass
class ExitSignal:
    """Result of an exit signal evaluation for an open position."""
    ticker: str
    position_id: str
    timestamp: datetime = field(default_factory=datetime.now)

    # Exit triggers
    stop_loss_hit: bool = False
    stop_approaching: bool = False
    target_reached: bool = False
    rsi_overbought: bool = False
    macd_reversal: bool = False
    thesis_broken: bool = False
    volume_drying: bool = False

    # Severity
    urgency: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL
    action: str = "HOLD"  # HOLD, TIGHTEN_STOP, TAKE_PROFITS, EXIT

    # Context
    current_price: float = 0.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target: float = 0.0
    pnl_pct: float = 0.0
    message: str = ""

    @property
    def any_trigger(self) -> bool:
        return any([
            self.stop_loss_hit, self.target_reached, self.rsi_overbought,
            self.macd_reversal, self.thesis_broken,
        ])

    def alert_str(self) -> str:
        """SMS-ready alert string."""
        emoji = {
            "CRITICAL": "🚨",
            "HIGH": "⚠️",
            "MEDIUM": "👀",
            "LOW": "ℹ️",
        }.get(self.urgency, "ℹ️")

        return (
            f"{emoji} {self.ticker} — {self.action}\n"
            f"Price: ${self.current_price:.2f} ({self.pnl_pct:+.1f}%)\n"
            f"Stop: ${self.stop_loss:.2f} | Target: ${self.target:.2f}\n"
            f"{self.message}"
        )


class SignalEngine:
    """
    Mechanically evaluates entry and exit signals.
    Works alongside the brain to enforce trading rules.
    """

    def __init__(self):
        self.confidence_meter = ConfidenceMeter()

    # ── Entry Signals ────────────────────────────────────────────────────────

    def evaluate_entry(
        self,
        ticker: str,
        snapshot: dict,
        catalyst: Optional[dict] = None,
        sector_data: Optional[dict] = None,
        market_regime: Optional[dict] = None,
        political_signal: Optional[dict] = None,
        manual_stop: Optional[float] = None,
        manual_target: Optional[float] = None,
    ) -> EntrySignal:
        """
        Evaluate all entry conditions for a ticker.
        Returns EntrySignal with full gate breakdown.
        """
        signal = EntrySignal(ticker=ticker)

        price = snapshot.get("price", 0)
        ema_20 = snapshot.get("ema_20", 0)
        rsi = snapshot.get("rsi", 50)
        atr = snapshot.get("atr", price * 0.02)

        # Calculate suggested prices
        stop = manual_stop or (price - (atr * 1.5))
        target = manual_target or (price + (atr * 3.0))  # Default 2:1 R:R target

        signal.suggested_entry = price
        signal.suggested_stop = round(stop, 2)
        signal.suggested_target = round(target, 2)

        # ── Gate 1: Trend (Price above 20 EMA) ──
        if ema_20 and price > ema_20:
            signal.trend_confirmed = True
        else:
            signal.fail_reasons.append("trend(EMA20)")

        # ── Gate 2: RSI in entry range ──
        if 40 <= rsi <= 65:
            signal.rsi_in_range = True
        else:
            signal.fail_reasons.append(f"RSI({rsi:.0f})")

        # ── Gate 3: MACD bullish ──
        macd_crossover = snapshot.get("macd_bullish_crossover", False)
        macd_expanding = snapshot.get("macd_hist_expanding", False) and snapshot.get("macd_hist_positive", False)
        macd_above = snapshot.get("macd_above_signal", False)

        if macd_crossover or (macd_expanding and macd_above):
            signal.macd_bullish = True
        elif macd_above:
            signal.macd_bullish = True  # Partial — MACD above signal is acceptable
        else:
            signal.fail_reasons.append("MACD")

        # ── Gate 4: Volume confirmed ──
        vol_ratio = snapshot.get("volume_ratio", 0)
        if vol_ratio >= 1.0:
            signal.volume_confirmed = True
        else:
            signal.fail_reasons.append(f"volume({vol_ratio:.1f}x)")

        # ── Gate 5: Catalyst present ──
        if catalyst and catalyst.get("type") != "unknown":
            signal.catalyst_present = True
            signal.catalyst_description = catalyst.get("description", "")
        else:
            signal.fail_reasons.append("catalyst")

        # ── Gate 6: Risk/Reward ratio ──
        risk = price - stop
        reward = target - price
        rr_ratio = reward / risk if risk > 0 else 0

        if rr_ratio >= 2.0:
            signal.rr_ratio_valid = True
        else:
            signal.fail_reasons.append(f"R:R({rr_ratio:.1f})")

        # ── Gate 7: Confidence score ──
        signal.confidence = self.confidence_meter.score(
            ticker=ticker,
            technical_data=snapshot,
            catalyst=catalyst,
            sector_data=sector_data,
            market_regime=market_regime,
            entry_price=price,
            stop_loss=stop,
            target_price=target,
            political_signal=political_signal,
        )

        if signal.confidence.total >= 50:
            signal.confidence_sufficient = True
        else:
            signal.fail_reasons.append(f"confidence({signal.confidence.total:.0f})")

        # Catalyst override — political and earnings gaps bypass volume gate
        signal = self._check_catalyst_override(signal, snapshot, catalyst, political_signal)

        logger.info(
            f"Entry eval {ticker}: {signal.gates_passed}/7 gates, "
            f"score={signal.confidence.total:.0f}, all_clear={signal.all_clear}"
        )
        return signal


    def _check_catalyst_override(
        self,
        signal,
        snapshot: dict,
        catalyst: dict,
        political_signal: dict,
    ):
        """
        Catalyst override: exceptional catalysts bypass the volume gate.

        Standard entries wait for volume confirmation — correct for normal setups.
        But for Trump posts and earnings gaps, volume comes AFTER the catalyst.
        Waiting for it means missing the move.

        Override conditions (ANY of these):
        1. Trump/Truth Social post with direct ticker mention
        2. Gap play 25%+ with earnings catalyst
        3. FDA approval / M&A / binary catalyst
        """
        try:
            from core.mode_manager import mode_manager
            if True:  # Builder Mode only — override always disabled
                return signal
        except Exception:
            return signal

        catalyst_type = catalyst.get("type", "") if catalyst else ""
        override_triggered = False
        override_reason = ""

        # Condition 1: Direct political mention
        if political_signal:
            acct = political_signal.get("account", "").lower()
            in_affected = signal.ticker in political_signal.get("affected_tickers", [])
            src = political_signal.get("source", "").lower()
            if acct in ["realdonaldtrump", "trump"] and (in_affected or src == "truth_social"):
                override_triggered = True
                override_reason = "Trump direct mention — volume gate bypassed"

        # Condition 2: Strong earnings gap
        if catalyst_type in ("earnings_beat", "earnings_surprise", "earnings_gap"):
            gap = snapshot.get("gap_pct", 0) or snapshot.get("change_pct", 0)
            if abs(gap) >= 25:
                override_triggered = True
                override_reason = f"Earnings gap {gap:+.1f}% — volume gate bypassed"

        # Condition 3: High-conviction binary catalyst
        if catalyst_type in ("fda_approval", "merger", "acquisition", "contract_win"):
            override_triggered = True
            override_reason = f"{catalyst_type} — volume gate bypassed"

        if override_triggered and not signal.volume_confirmed:
            signal.volume_confirmed = True
            signal.fail_reasons = [
                r for r in signal.fail_reasons if "volume" not in r.lower()
            ]
            signal.fail_reasons.append(f"⚡ CATALYST OVERRIDE: {override_reason}")
            logger.info(
                f"Catalyst override applied for {signal.ticker}: {override_reason}"
            )

        return signal

    # ── Exit Signals ─────────────────────────────────────────────────────────

    def evaluate_exit(
        self,
        position: dict,
        snapshot: dict,
        news_context: Optional[str] = None,
    ) -> ExitSignal:
        """
        Check all exit conditions for an open position.
        Returns ExitSignal with urgency and recommended action.
        """
        ticker = position.get("ticker", "UNKNOWN")
        position_id = position.get("id", ticker)
        entry_price = position.get("entry_price", 0)
        stop_loss = position.get("stop_loss", 0)
        target = position.get("target", 0)
        shares = position.get("shares", 0)

        current_price = snapshot.get("price", entry_price)
        rsi = snapshot.get("rsi", 50)

        pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price else 0
        pct_to_stop = ((current_price - stop_loss) / current_price * 100) if (stop_loss and current_price) else 100

        signal = ExitSignal(
            ticker=ticker,
            position_id=position_id,
            current_price=current_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            pnl_pct=pnl_pct,
        )

        messages = []

        # ── CRITICAL: Stop loss hit ──
        if stop_loss and current_price <= stop_loss:
            signal.stop_loss_hit = True
            signal.urgency = "CRITICAL"
            signal.action = "EXIT"
            messages.append(f"Stop loss hit at ${stop_loss:.2f}. Exit immediately — no exceptions.")

        # ── HIGH: Stop approaching ──
        elif stop_loss and pct_to_stop <= 1.5:
            signal.stop_approaching = True
            signal.urgency = "HIGH"
            signal.action = "TIGHTEN_STOP"
            messages.append(f"Only {pct_to_stop:.1f}% from stop loss. Consider tightening.")

        elif stop_loss and pct_to_stop <= 3.0:
            signal.stop_approaching = True
            signal.urgency = "MEDIUM"
            messages.append(f"{pct_to_stop:.1f}% from stop. Keep watching.")

        # ── HIGH: Target reached ──
        if target and current_price >= target:
            signal.target_reached = True
            if signal.urgency not in ["CRITICAL"]:
                signal.urgency = "HIGH"
                signal.action = "TAKE_PROFITS"
            messages.append(f"Target ${target:.2f} reached! Lock profits or trail stop.")

        # ── HIGH: RSI overbought ──
        if rsi > 75:
            signal.rsi_overbought = True
            if signal.urgency not in ["CRITICAL", "HIGH"]:
                signal.urgency = "HIGH"
                signal.action = "TAKE_PROFITS"
            messages.append(f"RSI at {rsi:.0f} — overbought. Consider taking profits.")

        # ── HIGH: MACD reversal ──
        if snapshot.get("macd_bearish_crossover"):
            signal.macd_reversal = True
            if signal.urgency not in ["CRITICAL", "HIGH"]:
                signal.urgency = "MEDIUM"
                signal.action = "TIGHTEN_STOP"
            messages.append("MACD bearish crossover — momentum shifting. Tighten stop.")

        # ── MEDIUM: Thesis broken by news ──
        if news_context and self._news_breaks_thesis(news_context, position):
            signal.thesis_broken = True
            signal.urgency = "HIGH"
            signal.action = "EXIT"
            messages.append("Breaking news may invalidate trade thesis. Review immediately.")

        # ── LOW: Volume drying up ──
        if snapshot.get("volume_drying"):
            signal.volume_drying = True
            if signal.action == "HOLD":
                signal.action = "TIGHTEN_STOP"
            messages.append("Volume drying up — distribution signal. Tighten stop.")

        # Final action and message
        if not signal.any_trigger and not signal.stop_approaching:
            signal.action = "HOLD"
            signal.urgency = "LOW"
            pnl_str = f"+{pnl_pct:.1f}%" if pnl_pct >= 0 else f"{pnl_pct:.1f}%"
            messages.append(f"Position healthy at {pnl_str}. Thesis intact.")

        signal.message = " ".join(messages)

        logger.debug(
            f"Exit eval {ticker}: urgency={signal.urgency}, "
            f"action={signal.action}, P&L={pnl_pct:.1f}%"
        )
        return signal

    # ── Watchlist Evaluation ──────────────────────────────────────────────────

    def screen_watchlist(
        self,
        watchlist: list[dict],
        snapshots: dict[str, dict],
        market_regime: Optional[dict] = None,
    ) -> list[EntrySignal]:
        """
        Screen all watchlist stocks for entry signals.
        Returns list of signals, sorted by confidence score.
        """
        signals = []

        for item in watchlist:
            ticker = item.get("ticker")
            if not ticker or ticker not in snapshots:
                continue

            snapshot = snapshots[ticker]
            if "error" in snapshot:
                continue

            # Build catalyst from watchlist thesis
            catalyst = {
                "type": item.get("catalyst_type", "technical_only"),
                "description": item.get("thesis", ""),
                "impact": item.get("expected_impact", "medium"),
            }

            signal = self.evaluate_entry(
                ticker=ticker,
                snapshot=snapshot,
                catalyst=catalyst,
                market_regime=market_regime,
                manual_stop=item.get("stop_loss"),
                manual_target=item.get("target"),
            )

            signals.append(signal)

        # Sort by confidence score descending
        signals.sort(
            key=lambda s: s.confidence.total if s.confidence else 0,
            reverse=True,
        )

        actionable = [s for s in signals if s.all_clear]
        logger.info(
            f"Watchlist screen: {len(actionable)} actionable of {len(signals)} total"
        )
        return signals

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _news_breaks_thesis(self, news_context: str, position: dict) -> bool:
        """
        Simple heuristic to detect news that might break a trade thesis.
        The brain does the real analysis — this is a quick pre-filter.
        """
        thesis = position.get("thesis", "").lower()
        news_lower = news_context.lower()

        # Key bearish signals that commonly break theses
        bearish_signals = [
            "earnings miss", "revenue miss", "guidance cut", "lowered guidance",
            "recall", "investigation", "fraud", "sec charges", "going private",
            "bankruptcy", "layoffs massive", "ceo resign", "data breach",
        ]

        for signal in bearish_signals:
            if signal in news_lower:
                return True

        return False


# Global singleton
signal_engine = SignalEngine()

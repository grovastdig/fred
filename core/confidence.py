"""
core/confidence.py
==================
The Confidence Meter — Fred's trade scoring system.

Every potential trade gets scored 0-100 before entry.
Score determines position size. Below 50 = skip.

Scoring breakdown (total 100 points):
- Technical setup quality:  25pts
- Volume confirmation:      15pts
- Catalyst strength:        20pts
- Sector strength:          10pts
- Market regime:            10pts
- Risk/reward ratio:        10pts
- Political tailwind:       10pts
"""

from dataclasses import dataclass, field
from typing import Optional
import logging as _logging; logger = _logging.getLogger(__name__)

from config.trading_rules import POSITION_SIZING, CONFIDENCE_WEIGHTS


@dataclass
class ConfidenceScore:
    """
    Full breakdown of a trade's confidence score.
    """
    ticker: str

    # Component scores
    technical_setup: float = 0      # 0-25
    volume_confirmation: float = 0  # 0-15
    catalyst_strength: float = 0    # 0-20
    sector_strength: float = 0      # 0-10
    market_regime: float = 0        # 0-10
    risk_reward_ratio: float = 0    # 0-10
    political_tailwind: float = 0   # 0-10

    # Metadata
    catalyst_description: str = ""
    political_context: str = ""
    regime: str = "unknown"
    rr_ratio: float = 0.0
    warnings: list = field(default_factory=list)

    @property
    def total(self) -> float:
        return (
            self.technical_setup
            + self.volume_confirmation
            + self.catalyst_strength
            + self.sector_strength
            + self.market_regime
            + self.risk_reward_ratio
            + self.political_tailwind
        )

    @property
    def label(self) -> str:
        score = self.total
        if score >= 90:
            return "🔥 Conviction"
        elif score >= 70:
            return "✅ Strong"
        elif score >= 50:
            return "👀 Moderate"
        else:
            return "❌ Skip"

    @property
    def position_size_pct(self) -> float:
        score = self.total
        if score >= 90:
            return POSITION_SIZING["conviction"]["max_pct"]
        elif score >= 80:
            mid = (
                POSITION_SIZING["conviction"]["min_pct"]
                + POSITION_SIZING["conviction"]["max_pct"]
            ) / 2
            return mid
        elif score >= 70:
            return POSITION_SIZING["strong"]["max_pct"]
        elif score >= 60:
            mid = (
                POSITION_SIZING["strong"]["min_pct"]
                + POSITION_SIZING["strong"]["max_pct"]
            ) / 2
            return mid
        elif score >= 50:
            return POSITION_SIZING["moderate"]["max_pct"]
        else:
            return 0.0

    @property
    def should_trade(self) -> bool:
        return self.total >= 50

    def breakdown_str(self) -> str:
        """Human-readable score breakdown for SMS."""
        return (
            f"📊 {self.ticker} Confidence: {self.total:.0f}/100 — {self.label}\n"
            f"Technical: {self.technical_setup:.0f}/25\n"
            f"Volume: {self.volume_confirmation:.0f}/15\n"
            f"Catalyst: {self.catalyst_strength:.0f}/20\n"
            f"Sector: {self.sector_strength:.0f}/10\n"
            f"Regime: {self.market_regime:.0f}/10\n"
            f"R:R: {self.risk_reward_ratio:.0f}/10\n"
            f"Political: {self.political_tailwind:.0f}/10\n"
            f"Position Size: {self.position_size_pct:.0f}% of portfolio"
        )


    def to_sms(self) -> str:
        """Compact SMS version of score."""
        return self.breakdown_str()

    @property
    def position_size_label(self) -> str:
        """Human-readable position size label."""
        pct = self.position_size_pct
        if pct == 0:
            return "0% — Skip"
        return f"{pct:.0f}% of portfolio"


class ConfidenceMeter:
    """
    Scores trade setups 0-100 based on technical, fundamental,
    and macro factors. The higher the score, the bigger we size.
    """

    def score(
        self,
        ticker: str,
        technical_data: dict,
        catalyst: Optional[dict] = None,
        sector_data: Optional[dict] = None,
        market_regime: Optional[dict] = None,
        entry_price: float = 0,
        stop_loss: float = 0,
        target_price: float = 0,
        political_signal: Optional[dict] = None,
    ) -> ConfidenceScore:
        """
        Score a trade setup. Returns a ConfidenceScore with full breakdown.
        """
        result = ConfidenceScore(ticker=ticker)

        # 1. Technical Setup (0-25)
        result.technical_setup = self._score_technical(technical_data, result)

        # 2. Volume Confirmation (0-15)
        result.volume_confirmation = self._score_volume(technical_data)

        # 3. Catalyst Strength (0-20)
        if catalyst:
            result.catalyst_strength, result.catalyst_description = self._score_catalyst(catalyst)
        else:
            result.catalyst_strength = 5  # Partial credit — scan may have found something
            result.catalyst_description = "No specific catalyst identified"

        # 4. Sector Strength (0-10)
        if sector_data:
            result.sector_strength = self._score_sector(sector_data, ticker)

        # 5. Market Regime (0-10)
        if market_regime:
            result.market_regime, result.regime = self._score_regime(market_regime)
        else:
            result.market_regime = 5  # Neutral
            result.regime = "unknown"

        # 6. Risk/Reward Ratio (0-10)
        if entry_price and stop_loss and target_price:
            result.risk_reward_ratio, result.rr_ratio = self._score_risk_reward(
                entry_price, stop_loss, target_price
            )

        # 7. Political Tailwind (0-10)
        if political_signal:
            result.political_tailwind, result.political_context = self._score_political(
                political_signal, ticker
            )

        # Add warnings for critical issues
        self._add_warnings(result, technical_data)

        logger.debug(
            f"Confidence score for {ticker}: {result.total:.1f}/100 ({result.label})"
        )
        return result

    # ── Component Scorers ────────────────────────────────────────────────────

    def _score_technical(self, data: dict, result: ConfidenceScore) -> float:
        """
        Score technical setup quality. Max 25 points.

        Scoring breakdown:
        - Price above 20 EMA:            +5
        - RSI in 40-65 range:            +5
        - MACD bullish crossover:        +5
        - MACD histogram expanding:      +3 (bonus)
        - EMA trending up (slope > 0):   +3
        - Bullish divergence:            +4 (bonus)
        - Golden cross:                  +2 (bonus)
        - Squeeze setup:                 +3 (bonus)
        """
        score = 0.0

        # Price above 20 EMA — non-negotiable trend check (+5)
        if data.get("price_above_ema_20"):
            score += 5
        else:
            result.warnings.append("⚠️ Price below 20 EMA — trend not confirmed")

        # RSI in optimal entry range (+5)
        rsi = data.get("rsi", 50)
        if 40 <= rsi <= 65:
            score += 5
        elif 35 <= rsi <= 70:
            score += 3
            result.warnings.append(f"⚠️ RSI {rsi:.0f} slightly outside optimal range")
        else:
            result.warnings.append(f"❌ RSI {rsi:.0f} outside entry range (40-65)")

        # MACD bullish crossover (+5)
        if data.get("macd_bullish_crossover"):
            score += 5
        elif data.get("macd_above_signal"):
            score += 3

        # MACD histogram expanding bonus (+3)
        if data.get("macd_hist_expanding") and data.get("macd_hist_positive"):
            score += 3

        # EMA slope trending up (+3)
        if data.get("ema_20_trending_up"):
            score += 3

        # RSI bullish divergence — high value signal (+4)
        if data.get("rsi_bullish_divergence"):
            score += 4

        # Golden cross bonus (+2)
        if data.get("golden_cross"):
            score += 2

        # Bollinger squeeze — explosive move imminent (+3)
        if data.get("bb_squeeze"):
            score += 3

        return min(score, 25)  # Cap at max

    def _score_volume(self, data: dict) -> float:
        """
        Score volume confirmation. Max 15 points.
        No volume = no conviction = no trade.
        """
        vol_ratio = data.get("volume_ratio", 1.0)

        if vol_ratio >= 3.0:
            return 15.0  # Massive volume — institutions moving
        elif vol_ratio >= 2.0:
            return 12.0  # Strong volume spike
        elif vol_ratio >= 1.5:
            return 10.0  # Good volume
        elif vol_ratio >= 1.0:
            return 7.0   # Average — acceptable
        elif vol_ratio >= 0.7:
            return 3.0   # Below average — weak
        else:
            return 0.0   # Volume drying up — skip

    def _score_catalyst(self, catalyst: dict) -> tuple[float, str]:
        """
        Score catalyst quality. Max 20 points.
        Catalyst is REQUIRED for high-conviction trades.
        """
        catalyst_type = catalyst.get("type", "unknown")
        catalyst_desc = catalyst.get("description", "Unknown catalyst")
        impact = catalyst.get("impact", "medium").lower()

        base_scores = {
            "earnings_beat": 18,
            "earnings_surprise": 15,
            "political_trump": 20,      # Trump post = max political alpha
            "political_social": 17,     # Other high-impact social
            "fda_approval": 19,
            "merger_acquisition": 16,
            "contract_win": 15,
            "analyst_upgrade": 12,
            "breakout_52w_high": 13,
            "sector_rotation": 11,
            "macro_data": 10,
            "technical_only": 5,        # No external catalyst
            "unknown": 5,
        }

        impact_multiplier = {"critical": 1.0, "high": 0.9, "medium": 0.75, "low": 0.5}.get(impact, 0.75)

        base = base_scores.get(catalyst_type, 8)
        score = base * impact_multiplier

        return round(min(score, 20), 1), catalyst_desc

    def _score_sector(self, sector_data: dict, ticker: str) -> float:
        """
        Score sector strength. Max 10 points.
        Trading with sector momentum = safer bet.
        """
        sector_pct = sector_data.get("change_pct_today", 0)
        sector_rank = sector_data.get("rank", 6)  # 1=best, 11=worst

        # Sector performance today
        if sector_pct > 2.0:
            perf_score = 5.0
        elif sector_pct > 1.0:
            perf_score = 4.0
        elif sector_pct > 0:
            perf_score = 3.0
        elif sector_pct > -1.0:
            perf_score = 2.0
        else:
            perf_score = 0.5

        # Sector rank bonus
        if sector_rank <= 3:
            rank_score = 5.0
        elif sector_rank <= 5:
            rank_score = 3.0
        elif sector_rank <= 8:
            rank_score = 2.0
        else:
            rank_score = 0.5

        return min(perf_score + rank_score, 10)

    def _score_regime(self, regime_data: dict) -> tuple[float, str]:
        """
        Score market regime alignment. Max 10 points.
        Don't fight the tape.
        """
        regime = regime_data.get("regime", "unknown")
        vix = regime_data.get("vix", 20)

        regime_scores = {
            "bull": 10.0,   # Full points in bull market
            "choppy": 5.0,  # Half in choppy
            "bear": 2.0,    # Very little — only the best setups
            "unknown": 4.0,
        }

        score = regime_scores.get(regime, 4.0)

        # VIX adjustment
        if vix and vix < 15:
            score = min(score + 1, 10)  # Low VIX bonus
        elif vix and vix > 30:
            score = max(score - 3, 0)   # High VIX penalty

        return score, regime

    def _score_risk_reward(
        self, entry: float, stop: float, target: float
    ) -> tuple[float, float]:
        """
        Score risk/reward ratio. Max 10 points.
        Minimum 2:1 required to be considered.
        """
        if entry <= 0 or stop <= 0 or target <= 0:
            return 3.0, 0.0  # Can't calculate — partial credit

        risk = abs(entry - stop)
        reward = abs(target - entry)

        if risk == 0:
            return 3.0, 0.0

        rr_ratio = reward / risk

        if rr_ratio >= 5.0:
            return 10.0, rr_ratio
        elif rr_ratio >= 4.0:
            return 9.0, rr_ratio
        elif rr_ratio >= 3.0:
            return 8.0, rr_ratio
        elif rr_ratio >= 2.5:
            return 7.0, rr_ratio
        elif rr_ratio >= 2.0:
            return 6.0, rr_ratio
        elif rr_ratio >= 1.5:
            return 3.0, rr_ratio
        else:
            return 0.0, rr_ratio  # Below 1.5:1 — don't trade this

    def _score_political(
        self, political_signal: dict, ticker: str
    ) -> tuple[float, str]:
        """
        Score political/social tailwind. Max 10 points.
        This is our unique edge — the alpha most bots miss.
        """
        account = political_signal.get("account", "")
        direction = political_signal.get("direction", "neutral").lower()
        ticker_mentioned = ticker in political_signal.get("affected_tickers", [])
        sector_match = political_signal.get("sector_match", False)
        impact = political_signal.get("impact_level", "low").lower()

        score = 0.0
        context = "No political signal"

        if account.lower() in ["realdonaldtrump", "trump"]:
            base = 8.0
            context = f"Trump post — {direction}"
        elif account.lower() in ["elonmusk", "barrontrump"]:
            base = 6.0
            context = f"@{account} post — {direction}"
        else:
            base = 4.0
            context = f"@{account} signal"

        # Direction alignment bonus
        if direction == "bullish":
            score = base
        elif direction == "bearish":
            score = base * 0.3  # Bearish signal = lower score for long setup
        else:
            score = base * 0.5

        # Direct ticker mention doubles impact
        if ticker_mentioned:
            score = min(score * 1.5, 10)
            context += f" — {ticker} directly mentioned"

        # Sector alignment bonus
        if sector_match:
            score = min(score + 1, 10)

        # Impact level adjustment
        impact_mult = {"critical": 1.0, "high": 0.85, "medium": 0.65, "low": 0.4}
        score *= impact_mult.get(impact, 0.65)

        return round(min(score, 10), 1), context

    def _add_warnings(self, result: ConfidenceScore, data: dict) -> None:
        """Add critical warnings that should accompany any trade recommendation."""
        if data.get("rsi_extreme_overbought"):
            result.warnings.append("🔴 RSI extremely overbought — high reversal risk")

        if data.get("rsi_bearish_divergence"):
            result.warnings.append("⚠️ Bearish RSI divergence detected")

        if data.get("macd_bearish_crossover"):
            result.warnings.append("🔴 MACD bearish crossover — momentum shifting")

        if data.get("death_cross"):
            result.warnings.append("🔴 Death cross active (50 EMA below 200 EMA)")

        if data.get("volume_drying"):
            result.warnings.append("⚠️ Volume drying up — low conviction")

        if result.rr_ratio > 0 and result.rr_ratio < 2.0:
            result.warnings.append(f"❌ R:R ratio only {result.rr_ratio:.1f}:1 — minimum is 2:1")

    # ── Fix #6: Feedback Loop ─────────────────────────────────────────────────

    def record_outcome(
        self,
        ticker: str,
        confidence_breakdown: dict,
        pnl_pct: float,
        won: bool,
    ) -> None:
        """
        Record the outcome of a trade against its confidence breakdown.
        Stored in data/outcomes.json — used to refine weights over time.
        """
        import json
        from pathlib import Path
        from datetime import datetime

        outcomes_path = Path("data/outcomes.json")
        outcomes_path.parent.mkdir(exist_ok=True)

        try:
            outcomes = json.loads(outcomes_path.read_text()) if outcomes_path.exists() else []
        except Exception:
            outcomes = []

        outcomes.append({
            "ticker": ticker,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "breakdown": confidence_breakdown,
            "pnl_pct": pnl_pct,
            "won": won,
        })

        # Keep last 200 outcomes
        outcomes = outcomes[-200:]
        outcomes_path.write_text(json.dumps(outcomes, indent=2))
        logger.debug(f"Outcome recorded: {ticker} {'WIN' if won else 'LOSS'} {pnl_pct:+.1f}%")

    def get_weights_analysis(self) -> str:
        """
        Compare avg confidence component scores on winners vs losers.
        Shows which signals actually predict winning trades.
        Grows more accurate after 30+ trades.
        Text "weights" command triggers this.
        """
        import json
        from pathlib import Path

        path = Path("data/outcomes.json")
        if not path.exists():
            return (
                "No trade outcomes recorded yet mate. "
                "Need at least 10 closed trades before the weights analysis "
                "means anything. Keep trading — Fred learns from every close."
            )

        try:
            outcomes = json.loads(path.read_text())
        except Exception:
            return "Could not read outcomes file."

        if len(outcomes) < 10:
            wins = sum(1 for o in outcomes if o["won"])
            losses = sum(1 for o in outcomes if not o["won"])
            return (
                f"Only {len(outcomes)} trades recorded so far. "
                f"Need at least 10 for meaningful analysis. "
                f"Currently: {wins} wins, {losses} losses."
            )

        winners = [o for o in outcomes if o["won"]]
        losers  = [o for o in outcomes if not o["won"]]

        if not winners or not losers:
            return f"Not enough data — {len(winners)} wins, {len(losers)} losses."

        components = [
            "technical_setup", "volume_confirmation", "catalyst_strength",
            "sector_strength", "market_regime", "risk_reward_ratio",
            "political_tailwind",
        ]

        win_rate = len(winners) / len(outcomes) * 100
        lines = [
            f"WEIGHTS ANALYSIS — {len(outcomes)} trades",
            f"Win rate: {win_rate:.0f}% ({len(winners)}W / {len(losers)}L)",
            "",
            "Component avg — Winners vs Losers:",
        ]

        for comp in components:
            w_avg = sum(o["breakdown"].get(comp, 0) for o in winners) / len(winners)
            l_avg = sum(o["breakdown"].get(comp, 0) for o in losers) / len(losers)
            diff = w_avg - l_avg
            signal = "up" if diff > 2 else "dn" if diff < -2 else "~"
            label = comp.replace("_", " ").title()[:20]
            lines.append(f"  [{signal}] {label}: {w_avg:.1f} vs {l_avg:.1f} ({diff:+.1f})")

        lines.append("")
        lines.append("Text 'weights advice' for Fred's interpretation.")
        return "\n".join(lines)


# Global singleton
confidence_meter = ConfidenceMeter()

"""
utils/formatters.py
====================
Fred's SMS message formatters.

Every alert, every summary, every trade suggestion
sounds like Fred — Australian, direct, no padding.
"""

from typing import Optional


# ── Price / number formatters ──────────────────────────────────────────────────

def fmt_price(price: float) -> str:
    return f"${price:,.2f}"

def fmt_pct(pct: float, include_sign: bool = True) -> str:
    sign = "+" if pct > 0 and include_sign else ""
    return f"{sign}{pct:.2f}%"

def fmt_pnl(pnl: float) -> str:
    if pnl >= 0:
        return f"+${pnl:,.2f}"
    else:
        return f"-${abs(pnl):,.2f}"


# ── Position summary ───────────────────────────────────────────────────────────

def position_summary(ticker: str, shares: float, entry: float,
                     current: float, stop: float, target: float) -> str:
    pnl = (current - entry) * shares
    pct = ((current - entry) / entry) * 100
    emoji = "📈" if pnl >= 0 else "📉"
    pct_to_stop = ((current - stop) / current) * 100
    return (
        f"{emoji} {ticker}\n"
        f"  Entry: {fmt_price(entry)} → Now: {fmt_price(current)}\n"
        f"  P&L: {fmt_pnl(pnl)} ({fmt_pct(pct)})\n"
        f"  Stop: {fmt_price(stop)} ({fmt_pct(pct_to_stop, False)} away) "
        f"| Target: {fmt_price(target)}"
    )


# ── Stop loss alerts ───────────────────────────────────────────────────────────

def alert_stop_loss_warning(ticker: str, current: float,
                             stop: float, pct_away: float) -> str:
    return (
        f"⚠️ {ticker} — stop getting close mate.\n"
        f"Now: {fmt_price(current)} | Stop: {fmt_price(stop)}\n"
        f"Only {fmt_pct(pct_away, False)} between you and the line.\n"
        f"Eyes on it."
    )

def alert_stop_loss_hit(ticker: str, current: float,
                         stop: float, entry: float, shares: float) -> str:
    loss = (current - entry) * shares
    return (
        f"🚨 {ticker} — stop\'s gone.\n"
        f"Price: {fmt_price(current)} hit your stop at {fmt_price(stop)}.\n"
        f"Loss: {fmt_pnl(loss)}\n"
        f"Cut it now. Don\'t argue with it. That\'s the game."
    )


# ── Target alerts ──────────────────────────────────────────────────────────────

def alert_target_hit(ticker: str, current: float, target: float,
                      entry: float, shares: float) -> str:
    gain = (current - entry) * shares
    return (
        f"🎯 {ticker} — target hit. Bloody beauty.\n"
        f"Price: {fmt_price(current)} at your target {fmt_price(target)}.\n"
        f"Gain: {fmt_pnl(gain)}\n"
        f"Lock it in or trail the stop. Your call."
    )


# ── RSI / technical alerts ─────────────────────────────────────────────────────

def alert_rsi_overbought(ticker: str, rsi: float, current: float) -> str:
    return (
        f"🔴 {ticker} — RSI at {rsi:.1f}. Getting extended.\n"
        f"Price: {fmt_price(current)}\n"
        f"Consider tightening the stop or taking some off the table.\n"
        f"Don\'t get greedy this close to the top."
    )

def alert_macd_bearish(ticker: str, current: float) -> str:
    return (
        f"⚠️ {ticker} — MACD just crossed bearish.\n"
        f"Price: {fmt_price(current)}\n"
        f"Momentum is shifting. Tighten your stop.\n"
        f"Not a panic — but worth watching."
    )


# ── Breakout / setup alerts ────────────────────────────────────────────────────

def alert_breakout(ticker: str, current: float, volume_ratio: float,
                    setup: str, confidence: int) -> str:
    heat = "🔥" if confidence >= 80 else "⚡" if confidence >= 65 else "👀"
    return (
        f"{heat} {ticker} — {setup}\n"
        f"Price: {fmt_price(current)} | Volume: {volume_ratio:.1f}x avg\n"
        f"Confidence: {confidence}/100\n"
        f"Worth a proper look."
    )

def alert_bb_squeeze(ticker: str, current: float) -> str:
    return (
        f"⚡ {ticker} — Bollinger squeeze building.\n"
        f"Price: {fmt_price(current)}\n"
        f"Volatility compressed. Move incoming — watch for the direction.\n"
        f"Volume will tell you which way."
    )


# ── Social / news alerts ───────────────────────────────────────────────────────

def alert_social(account: str, post_preview: str,
                 impact: str, affected_tickers: list) -> str:
    urgency = "🚨" if impact == "HIGH" else "📢" if impact == "MEDIUM" else "📌"
    tickers_str = ", ".join(affected_tickers) if affected_tickers else "General market"
    preview = post_preview[:100] + ("..." if len(post_preview) > 100 else "")
    return (
        f"{urgency} @{account} just posted.\n"
        f"\"{preview}\"\n"
        f"Impact: {impact} | Watch: {tickers_str}"
    )

def alert_news(headline: str, ticker: str, impact: str) -> str:
    urgency = "🚨" if impact == "HIGH" else "📰"
    return (
        f"{urgency} {ticker} — news dropping.\n"
        f"{headline[:120]}\n"
        f"Impact: {impact} — check your position."
    )


# ── Trade suggestion ───────────────────────────────────────────────────────────

def trade_suggestion(ticker: str, action: str, entry: float,
                      target: float, stop: float, shares: int,
                      confidence: int, reason: str,
                      mode: str = "builder") -> str:

    rr = abs((target - entry) / (entry - stop)) if entry != stop else 0
    heat = "🔥" if confidence >= 85 else "✅" if confidence >= 70 else "👀"

    if confidence >= 90:
        size_line = "Size: 25-28% of portfolio."
    elif confidence >= 70:
        size_line = "Size: 15-20% of portfolio."
    else:
        size_line = "Size: 8-12% of portfolio."

    return (
        f"{heat} {ticker}\n"
        f"{reason[:100]}\n\n"
        f"Entry: {fmt_price(entry)}\n"
        f"Stop: {fmt_price(stop)}\n"
        f"Target: {fmt_price(target)}\n"
        f"R:R {rr:.1f}:1 | Score: {confidence}/100\n"
        f"{size_line}\n"
        f"Your call."
    )


# ── Portfolio health ───────────────────────────────────────────────────────────

def portfolio_health(total_value: float, cash: float, day_pnl: float,
                      total_pnl: float, open_positions: int) -> str:
    day_emoji = "📈" if day_pnl >= 0 else "📉"
    return (
        f"💼 PORTFOLIO\n"
        f"Total: {fmt_price(total_value)}\n"
        f"Cash: {fmt_price(cash)}\n"
        f"{day_emoji} Today: {fmt_pnl(day_pnl)}\n"
        f"All-time: {fmt_pnl(total_pnl)}\n"
        f"Open: {open_positions} position(s)"
    )


# ── Milestone celebration ──────────────────────────────────────────────────────

def milestone_text(balance: float, multiplier: float = 0) -> str:
    """Milestone text based on dollar amount crossed."""
    if balance >= 100_000:
        return (
            "🏆 $100,000.\n"
            "Six figures. Everything you built to get here was worth it.\n"
            "Enjoy that for thirty seconds. Then we find the next one."
        )
    elif balance >= 50_000:
        return (
            "💰 $50,000.\n"
            "Fifty grand mate. That\'s serious capital.\n"
            "Protect it. Keep compounding."
        )
    elif balance >= 25_000:
        return (
            "🚀 $25,000.\n"
            "PDT restrictions gone. Different game now.\n"
            "Stay sharp. Same rules, bigger stakes."
        )
    elif balance >= 10_000:
        return (
            "✅ $10,000.\n"
            "Ten grand. This is where it starts to matter.\n"
            "Keep the discipline that got you here."
        )
    elif balance >= 5_000:
        return (
            "📈 $5,000.\n"
            "Five grand. Halfway to something serious.\n"
            "Don\'t get sloppy now."
        )
    elif balance >= 2_500:
        return (
            "📊 $2,500.\n"
            "Building nicely. Stay the course."
        )
    elif balance >= 1_000:
        return (
            "✅ $1,000.\n"
            "First grand. That\'s real. Keep going."
        )
    else:
        return f"✅ ${balance:,.0f}. Building. Keep going."



def sms_help_menu() -> str:
    return (
        "FRED COMMANDS\n"
        "──────────────────────\n"
        "PORTFOLIO\n"
        "  status / positions\n"
        "  buy NVDA 20 at 127 stop 122 target 138\n"
        "  sold NVDA | stop NVDA 122\n"
        "\nSCOUTING\n"
        "  scan — market scan\n"
        "  gaps — overnight gap plays\n"
        "  discover — volume surges + rotation\n"
        "  NVDA — full ticker analysis\n"
        "  [send chart photo] — trade plan\n"
        "\nMONITORS\n"
        "  ts — social monitor status\n"
        "  weights — confidence analysis\n"
        "\nUPDATES\n"
        "  brief — 8:30am morning brief\n"
        "  midday — noon check-in\n"
        "  progress — performance stats\n"
        "  pdt — day trades remaining\n"
        "\nCONTROLS\n"
        "  rules | watchlist | sync | help"
    )

def dead_market_msg() -> str:
    import random
    msgs = [
        "Scanned everything. Honestly? Nothing worth touching today. Cash is a position — beats a bad trade every time.",
        "Quiet out there. No clean setups. Don\'t force it.",
        "Market\'s giving nothing right now. Stay patient. The setups will come.",
        "Nothing jumping out. Some days are like this. Wait for the real ones.",
        "Choppy and directionless. This is where bad trades happen. Stay flat.",
    ]
    return random.choice(msgs)

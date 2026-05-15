"""
core/discovery.py
=================
Fred's dynamic stock discovery engine.

Fred doesn't just watch a fixed list. He hunts.
This module finds stocks worth looking at that aren't
on the standard watchlist — volume surges, earnings gappers,
sector rotation plays, and news-driven opportunities.

Every discovery gets quick-scored. Only high-quality
discoveries get surfaced to the trader.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from config.trading_rules import SCAN_UNIVERSE

logger = logging.getLogger("fred.discovery")

# Minimum volume ratio to flag as a surge
VOLUME_SURGE_THRESHOLD = 2.5   # 2.5x normal volume
EARNINGS_GAP_THRESHOLD = 0.07  # 7% gap = earnings gapper
SECTOR_ROTATION_THRESHOLD = 0.02  # 2% ETF move triggers sector scan


class DiscoveryEngine:
    """
    Finds new trading opportunities beyond the base watchlist.
    Runs on a daily schedule and feeds into the main scanner.
    """

    def __init__(self):
        self._discovered_tickers: dict[str, dict] = {}
        self._discovery_ttl_hours = 48   # Remove discoveries after 48 hours
        logger.info("DiscoveryEngine initialized")

    # ── Volume Surge Scanner ─────────────────────────────────────────────────

    def scan_volume_surges(self) -> list[dict]:
        """
        Find stocks trading significantly above normal volume.
        Something is always happening somewhere — volume finds it first.
        """
        try:
            import yfinance as yf
            import pandas as pd

            # Broad universe to scan beyond the base watchlist
            scan_list = list(set(SCAN_UNIVERSE + [
                "HOOD", "RIVN", "NIO", "LCID", "SPCE", "BBAI", "AI",
                "SMCI", "ARM", "ASML", "LRCX", "KLAC", "AMAT",
                "SNOW", "DDOG", "NET", "ZS", "OKTA", "MDB",
                "SHOP", "TTD", "RBLX", "U", "SNAP", "PINS",
                "XOM", "CVX", "OXY", "HAL", "SLB",
                "GLD", "SLV", "GDX", "GDXJ",
            ]))

            surges = []

            for ticker in scan_list:
                try:
                    data = yf.Ticker(ticker)
                    hist = data.history(period="25d")

                    if hist.empty or len(hist) < 20:
                        continue

                    avg_vol = hist["Volume"][:-1].mean()
                    today_vol = hist["Volume"].iloc[-1]

                    if avg_vol <= 0:
                        continue

                    ratio = today_vol / avg_vol

                    if ratio >= VOLUME_SURGE_THRESHOLD:
                        price = hist["Close"].iloc[-1]
                        prev_close = hist["Close"].iloc[-2]
                        change_pct = ((price - prev_close) / prev_close) * 100

                        surges.append({
                            "ticker": ticker,
                            "volume_ratio": round(ratio, 1),
                            "price": round(price, 2),
                            "change_pct": round(change_pct, 2),
                            "discovery_reason": f"Volume surge {ratio:.1f}x avg",
                            "discovery_type": "volume_surge",
                        })
                        logger.info(
                            f"Volume surge: {ticker} — {ratio:.1f}x avg | "
                            f"{change_pct:+.1f}%"
                        )

                except Exception as e:
                    logger.debug(f"Volume check failed for {ticker}: {e}")
                    continue

            # Sort by volume ratio
            surges.sort(key=lambda x: x["volume_ratio"], reverse=True)
            logger.info(f"Volume surge scan: {len(surges)} found")
            return surges[:10]  # Top 10

        except Exception as e:
            logger.error(f"Volume surge scan error: {e}")
            return []

    # ── Earnings Gapper Scanner ───────────────────────────────────────────────

    def scan_earnings_gappers(self) -> list[dict]:
        """
        Find stocks that gapped significantly on earnings overnight.
        Earnings gappers that hold the gap are among the cleanest
        swing setups — institutions confirming the move.
        """
        try:
            import yfinance as yf

            # Get earnings calendar for this week
            gappers = []

            # Check SPY components and popular names for overnight gaps
            check_list = list(set(SCAN_UNIVERSE + [
                "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA",
                "AMD", "INTC", "QCOM", "AVGO", "MU", "AMAT", "LRCX",
                "JPM", "BAC", "GS", "MS", "WFC", "C",
                "UNH", "LLY", "JNJ", "ABBV", "MRK", "PFE",
                "XOM", "CVX", "OXY",
                "HD", "LOW", "COST", "WMT", "TGT",
                "NFLX", "DIS", "CMCSA",
                "V", "MA", "AXP", "PYPL",
                "SNOW", "DDOG", "CRM", "NOW", "ADBE",
            ]))

            for ticker in check_list:
                try:
                    data = yf.Ticker(ticker)
                    hist = data.history(period="3d")

                    if hist.empty or len(hist) < 2:
                        continue

                    prev_close = hist["Close"].iloc[-2]
                    today_open = hist["Open"].iloc[-1]

                    if prev_close <= 0:
                        continue

                    gap_pct = ((today_open - prev_close) / prev_close) * 100

                    if abs(gap_pct) >= EARNINGS_GAP_THRESHOLD * 100:
                        current_price = hist["Close"].iloc[-1]
                        vol_today = hist["Volume"].iloc[-1]
                        vol_avg = hist["Volume"].mean()
                        vol_ratio = vol_today / vol_avg if vol_avg > 0 else 1.0

                        direction = "up" if gap_pct > 0 else "down"

                        gappers.append({
                            "ticker": ticker,
                            "gap_pct": round(gap_pct, 1),
                            "direction": direction,
                            "price": round(current_price, 2),
                            "open": round(today_open, 2),
                            "prev_close": round(prev_close, 2),
                            "volume_ratio": round(vol_ratio, 1),
                            "discovery_reason": f"Earnings gap {gap_pct:+.1f}% overnight",
                            "discovery_type": "earnings_gap",
                        })
                        logger.info(
                            f"Earnings gapper: {ticker} {gap_pct:+.1f}% | "
                            f"vol {vol_ratio:.1f}x"
                        )

                except Exception as e:
                    logger.debug(f"Gap check failed for {ticker}: {e}")
                    continue

            # Sort by absolute gap size
            gappers.sort(key=lambda x: abs(x["gap_pct"]), reverse=True)
            logger.info(f"Earnings gap scan: {len(gappers)} found")
            return gappers[:8]

        except Exception as e:
            logger.error(f"Earnings gap scan error: {e}")
            return []

    # ── Sector Rotation Scanner ───────────────────────────────────────────────

    def scan_sector_rotation(self) -> list[dict]:
        """
        When a sector ETF moves significantly, surface the top
        individual names in that sector. Money flows into sectors
        before it flows into individual stocks.
        """
        try:
            import yfinance as yf

            hot_sectors = []

            for etf, info in sector_etfs.items():
                try:
                    data = yf.Ticker(etf)
                    hist = data.history(period="3d")

                    if hist.empty or len(hist) < 2:
                        continue

                    prev = hist["Close"].iloc[-2]
                    current = hist["Close"].iloc[-1]
                    change = ((current - prev) / prev)

                    if abs(change) >= SECTOR_ROTATION_THRESHOLD:
                        direction = "bull" if change > 0 else "bear"
                        hot_sectors.append({
                            "etf": etf,
                            "sector_name": sector_info["name"],
                            "change_pct": round(change * 100, 2),
                            "direction": direction,
                            "component_tickers": sector_info["tickers"],
                        })
                        logger.info(
                            f"Sector rotation: {sector_info['name']} "
                            f"({etf}) {change*100:+.1f}%"
                        )

                except Exception as e:
                    logger.debug(f"Sector check failed for {etf}: {e}")

            discoveries = []
            for sector in hot_sectors:
                for ticker in sector["component_tickers"]:
                    if ticker not in SCAN_UNIVERSE:
                        discoveries.append({
                            "ticker": ticker,
                            "discovery_reason": (
                                f"{sector['sector_name']} sector "
                                f"{sector['change_pct']:+.1f}% today — "
                                f"rotating {'in' if sector['direction'] == 'bull' else 'out'}"
                            ),
                            "discovery_type": "sector_rotation",
                            "sector": sector["sector_name"],
                            "sector_direction": sector["direction"],
                        })

            logger.info(f"Sector rotation: {len(discoveries)} tickers surfaced")
            return discoveries

        except Exception as e:
            logger.error(f"Sector rotation scan error: {e}")
            return []

    # ── News-Driven Discovery ─────────────────────────────────────────────────

    def extract_tickers_from_news(self, headline: str, body: str = "") -> list[str]:
        """
        Parse a news headline for ticker symbols.
        Catches both $NVDA format and bare mentions against known names.
        """
        import re

        discovered = set()
        text = f"{headline} {body}".upper()

        # $TICKER format
        dollar_tickers = re.findall(r'\$([A-Z]{1,5})\b', text)
        discovered.update(dollar_tickers)

        # Common known names in headlines
        known = {
            "NVIDIA": "NVDA", "APPLE": "AAPL", "MICROSOFT": "MSFT",
            "TESLA": "TSLA", "AMAZON": "AMZN", "GOOGLE": "GOOGL",
            "META": "META", "AMD": "AMD", "INTEL": "INTC",
            "PALANTIR": "PLTR", "COINBASE": "COIN", "ROBINHOOD": "HOOD",
            "RIVIAN": "RIVN", "LUCID": "LCID", "SPACEX": "SPCE",
        }
        for name, ticker in known.items():
            if name in text:
                discovered.add(ticker)

        return list(discovered)

    # ── Full Discovery Run ────────────────────────────────────────────────────

    def run_full_discovery(self) -> list[dict]:
        """
        Run all discovery scanners and return deduplicated results.
        Called every morning and after major market events.
        """
        logger.info("Running full discovery scan...")
        all_discoveries = []

        # Volume surges
        surges = self.scan_volume_surges()
        all_discoveries.extend(surges)

        # Earnings gappers
        gappers = self.scan_earnings_gappers()
        all_discoveries.extend(gappers)

        # Sector rotation
        rotation = self.scan_sector_rotation()
        all_discoveries.extend(rotation)

        # Deduplicate by ticker (keep highest priority)
        seen = {}
        priority = {"volume_surge": 3, "earnings_gap": 2, "sector_rotation": 1}
        for d in all_discoveries:
            ticker = d["ticker"]
            p = priority.get(d.get("discovery_type", ""), 0)
            if ticker not in seen or p > priority.get(seen[ticker].get("discovery_type", ""), 0):
                seen[ticker] = d

        unique = list(seen.values())
        logger.info(f"Full discovery: {len(unique)} unique tickers found")
        return unique

    def get_discovery_summary_sms(self, discoveries: list[dict]) -> str:
        """Format discovery results for SMS."""
        if not discoveries:
            return "🔍 Discovery scan complete — nothing unusual today. Market is quiet."

        surges = [d for d in discoveries if d.get("discovery_type") == "volume_surge"]
        gappers = [d for d in discoveries if d.get("discovery_type") == "earnings_gap"]
        rotation = [d for d in discoveries if d.get("discovery_type") == "sector_rotation"]

        lines = [f"🔍 DISCOVERY — {len(discoveries)} new names\n"]

        if surges[:3]:
            lines.append("📊 VOLUME SURGES:")
            for s in surges[:3]:
                lines.append(
                    f"  {s['ticker']} — {s['volume_ratio']}x vol | "
                    f"{s.get('change_pct', 0):+.1f}%"
                )

        if gappers[:3]:
            lines.append("\n⚡ EARNINGS GAPPERS:")
            for g in gappers[:3]:
                lines.append(
                    f"  {g['ticker']} — {g['gap_pct']:+.1f}% gap | "
                    f"vol {g.get('volume_ratio', 0):.1f}x"
                )

        if rotation:
            sectors = list({d["sector"] for d in rotation})[:2]
            lines.append(f"\n🔄 SECTOR ROTATION: {', '.join(sectors)}")

        return "\n".join(lines)


    def _get_broad_universe(self) -> list[str]:
        """Broad scan universe — top actively traded US stocks."""
        return [
            "AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","AVGO",
            "AMD","PLTR","SOFI","MSTR","CRWD","PANW","COIN","RKLB","LUNR","DJT",
            "BAC","JPM","GS","MS","WFC","C","BLK","SCHW",
            "MRNA","BNTX","REGN","ABBV","PFE","GILD",
            "XOM","CVX","OXY","SLB","HAL","MPC","VLO",
            "INTC","MU","QCOM","AMAT","LRCX","KLAC","TXN",
            "NFLX","SHOP","PYPL","HOOD","RIVN","NIO","LCID",
            "SPY","QQQ","SOXL","TQQQ","ARKK","IWM",
            "SNOW","DDOG","ZM","UBER","LYFT","ABNB","DASH",
            "RBLX","SNAP","PINS","BILL","HUBS","ZS","OKTA","NET",
            "GME","AMC","FCX","NEM",
        ]

    def find_news_driven_tickers(self, headlines: list[dict]) -> list[str]:
        """Extract tickers from headlines. Alias for extract_tickers_from_news."""
        import re
        SKIP = {"US","UK","EU","AI","IPO","CEO","CFO","COO","CTO","SEC","FDA",
                "FTC","DOJ","GDP","CPI","PCE","FOMC","FED","NYSE","ETF","SPX",
                "VIX","RSI","MACD","EMA","ATH","ATL","YTD","Q1","Q2","Q3","Q4"}
        found = set()
        for h in headlines:
            text = (h.get("title","") or h.get("text","")).upper()
            for word in re.findall(r"\b([A-Z]{2,5})\b", text):
                if word not in SKIP:
                    found.add(word)
            # Also check known names
            known = {"NVIDIA":"NVDA","APPLE":"AAPL","MICROSOFT":"MSFT",
                     "TESLA":"TSLA","AMAZON":"AMZN","GOOGLE":"GOOGL",
                     "AMD":"AMD","INTEL":"INTC","PALANTIR":"PLTR"}
            for name, ticker in known.items():
                if name in text:
                    found.add(ticker)
        return list(found)

    def format_discovery_sms(self, results) -> str:
        """Alias for get_discovery_summary_sms for interface compatibility."""
        if isinstance(results, list):
            return self.get_discovery_summary_sms(results)
        # results is a dict (new format)
        discoveries = []
        discoveries.extend(results.get("volume_surges", []))
        discoveries.extend(results.get("earnings_gappers", []))
        return self.get_discovery_summary_sms(discoveries)


# Global singleton
discovery_engine = DiscoveryEngine()

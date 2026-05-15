"""
integrations/notion_client.py
==============================
Full Notion database integration for Fred.

Manages 6 databases:
1. Open Positions      — live trades being tracked
2. Watchlist           — stocks on radar with thesis
3. Trade Journal       — closed trades with outcomes
4. Trading Rules       — personal rulebook Fred enforces
5. Alert Log           — every alert fired and outcome
6. Social Triggers     — posts that moved positions

All database IDs are pulled from .env and set up by
scripts/setup_notion.py on first run.
"""

from notion_client import AsyncClient
from datetime import datetime
from typing import Optional
import logging as _logging; logger = _logging.getLogger(__name__)

from config.settings import settings


class NotionClient:
    """
    Async Notion API wrapper for all Fred databases.
    """

    def __init__(self):
        self.client = AsyncClient(auth=settings.notion_api_key)
        self.db_ids = {
            "positions": settings.notion_positions_db,
            "watchlist": settings.notion_watchlist_db,
            "journal": settings.notion_journal_db,
            "rules": settings.notion_rules_db,
            "alerts_log": settings.notion_alerts_log_db,
            "social_triggers": settings.notion_social_triggers_db,
        }

    # ── Open Positions ───────────────────────────────────────────────────────

    async def get_open_positions(self) -> list[dict]:
        """Fetch all open positions."""
        try:
            response = await self.client.databases.query(
                database_id=self.db_ids["positions"],
                filter={
                    "property": "Status",
                    "select": {"equals": "Open"},
                },
            )
            return [self._parse_position_page(p) for p in response["results"]]
        except Exception as e:
            logger.error(f"Failed to fetch positions from Notion: {e}")
            return []

    async def add_position(self, position_data: dict) -> Optional[str]:
        """Add a new open position to Notion. Returns page ID."""
        try:
            ticker = position_data.get("ticker", "")
            response = await self.client.pages.create(
                parent={"database_id": self.db_ids["positions"]},
                properties={
                    "Ticker": {"title": [{"text": {"content": ticker}}]},
                    "Status": {"select": {"name": "Open"}},
                    "Shares": {"number": position_data.get("shares", 0)},
                    "Entry Price": {"number": position_data.get("entry_price", 0)},
                    "Stop Loss": {"number": position_data.get("stop_loss", 0)},
                    "Target": {"number": position_data.get("target", 0)},
                    "Thesis": {"rich_text": [{"text": {"content": position_data.get("thesis", "")}}]},
                    "Catalyst Type": {"select": {"name": position_data.get("catalyst_type", "technical_only")}},
                    "Confidence Score": {"number": position_data.get("confidence_at_entry", 0)},
                    "Entry Date": {"date": {"start": position_data.get("entry_date", datetime.now().isoformat())}},
                    "Sector": {"rich_text": [{"text": {"content": position_data.get("sector", "")}}]},
                },
            )
            logger.info(f"Added position {ticker} to Notion: {response['id']}")
            return response["id"]
        except Exception as e:
            logger.error(f"Failed to add position to Notion: {e}")
            return None

    async def update_position(self, page_id: str, updates: dict) -> bool:
        """Update a position's properties."""
        try:
            properties = {}

            if "current_price" in updates:
                properties["Current Price"] = {"number": updates["current_price"]}
            if "stop_loss" in updates:
                properties["Stop Loss"] = {"number": updates["stop_loss"]}
            if "target" in updates:
                properties["Target"] = {"number": updates["target"]}
            if "status" in updates:
                properties["Status"] = {"select": {"name": updates["status"]}}

            await self.client.pages.update(page_id=page_id, properties=properties)
            return True
        except Exception as e:
            logger.error(f"Failed to update position {page_id}: {e}")
            return False

    async def close_position(self, page_id: str, trade_result: dict) -> bool:
        """Mark a position as closed and record exit details."""
        try:
            await self.client.pages.update(
                page_id=page_id,
                properties={
                    "Status": {"select": {"name": "Closed"}},
                    "Exit Price": {"number": trade_result.get("exit_price", 0)},
                    "P&L ($)": {"number": trade_result.get("pnl_dollars", 0)},
                    "P&L (%)": {"number": trade_result.get("pnl_pct", 0)},
                    "Exit Date": {"date": {"start": trade_result.get("exit_date", datetime.now().isoformat())}},
                    "Exit Reason": {"rich_text": [{"text": {"content": trade_result.get("exit_reason", "")}}]},
                    "Outcome": {"select": {"name": trade_result.get("outcome", "LOSS")}},
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to close position in Notion: {e}")
            return False

    # ── Watchlist ────────────────────────────────────────────────────────────

    async def get_watchlist(self) -> list[dict]:
        """Fetch all active watchlist items."""
        try:
            response = await self.client.databases.query(
                database_id=self.db_ids["watchlist"],
                filter={
                    "property": "Active",
                    "checkbox": {"equals": True},
                },
            )
            return [self._parse_watchlist_page(p) for p in response["results"]]
        except Exception as e:
            logger.error(f"Failed to fetch watchlist: {e}")
            return []

    async def add_to_watchlist(
        self,
        ticker: str,
        thesis: str,
        entry_zone: str = "",
        stop_loss: float = 0,
        target: float = 0,
        catalyst_type: str = "technical_only",
    ) -> Optional[str]:
        """Add a stock to the watchlist."""
        try:
            response = await self.client.pages.create(
                parent={"database_id": self.db_ids["watchlist"]},
                properties={
                    "Ticker": {"title": [{"text": {"content": ticker}}]},
                    "Thesis": {"rich_text": [{"text": {"content": thesis}}]},
                    "Entry Zone": {"rich_text": [{"text": {"content": entry_zone}}]},
                    "Stop Loss": {"number": stop_loss},
                    "Target": {"number": target},
                    "Catalyst Type": {"select": {"name": catalyst_type}},
                    "Active": {"checkbox": True},
                    "Added Date": {"date": {"start": datetime.now().isoformat()}},
                },
            )
            return response["id"]
        except Exception as e:
            logger.error(f"Failed to add to watchlist: {e}")
            return None

    async def remove_from_watchlist(self, ticker: str) -> bool:
        """Deactivate a watchlist item."""
        try:
            # Find the page
            response = await self.client.databases.query(
                database_id=self.db_ids["watchlist"],
                filter={"property": "Ticker", "title": {"equals": ticker}},
            )
            if not response["results"]:
                return False

            page_id = response["results"][0]["id"]
            await self.client.pages.update(
                page_id=page_id,
                properties={"Active": {"checkbox": False}},
            )
            return True
        except Exception as e:
            logger.error(f"Failed to remove {ticker} from watchlist: {e}")
            return False

    # ── Trade Journal ─────────────────────────────────────────────────────────

    async def add_journal_entry(self, trade_result: dict) -> Optional[str]:
        """Log a completed trade to the journal."""
        try:
            outcome = trade_result.get("outcome", "LOSS")
            pnl_pct = trade_result.get("pnl_pct", 0)

            # Auto-generate lesson prompt
            lesson = trade_result.get("lesson", "")
            if not lesson:
                lesson = (
                    f"{'Win' if outcome == 'WIN' else 'Loss'}: "
                    f"{pnl_pct:+.1f}%. Review thesis and execution."
                )

            response = await self.client.pages.create(
                parent={"database_id": self.db_ids["journal"]},
                properties={
                    "Trade": {"title": [{"text": {"content": f"{trade_result.get('ticker')} {outcome}"}}]},
                    "Ticker": {"rich_text": [{"text": {"content": trade_result.get("ticker", "")}}]},
                    "Entry Price": {"number": trade_result.get("entry_price", 0)},
                    "Exit Price": {"number": trade_result.get("exit_price", 0)},
                    "Shares": {"number": trade_result.get("shares", 0)},
                    "P&L ($)": {"number": trade_result.get("pnl_dollars", 0)},
                    "P&L (%)": {"number": trade_result.get("pnl_pct", 0)},
                    "Outcome": {"select": {"name": outcome}},
                    "Exit Reason": {"rich_text": [{"text": {"content": trade_result.get("exit_reason", "")}}]},
                    "Thesis": {"rich_text": [{"text": {"content": trade_result.get("thesis", "")}}]},
                    "Confidence at Entry": {"number": trade_result.get("confidence_at_entry", 0)},
                    "Entry Date": {"date": {"start": trade_result.get("entry_date", "")}},
                    "Exit Date": {"date": {"start": trade_result.get("exit_date", datetime.now().isoformat())}},
                    "Lesson": {"rich_text": [{"text": {"content": lesson}}]},
                },
            )
            return response["id"]
        except Exception as e:
            logger.error(f"Failed to add journal entry: {e}")
            return None

    async def get_journal_stats(self) -> dict:
        """Aggregate trade journal for performance stats."""
        try:
            response = await self.client.databases.query(
                database_id=self.db_ids["journal"]
            )
            trades = [self._parse_journal_page(p) for p in response["results"]]

            if not trades:
                return {"total_trades": 0, "win_rate": 0, "total_pnl": 0}

            wins = [t for t in trades if t.get("outcome") == "WIN"]
            total_pnl = sum(t.get("pnl_dollars", 0) for t in trades)
            avg_win = sum(t.get("pnl_dollars", 0) for t in wins) / len(wins) if wins else 0
            losses = [t for t in trades if t.get("outcome") == "LOSS"]
            avg_loss = sum(t.get("pnl_dollars", 0) for t in losses) / len(losses) if losses else 0
            profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0

            return {
                "total_trades": len(trades),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": (len(wins) / len(trades) * 100) if trades else 0,
                "total_pnl": total_pnl,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "profit_factor": profit_factor,
            }
        except Exception as e:
            logger.error(f"Failed to get journal stats: {e}")
            return {}

    # ── Alert Log ─────────────────────────────────────────────────────────────

    async def log_alert(
        self,
        alert_type: str,
        ticker: Optional[str],
        message: str,
        urgency: str = "LOW",
        action_taken: str = "",
    ) -> None:
        """Log every alert Fred sends."""
        try:
            await self.client.pages.create(
                parent={"database_id": self.db_ids["alerts_log"]},
                properties={
                    "Alert": {"title": [{"text": {"content": f"{alert_type}: {ticker or 'Market'}"}}]},
                    "Type": {"select": {"name": alert_type}},
                    "Ticker": {"rich_text": [{"text": {"content": ticker or ""}}]},
                    "Message": {"rich_text": [{"text": {"content": message}}]},
                    "Urgency": {"select": {"name": urgency}},
                    "Action Taken": {"rich_text": [{"text": {"content": action_taken}}]},
                    "Timestamp": {"date": {"start": datetime.now().isoformat()}},
                },
            )
        except Exception as e:
            logger.error(f"Failed to log alert: {e}")

    # ── Social Triggers ───────────────────────────────────────────────────────

    async def log_social_trigger(
        self,
        account: str,
        post_text: str,
        impact_level: str,
        affected_tickers: list[str],
        analysis: str,
    ) -> None:
        """Log a social media post that had market impact."""
        try:
            await self.client.pages.create(
                parent={"database_id": self.db_ids["social_triggers"]},
                properties={
                    "Post": {"title": [{"text": {"content": f"@{account}: {post_text[:50]}..."}}]},
                    "Account": {"rich_text": [{"text": {"content": account}}]},
                    "Post Text": {"rich_text": [{"text": {"content": post_text}}]},
                    "Impact Level": {"select": {"name": impact_level}},
                    "Affected Tickers": {"rich_text": [{"text": {"content": ", ".join(affected_tickers)}}]},
                    "Fred's Analysis": {"rich_text": [{"text": {"content": analysis}}]},
                    "Timestamp": {"date": {"start": datetime.now().isoformat()}},
                },
            )
        except Exception as e:
            logger.error(f"Failed to log social trigger: {e}")

    # ── Parser Helpers ────────────────────────────────────────────────────────


    async def append_to_brain_section(
        self,
        section: str,
        ticker: Optional[str],
        content: str,
    ) -> bool:
        """
        Append a note to a section in Fred's Brain Notion page.
        Creates a new block under the matching section heading.
        """
        FREDS_BRAIN_PAGE_ID = "35ed6963-22fb-8199-a118-d6f0225ffebc"
        try:
            # Append as a paragraph block to the page
            label = f"[{ticker}] " if ticker else ""
            full_content = f"{label}{content}"
            # Truncate to Notion block limit
            if len(full_content) > 1900:
                full_content = full_content[:1897] + "..."

            await self.client.blocks.children.append(
                block_id=FREDS_BRAIN_PAGE_ID,
                children=[
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {"content": full_content},
                                }
                            ]
                        },
                    }
                ],
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to append to Fred's Brain ({section}): {e}")
            return False

    def _parse_position_page(self, page: dict) -> dict:
        """Extract position data from a Notion page."""
        props = page.get("properties", {})

        def get_text(prop_name):
            prop = props.get(prop_name, {})
            items = prop.get("rich_text") or prop.get("title") or []
            return items[0]["text"]["content"] if items else ""

        def get_number(prop_name):
            return props.get(prop_name, {}).get("number", 0) or 0

        def get_select(prop_name):
            sel = props.get(prop_name, {}).get("select")
            return sel["name"] if sel else ""

        def get_date(prop_name):
            date_obj = props.get(prop_name, {}).get("date")
            return date_obj["start"] if date_obj else None

        return {
            "id": page["id"],
            "ticker": get_text("Ticker"),
            "shares": get_number("Shares"),
            "entry_price": get_number("Entry Price"),
            "current_price": get_number("Current Price"),
            "stop_loss": get_number("Stop Loss"),
            "target": get_number("Target"),
            "thesis": get_text("Thesis"),
            "catalyst_type": get_select("Catalyst Type"),
            "confidence_at_entry": get_number("Confidence Score"),
            "entry_date": get_date("Entry Date"),
            "sector": get_text("Sector"),
            "status": get_select("Status"),
        }

    def _parse_watchlist_page(self, page: dict) -> dict:
        """Extract watchlist data from a Notion page."""
        props = page.get("properties", {})

        def get_text(prop_name):
            prop = props.get(prop_name, {})
            items = prop.get("rich_text") or prop.get("title") or []
            return items[0]["text"]["content"] if items else ""

        def get_number(prop_name):
            return props.get(prop_name, {}).get("number", 0) or 0

        def get_select(prop_name):
            sel = props.get(prop_name, {}).get("select")
            return sel["name"] if sel else ""

        return {
            "id": page["id"],
            "ticker": get_text("Ticker"),
            "thesis": get_text("Thesis"),
            "entry_zone": get_text("Entry Zone"),
            "stop_loss": get_number("Stop Loss"),
            "target": get_number("Target"),
            "catalyst_type": get_select("Catalyst Type"),
        }

    def _parse_journal_page(self, page: dict) -> dict:
        """Extract journal data from a Notion page."""
        props = page.get("properties", {})

        def get_number(prop_name):
            return props.get(prop_name, {}).get("number", 0) or 0

        def get_select(prop_name):
            sel = props.get(prop_name, {}).get("select")
            return sel["name"] if sel else ""

        return {
            "id": page["id"],
            "pnl_dollars": get_number("P&L ($)"),
            "pnl_pct": get_number("P&L (%)"),
            "outcome": get_select("Outcome"),
        }


# ── Fred's Brain Writer ───────────────────────────────────────────────────


    # ── Fred State Persistence (Fix #3 — Railway ephemeral filesystem) ────────
    # State stored in Notion so it survives Railway redeploys.

    async def save_fred_state(self, state_dict: dict) -> bool:
        """
        Save Fred's full state to a Notion page.
        Called after every balance update, trade, and mode switch.
        Survives Railway deploys — local filesystem does not.
        """
        try:
            import json
            state_page_id = getattr(settings, "notion_fred_state_page_id", None)
            if not state_page_id:
                # Fall back to local file if no Notion state page configured
                from pathlib import Path
                Path("data").mkdir(exist_ok=True)
                with open("data/fred_state.json", "w") as f:
                    json.dump(state_dict, f, indent=2)
                return True

            # Store as a code block in Notion (easy to read and parse)
            await self.client.blocks.children.append(
                block_id=state_page_id,
                children=[{
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": [{
                            "type": "text",
                            "text": {"content": json.dumps(state_dict, indent=2)}
                        }],
                        "language": "json"
                    }
                }]
            )
            return True
        except Exception as e:
            logger.error(f"State save error: {e}")
            # Always fall back to local file
            try:
                import json
                from pathlib import Path
                Path("data").mkdir(exist_ok=True)
                with open("data/fred_state.json", "w") as f:
                    json.dump(state_dict, f, indent=2)
            except Exception:
                pass
            return False

    async def load_fred_state(self) -> dict:
        """
        Load Fred's state from Notion.
        Falls back to local file if Notion not configured.
        """
        try:
            import json
            state_page_id = getattr(settings, "notion_fred_state_page_id", None)
            if not state_page_id:
                from pathlib import Path
                path = Path("data/fred_state.json")
                if path.exists():
                    return json.loads(path.read_text())
                return {}

            blocks = await self.client.blocks.children.list(block_id=state_page_id)
            code_blocks = [
                b for b in blocks.get("results", [])
                if b.get("type") == "code"
            ]
            if not code_blocks:
                return {}

            # Get the most recent code block
            latest = code_blocks[-1]
            text = latest["code"]["rich_text"][0]["text"]["content"]
            return json.loads(text)
        except Exception as e:
            logger.debug(f"State load from Notion failed: {e}")
            try:
                import json
                from pathlib import Path
                path = Path("data/fred_state.json")
                if path.exists():
                    return json.loads(path.read_text())
            except Exception:
                pass
            return {}

    async def save_sms_history(self, number: str, history: list) -> bool:
        """Save SMS conversation history for a phone number."""
        try:
            import json
            db_id = getattr(settings, "notion_sms_history_db_id", None)
            if not db_id:
                return False

            # Upsert — find existing or create new
            results = await self.client.databases.query(
                database_id=db_id,
                filter={"property": "Phone", "title": {"equals": number}}
            )

            history_json = json.dumps(history[-20:])  # Keep last 20 messages
            properties = {
                "Phone": {"title": [{"text": {"content": number}}]},
                "History": {"rich_text": [{"text": {"content": history_json[:2000]}}]},
            }

            if results.get("results"):
                page_id = results["results"][0]["id"]
                await self.client.pages.update(
                    page_id=page_id, properties=properties
                )
            else:
                await self.client.pages.create(
                    parent={"database_id": db_id},
                    properties=properties,
                )
            return True
        except Exception as e:
            logger.debug(f"SMS history save error: {e}")
            return False

    async def load_sms_history(self, number: str) -> list:
        """Load SMS conversation history for a phone number."""
        try:
            import json
            db_id = getattr(settings, "notion_sms_history_db_id", None)
            if not db_id:
                return []

            results = await self.client.databases.query(
                database_id=db_id,
                filter={"property": "Phone", "title": {"equals": number}}
            )
            if not results.get("results"):
                return []

            page = results["results"][0]
            history_text = (
                page["properties"]
                .get("History", {})
                .get("rich_text", [{}])[0]
                .get("text", {})
                .get("content", "[]")
            )
            return json.loads(history_text)
        except Exception as e:
            logger.debug(f"SMS history load error: {e}")
            return []

    async def get_brain_notes_for_ticker(self, ticker: str) -> list[dict]:
        """
        Get Fred's previous notes on a specific ticker.
        Injected into analysis prompts — Fred remembers what he's seen.
        """
        try:
            brain_page_id = getattr(settings, "notion_freds_brain_page_id", None)
            if not brain_page_id:
                return []

            # Search child pages of Fred's Brain for this ticker
            children = await self.client.blocks.children.list(
                block_id=brain_page_id
            )
            notes = []
            ticker_upper = ticker.upper()

            for block in children.get("results", []):
                if block.get("type") == "child_page":
                    title = block.get("child_page", {}).get("title", "")
                    if ticker_upper in title.upper():
                        # Get the content of this note page
                        try:
                            page_blocks = await self.client.blocks.children.list(
                                block_id=block["id"]
                            )
                            for pb in page_blocks.get("results", []):
                                if pb.get("type") == "paragraph":
                                    text = "".join(
                                        rt.get("text", {}).get("content", "")
                                        for rt in pb.get("paragraph", {})
                                            .get("rich_text", [])
                                    )
                                    if text:
                                        notes.append({
                                            "title": title,
                                            "text": text,
                                        })
                        except Exception:
                            pass

            return notes[-5:]  # Last 5 notes on this ticker
        except Exception as e:
            logger.debug(f"Brain note fetch error for {ticker}: {e}")
            return []

    async def write_brain_note(self, ticker: str, note: str, note_type: str = "analysis") -> bool:
        """
        Append a note to Fred's Brain page in Notion.
        Called automatically after every analysis, trade, or market observation.
        """
        try:
            brain_page_id = getattr(settings, "notion_freds_brain_page_id", None)
            if not brain_page_id:
                logger.debug("Fred's Brain page ID not configured — skipping note write")
                return False

            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            emoji_map = {
                "analysis": "🔍",
                "trade_open": "📈",
                "trade_close": "📊",
                "social": "🐦",
                "market": "🌍",
                "lesson": "📚",
                "discovery": "⚡",
            }
            emoji = emoji_map.get(note_type, "📝")
            title = f"{emoji} {ticker} — {timestamp}"

            await self.client.pages.create(
                parent={"page_id": brain_page_id},
                properties={
                    "title": {
                        "title": [{"text": {"content": title}}]
                    }
                },
                children=[
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": note}}]
                        },
                    }
                ],
            )
            logger.debug(f"Brain note written: {ticker} ({note_type})")
            return True

        except Exception as e:
            logger.error(f"Brain note write error: {e}")
            return False

    async def log_milestone(self, milestone: str, balance: float) -> None:
        """Log a portfolio milestone to the journal."""
        try:
            from datetime import datetime
            await self.add_journal_entry({
                "ticker": "PORTFOLIO",
                "type": "milestone",
                "note": milestone,
                "balance": balance,
                "date": datetime.now().strftime("%Y-%m-%d"),
            })
        except Exception as e:
            logger.debug(f"Milestone log error: {e}")


# Global singleton
notion_client = NotionClient()

"""
alerts/social_alerts.py
========================
Social media alert handler.

Bridges TwitterMonitor → AlertEngine.
Registers as callback, receives new posts,
and routes them through the full analysis pipeline.
"""

import logging as _logging; logger = _logging.getLogger(__name__)
from alerts.engine import alert_engine
from integrations.twitter_monitor import twitter_monitor


class SocialAlertHandler:
    """
    Handles the Twitter/X → Alert pipeline.
    """

    def __init__(self):
        self._registered = False

    def register_callbacks(self) -> None:
        """Register this handler with the Twitter monitor."""
        if not self._registered:
            twitter_monitor.add_callback(self._on_new_post)
            self._registered = True
            logger.info("Social alert handler registered with Twitter monitor")

    async def _on_new_post(self, account: str, post_text: str, post_data: dict) -> None:
        """
        Called by TwitterMonitor when a new post is detected.
        Routes to AlertEngine for full processing.
        """
        logger.info(f"Social alert handler received post from @{account}")
        await alert_engine.process_social_post(account, post_text, post_data)


# Singleton
social_alert_handler = SocialAlertHandler()

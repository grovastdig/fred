"""
integrations/twilio_client.py
==============================
Twilio SMS integration — Fred's voice.

Handles:
- Sending alerts to your phone
- Multi-part SMS for long messages
- Rate limiting (avoid spam)
- Message formatting for SMS constraints
- Delivery tracking
"""

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from datetime import datetime, timedelta
from typing import Optional
import logging as _logging; logger = _logging.getLogger(__name__)

from config.settings import settings


class TwilioClient:
    """
    SMS sender and receiver for Fred.
    Sends from Fred's dedicated Twilio number to your phone.
    """

    # SMS character limit per segment
    SMS_CHAR_LIMIT = 1600

    # Rate limiting — don't spam if same alert fires repeatedly
    _last_alert_times: dict = {}
    ALERT_COOLDOWN_SECONDS = 300  # 5 minutes between same alerts

    def __init__(self):
        self.client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        self.from_number = settings.twilio_phone_number
        self.to_number = settings.your_phone_number
        logger.info(f"Twilio client initialized — Fred's number: {self.from_number}")

    # ── Core Send ────────────────────────────────────────────────────────────

    def send(
        self,
        message: str,
        to: Optional[str] = None,
        force: bool = False,
        alert_key: Optional[str] = None,
    ) -> bool:
        """
        Send an SMS from Fred to your phone.

        Args:
            message: The message text
            to: Recipient phone (defaults to YOUR_PHONE_NUMBER)
            force: Skip rate limiting
            alert_key: Key for rate limiting (e.g. "stop_NVDA")
        """
        recipient = to or self.to_number

        # Rate limit check
        if not force and alert_key:
            if self._is_rate_limited(alert_key):
                logger.debug(f"Suppressed repeat alert: {alert_key}")
                return False

        # Clean and truncate message
        message = self._format_message(message)

        try:
            # Handle long messages — split into segments
            if len(message) > self.SMS_CHAR_LIMIT:
                return self._send_multipart(message, recipient, alert_key)

            msg = self.client.messages.create(
                body=message,
                from_=self.from_number,
                to=recipient,
            )

            if alert_key:
                self._record_alert_time(alert_key)

            logger.info(f"SMS sent to {recipient}: {message[:50]}... [SID: {msg.sid}]")
            return True

        except TwilioRestException as e:
            logger.error(f"Twilio send failed: {e}")
            return False
        except Exception as e:
            logger.error(f"SMS send error: {e}")
            return False

    def _send_multipart(self, message: str, recipient: str, alert_key: Optional[str]) -> bool:
        """Split long messages into multiple SMS segments."""
        # Split on paragraph breaks first, then by character limit
        segments = self._split_message(message, self.SMS_CHAR_LIMIT)

        success = True
        for i, segment in enumerate(segments):
            if len(segments) > 1:
                header = f"({i+1}/{len(segments)}) "
                segment = header + segment

            try:
                self.client.messages.create(
                    body=segment,
                    from_=self.from_number,
                    to=recipient,
                )
            except Exception as e:
                logger.error(f"Multipart segment {i+1} failed: {e}")
                success = False

        if alert_key and success:
            self._record_alert_time(alert_key)

        return success

    # ── Specialized Alert Senders ────────────────────────────────────────────

    def send_morning_brief(self, brief_text: str) -> bool:
        """Send the daily morning brief."""
        header = f"☀️ FRED MORNING BRIEF — {datetime.now().strftime('%a %b %d')}\n\n"
        return self.send(header + brief_text, force=True)

    def send_eod_debrief(self, debrief_text: str) -> bool:
        """Send end-of-day debrief."""
        header = f"🔔 EOD DEBRIEF — {datetime.now().strftime('%a %b %d')}\n\n"
        return self.send(header + debrief_text, force=True)

    def send_stop_alert(self, ticker: str, current_price: float, stop_price: float, urgency: str) -> bool:
        """Send a stop loss proximity alert."""
        pct_away = ((current_price - stop_price) / current_price) * 100
        emoji = "🚨" if urgency == "CRITICAL" else "⚠️"
        message = (
            f"{emoji} STOP ALERT: {ticker}\n"
            f"Current: ${current_price:.2f}\n"
            f"Stop: ${stop_price:.2f} ({pct_away:.1f}% away)\n"
            f"{'HIT STOP — EXIT NOW' if urgency == 'CRITICAL' else 'Getting close. Watch it.'}"
        )
        return self.send(message, alert_key=f"stop_{ticker}_{urgency}")

    def send_entry_signal(self, ticker: str, signal_summary: str) -> bool:
        """Send an entry signal alert."""
        message = f"📈 ENTRY SIGNAL: {ticker}\n\n{signal_summary}"
        return self.send(message, alert_key=f"entry_{ticker}")

    def send_target_alert(self, ticker: str, current_price: float, target: float) -> bool:
        """Alert when price target is reached."""
        message = (
            f"🎯 TARGET HIT: {ticker}\n"
            f"Price: ${current_price:.2f}\n"
            f"Target was: ${target:.2f}\n"
            f"Lock profits or trail your stop. Your call."
        )
        return self.send(message, alert_key=f"target_{ticker}")

    def send_social_alert(self, account: str, post_text: str, analysis: str, urgency: str) -> bool:
        """Alert on high-impact social media post."""
        emoji = "🚨" if urgency == "CRITICAL" else "📢"
        truncated_post = post_text[:150] + "..." if len(post_text) > 150 else post_text
        message = (
            f"{emoji} @{account} POSTED:\n"
            f'"{truncated_post}"\n\n'
            f"Fred's Take: {analysis}"
        )
        return self.send(message, alert_key=f"social_{account}_{hash(post_text[:50])}")

    def send_news_alert(self, headline: str, ticker: str, impact: str) -> bool:
        """Alert on market-moving news."""
        emoji = "📰" if impact == "MEDIUM" else "⚠️"
        message = (
            f"{emoji} NEWS ALERT — {ticker}\n"
            f"{headline}\n"
            f"Impact: {impact}\n"
            f"Check your {ticker} position."
        )
        return self.send(message, alert_key=f"news_{ticker}_{hash(headline[:30])}")

    def send_sunday_sync(self, sync_summary: str) -> bool:
        """Sunday evening portfolio sync message."""
        header = "🗓️ SUNDAY SYNC — Fred's Report\n\n"
        return self.send(header + sync_summary, force=True)

    def send_response(self, message: str, to: str) -> bool:
        """
        Send a response to an SMS that came in.
        Used by the webhook handler to reply to your texts.
        """
        return self.send(message, to=to, force=True)

    # ── Rate Limiting ─────────────────────────────────────────────────────────

    def _is_rate_limited(self, alert_key: str) -> bool:
        if alert_key not in self._last_alert_times:
            return False
        elapsed = (datetime.now() - self._last_alert_times[alert_key]).seconds
        return elapsed < self.ALERT_COOLDOWN_SECONDS

    def _record_alert_time(self, alert_key: str) -> None:
        self._last_alert_times[alert_key] = datetime.now()

    # ── Formatting ────────────────────────────────────────────────────────────

    def _format_message(self, message: str) -> str:
        """Clean message for SMS delivery."""
        # Remove excessive blank lines
        while "\n\n\n" in message:
            message = message.replace("\n\n\n", "\n\n")
        return message.strip()

    def _split_message(self, message: str, limit: int) -> list[str]:
        """Split a long message into SMS-sized chunks."""
        if len(message) <= limit:
            return [message]

        segments = []
        current = ""

        # Try splitting on double newlines (paragraphs) first
        paragraphs = message.split("\n\n")

        for para in paragraphs:
            if len(current) + len(para) + 2 <= limit:
                current += para + "\n\n"
            else:
                if current:
                    segments.append(current.strip())
                    current = ""
                # If single paragraph is too long, split by sentences
                if len(para) > limit:
                    sentences = para.split(". ")
                    for sentence in sentences:
                        if len(current) + len(sentence) + 2 <= limit:
                            current += sentence + ". "
                        else:
                            if current:
                                segments.append(current.strip())
                            current = sentence + ". "
                else:
                    current = para + "\n\n"

        if current:
            segments.append(current.strip())

        return segments if segments else [message[:limit]]


# Global singleton
twilio_client = TwilioClient()

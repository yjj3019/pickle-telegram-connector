"""Watchdog utilities for Pickle Telegram Connector.

Provides background typing indicators and stuck alert notifications
while long operations or host approvals are pending.
"""

import os
import sys
import time
from typing import Optional

from .client import TelegramClient


class Watchdog:
    """Manages typing activity and timeout notifications."""

    def __init__(self, client: Optional[TelegramClient] = None):
        self.client = client or TelegramClient()

    def keep_typing(
        self,
        chat_id: int,
        interval_seconds: int = 4,
        max_duration_seconds: int = 60
    ) -> None:
        """Keep typing indicator active for up to max_duration_seconds."""
        deadline = time.time() + max_duration_seconds
        while time.time() < deadline:
            self.client.send_chat_action(chat_id, "typing")
            time.sleep(interval_seconds)

    def alert_stuck(
        self,
        chat_id: int,
        message: str = "요청을 처리하고 있습니다. 승인 대기 중인 항목이 있다면 확인해 주세요."
    ) -> None:
        """Send a polite progress update if an errand is taking longer than expected."""
        self.client.send_message(chat_id, message)

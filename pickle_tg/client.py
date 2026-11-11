"""Telegram Bot API Client for Pickle Connector.

Implements high-efficiency HTTP communication with the Telegram Bot API using
pure Python 3 standard library components (urllib.request, json, mimetypes).
Zero external dependencies required.
"""

import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Union


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Strict security handler refusing HTTP redirects."""
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError("HTTP redirect refused by security policy; check endpoint URL.")


class TelegramClient:
    """Client for interacting with the Telegram Bot API."""

    def __init__(self, bot_token: Optional[str] = None):
        self.bot_token = (bot_token or self._resolve_token()).strip()
        if not self.bot_token:
            raise ValueError(
                "Bot token not found. Provide it directly or configure TELEGRAM_BOT_TOKEN / local.json."
            )
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.opener = urllib.request.build_opener(NoRedirectHandler())

    @staticmethod
    def _resolve_token() -> str:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if token:
            return token.strip()

        candidate_paths = [
            os.environ.get("TG_LOCAL_CONFIG"),
            "local.json",
            "telegram-relay/local.json",
            "/workspace/telegram-relay/local.json",
            os.path.expanduser("~/telegram-relay/local.json"),
            os.path.expanduser("~/workspace/telegram-relay/local.json"),
        ]
        for p in candidate_paths:
            if p and os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        val = data.get("bot_token")
                        if val:
                            return str(val).strip()
                except Exception:
                    pass
        return ""

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 40.0) -> Dict[str, Any]:
        """Execute a JSON POST request to the Telegram Bot API."""
        url = f"{self.base_url}/{method}"
        data = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                return json.loads(exc.read().decode("utf-8"))
            except Exception:
                return {"ok": False, "error_code": exc.code, "description": str(exc)}
        except Exception as exc:
            return {"ok": False, "description": str(exc)}

    def call_multipart(
        self,
        method: str,
        fields: Dict[str, Any],
        file_param: str,
        file_path: str,
        timeout: float = 60.0
    ) -> Dict[str, Any]:
        """Execute a multipart/form-data POST request for file uploads."""
        url = f"{self.base_url}/{method}"
        boundary = "----pickle-" + uuid.uuid4().hex
        body = bytearray()

        for key, value in fields.items():
            if value is None:
                continue
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            body.extend(str(value).encode("utf-8") + b"\r\n")

        filename = os.path.basename(file_path)
        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

        with open(file_path, "rb") as fh:
            file_bytes = fh.read()

        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{file_param}"; filename="{filename}"\r\n'.encode("utf-8")
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body.extend(file_bytes + b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        req = urllib.request.Request(url, data=bytes(body), method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

        try:
            with self.opener.open(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                return json.loads(exc.read().decode("utf-8"))
            except Exception:
                return {"ok": False, "error_code": exc.code, "description": str(exc)}
        except Exception as exc:
            return {"ok": False, "description": str(exc)}

    def get_me(self) -> Dict[str, Any]:
        """Fetch bot user information."""
        return self.call("getMe")

    def get_updates(
        self,
        offset: Optional[int] = None,
        limit: int = 100,
        timeout: int = 0,
        allowed_updates: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Receive incoming updates using long-polling or short queries."""
        params: Dict[str, Any] = {
            "limit": limit,
            "timeout": timeout,
            "allowed_updates": allowed_updates or ["message", "edited_message", "my_chat_member"]
        }
        if offset is not None:
            params["offset"] = offset
        return self.call("getUpdates", params, timeout=float(timeout + 20))

    def send_message(
        self,
        chat_id: Union[int, str],
        text: str,
        reply_to: Optional[int] = None,
        thread_id: Optional[int] = None,
        parse_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send a text message to a chat."""
        params: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text
        }
        if reply_to is not None:
            params["reply_parameters"] = {"message_id": reply_to}
        if thread_id is not None:
            params["message_thread_id"] = thread_id
        if parse_mode:
            params["parse_mode"] = parse_mode
        return self.call("sendMessage", params)

    def send_photo(
        self,
        chat_id: Union[int, str],
        photo_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[int] = None,
        thread_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Upload and send a local photo to a chat."""
        fields: Dict[str, Any] = {"chat_id": chat_id}
        if caption:
            fields["caption"] = caption
        if reply_to is not None:
            fields["reply_parameters"] = json.dumps({"message_id": reply_to}, ensure_ascii=False)
        if thread_id is not None:
            fields["message_thread_id"] = thread_id
        return self.call_multipart("sendPhoto", fields, "photo", photo_path)

    def send_chat_action(self, chat_id: Union[int, str], action: str = "typing") -> Dict[str, Any]:
        """Broadcast a chat action (typing, upload_photo, etc.)."""
        try:
            return self.call("sendChatAction", {"chat_id": chat_id, "action": action})
        except Exception:
            return {"ok": False}

    def set_reaction(
        self,
        chat_id: Union[int, str],
        message_id: int,
        emoji: str = "👀"
    ) -> Dict[str, Any]:
        """Set an emoji reaction on a message."""
        return self.call("setMessageReaction", {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}]
        })

    def get_chat(self, chat_id: Union[int, str]) -> Dict[str, Any]:
        """Get information about a chat."""
        return self.call("getChat", {"chat_id": chat_id})

    def set_webhook(
        self,
        url: str,
        secret_token: Optional[str] = None,
        drop_pending_updates: bool = False
    ) -> Dict[str, Any]:
        """Set up an HTTPS webhook endpoint for Telegram updates."""
        params: Dict[str, Any] = {
            "url": url,
            "allowed_updates": ["message", "edited_message", "my_chat_member"],
            "drop_pending_updates": drop_pending_updates
        }
        if secret_token:
            params["secret_token"] = secret_token
        return self.call("setWebhook", params)

    def get_webhook_info(self) -> Dict[str, Any]:
        """Get current webhook status."""
        return self.call("getWebhookInfo")

    def delete_webhook(self, drop_pending_updates: bool = False) -> Dict[str, Any]:
        """Delete configured webhook."""
        return self.call("deleteWebhook", {"drop_pending_updates": drop_pending_updates})

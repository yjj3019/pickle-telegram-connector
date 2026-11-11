"""Relay and queue storage management for Pickle Telegram Connector.

Handles message deduplication, persistence of getUpdates offset, queueing to
queue.jsonl, and authorization filtering (owner_ids, group_ids).
"""

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union


class RelayManager:
    """Manages queue files, state cursors, and access control."""

    def __init__(self, relay_dir: Optional[str] = None):
        self.relay_dir = (relay_dir or self._resolve_relay_dir())
        os.makedirs(self.relay_dir, exist_ok=True)

        self.state_file = os.path.join(self.relay_dir, "state.json")
        self.queue_file = os.path.join(self.relay_dir, "queue.jsonl")
        self.handled_file = os.path.join(self.relay_dir, "handled.txt")
        self.dropped_file = os.path.join(self.relay_dir, "dropped.log")
        self.config_file = os.path.join(self.relay_dir, "local.json")

        self.config = self.load_config()

    @staticmethod
    def _resolve_relay_dir() -> str:
        if os.environ.get("TG_RELAY_DIR"):
            return os.environ["TG_RELAY_DIR"]
        for candidate in [
            "telegram-relay",
            "/workspace/telegram-relay",
            os.path.expanduser("~/telegram-relay"),
            os.path.expanduser("~/workspace/telegram-relay"),
            "relay"
        ]:
            if os.path.exists(candidate):
                return os.path.abspath(candidate)
        return os.path.abspath("telegram-relay")

    def load_config(self) -> Dict[str, Any]:
        """Load local configuration (bot identity, allowed IDs)."""
        cfg: Dict[str, Any] = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass

        # Environment variable overrides
        if os.environ.get("TG_OWNER_IDS"):
            cfg["owner_ids"] = [
                int(x.strip()) for x in os.environ["TG_OWNER_IDS"].split(",") if x.strip().isdigit()
            ]
        if os.environ.get("TG_GROUP_IDS"):
            cfg["group_ids"] = [
                int(x.strip()) for x in os.environ["TG_GROUP_IDS"].split(",") if x.strip()
            ]
        if os.environ.get("TG_BOT_ID") and str(os.environ["TG_BOT_ID"]).isdigit():
            cfg["bot_id"] = int(os.environ["TG_BOT_ID"])
        if os.environ.get("TG_BOT_USERNAME"):
            cfg["bot_username"] = os.environ["TG_BOT_USERNAME"].strip().lstrip("@")

        return cfg

    def get_offset(self) -> Optional[int]:
        """Read latest processed update offset from state.json."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f).get("offset")
            except Exception:
                pass
        return None

    def set_offset(self, offset: int) -> None:
        """Persist processed update offset atomically."""
        tmp = self.state_file + f".tmp.{os.getpid()}"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"offset": offset, "updated_at": time.time()}, f)
            os.replace(tmp, self.state_file)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass

    def get_handled_keys(self) -> Set[str]:
        """Load set of handled message keys ('chat_id:message_id')."""
        if os.path.exists(self.handled_file):
            try:
                with open(self.handled_file, "r", encoding="utf-8") as f:
                    return {line.strip() for line in f if line.strip()}
            except Exception:
                pass
        return set()

    def mark_handled(self, chat_id: Union[int, str], message_id: int) -> None:
        """Record a message as handled."""
        key = f"{chat_id}:{message_id}"
        try:
            with open(self.handled_file, "a", encoding="utf-8") as f:
                f.write(f"{key}\n")
        except Exception:
            pass

    def is_authorized(self, update: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Check if an incoming update is permitted under security filters."""
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            if "my_chat_member" in update:
                return True, None
            return False, "no_message"

        chat = msg.get("chat", {})
        chat_type = chat.get("type")
        chat_id = chat.get("id")
        from_user = msg.get("from", {})
        from_id = from_user.get("id")

        owner_ids = self.config.get("owner_ids")
        group_ids = self.config.get("group_ids")

        if chat_type == "private":
            if owner_ids and from_id not in owner_ids:
                return False, f"unauthorized_private_sender:{from_id}"
            return True, None

        if chat_type in ("group", "supergroup"):
            if group_ids and chat_id not in group_ids:
                return False, f"unauthorized_group:{chat_id}"
            return True, None

        return True, None

    def enqueue_update(self, update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normalize update, apply security filters, and append to queue.jsonl."""
        authorized, reason = self.is_authorized(update)
        msg = update.get("message") or update.get("edited_message")
        if not authorized:
            if msg:
                try:
                    with open(self.dropped_file, "a", encoding="utf-8") as f:
                        f.write(json.dumps({
                            "time": time.time(),
                            "reason": reason,
                            "update_id": update.get("update_id"),
                            "chat_id": msg.get("chat", {}).get("id"),
                            "from_id": msg.get("from", {}).get("id"),
                            "text": msg.get("text", "")[:100]
                        }, ensure_ascii=False) + "\n")
                except Exception:
                    pass
            return None

        if not msg:
            return None

        chat = msg.get("chat", {})
        from_user = msg.get("from", {})

        record = {
            "update_id": update.get("update_id"),
            "received_at": time.time(),
            "chat_id": chat.get("id"),
            "chat_type": chat.get("type"),
            "chat_title": chat.get("title"),
            "thread_id": msg.get("message_thread_id"),
            "from": from_user.get("first_name") or from_user.get("username"),
            "from_username": from_user.get("username"),
            "from_id": from_user.get("id"),
            "from_is_bot": from_user.get("is_bot", False),
            "message_id": msg.get("message_id"),
            "text": msg.get("text") or msg.get("caption") or ""
        }

        try:
            with open(self.queue_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

        return record

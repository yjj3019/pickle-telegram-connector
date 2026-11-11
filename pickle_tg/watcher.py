"""High-performance 1-2s Low-Latency Watcher for Pickle Telegram Connector.

Leverages HTTP long-polling (Telegram getUpdates server-side wait) to hold an open
TCP connection. The moment Telegram receives a message from the user, it pushes the
payload down the wire within sub-seconds, achieving near-zero latency without
wasteful busy-polling loops.
"""

import fcntl
import json
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional

from .client import TelegramClient
from .relay import RelayManager


class Watcher:
    """Low-latency long-polling watcher engine with file lock and heartbeat."""

    def __init__(
        self,
        client: Optional[TelegramClient] = None,
        relay: Optional[RelayManager] = None,
        lock_path: Optional[str] = None,
        state_path: Optional[str] = None
    ):
        self.client = client or TelegramClient()
        self.relay = relay or RelayManager()

        self.lock_file = lock_path or os.path.join(self.relay.relay_dir, "watch.lock")
        self.heartbeat_file = state_path or os.path.join(self.relay.relay_dir, "watcher-state.json")
        self.lock_fd: Optional[int] = None

    def update_heartbeat(self, started_at: Optional[float] = None) -> None:
        """Write current timestamp to watcher-state.json for supervisor monitoring."""
        now = time.time()
        data = {
            "started_at": started_at or now,
            "beat_at": now,
            "pid": os.getpid()
        }
        tmp = self.heartbeat_file + f".tmp.{os.getpid()}"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.heartbeat_file)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass

    def acquire_lock(self, wait_seconds: int = 0) -> bool:
        """Acquire single-instance file lock using fcntl."""
        self.lock_fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR, 0o666)
        deadline = time.time() + wait_seconds

        while True:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except (BlockingIOError, OSError):
                if time.time() >= deadline:
                    return False
                time.sleep(0.5)

    def release_lock(self) -> None:
        """Release single-instance file lock."""
        if self.lock_fd is not None:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                os.close(self.lock_fd)
            except Exception:
                pass
            self.lock_fd = None

    def run_slice(
        self,
        slice_seconds: int = 600,
        wait_lock_seconds: int = 0,
        long_poll_timeout: int = 30
    ) -> Dict[str, Any]:
        """Run a single watch slice. Returns immediately when relevant updates arrive."""
        if not self.acquire_lock(wait_seconds=wait_lock_seconds):
            return {"status": "LOCKED", "items": []}

        started_at = time.time()
        self.update_heartbeat(started_at=started_at)
        deadline = started_at + slice_seconds

        try:
            while time.time() < deadline:
                self.update_heartbeat(started_at=started_at)
                current_offset = self.relay.get_offset()

                resp = self.client.get_updates(
                    offset=current_offset,
                    limit=50,
                    timeout=long_poll_timeout
                )

                if not resp.get("ok"):
                    return {
                        "status": "ERROR",
                        "description": resp.get("description", "Unknown error"),
                        "items": []
                    }

                updates = resp.get("result", [])
                if not updates:
                    continue

                relevant_items: List[Dict[str, Any]] = []
                max_update_id = 0

                for u in updates:
                    uid = u.get("update_id", 0)
                    if uid > max_update_id:
                        max_update_id = uid

                    record = self.relay.enqueue_update(u)
                    if record:
                        relevant_items.append(record)

                if max_update_id > 0:
                    self.relay.set_offset(max_update_id + 1)

                if relevant_items:
                    return {
                        "status": "RELEVANT",
                        "items": relevant_items
                    }

            return {"status": "NONE", "items": []}

        finally:
            self.release_lock()

    def run_forever(
        self,
        handler: Optional[Callable[[Dict[str, Any]], None]] = None,
        long_poll_timeout: int = 40
    ) -> None:
        """Run continuous daemon loop for systemd or container deployment."""
        if not self.acquire_lock(wait_seconds=10):
            print("[!] Could not acquire lock; another instance is running.", file=sys.stderr)
            sys.exit(1)

        print("[*] Pickle Telegram Watcher started in continuous mode.")
        started_at = time.time()
        consecutive_errors = 0

        try:
            while True:
                self.update_heartbeat(started_at=started_at)
                current_offset = self.relay.get_offset()

                try:
                    resp = self.client.get_updates(
                        offset=current_offset,
                        limit=50,
                        timeout=long_poll_timeout
                    )
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    sleep_time = min(30, 2 ** consecutive_errors)
                    print(f"[!] Error polling updates: {e}. Backing off {sleep_time}s...", file=sys.stderr)
                    time.sleep(sleep_time)
                    continue

                if not resp.get("ok"):
                    consecutive_errors += 1
                    sleep_time = min(30, 2 ** consecutive_errors)
                    print(f"[!] API returned error: {resp}. Backing off {sleep_time}s...", file=sys.stderr)
                    time.sleep(sleep_time)
                    continue

                updates = resp.get("result", [])
                max_update_id = 0

                for u in updates:
                    uid = u.get("update_id", 0)
                    if uid > max_update_id:
                        max_update_id = uid

                    record = self.relay.enqueue_update(u)
                    if record and handler:
                        try:
                            handler(record)
                        except Exception as h_err:
                            print(f"[!] Handler error: {h_err}", file=sys.stderr)

                if max_update_id > 0:
                    self.relay.set_offset(max_update_id + 1)

        finally:
            self.release_lock()

"""Supervisor and health monitoring for Pickle Telegram Watcher.

Allows cron jobs, system monitors, or scheduled actions to inspect watcher health,
detect hung workers, and trigger handover/restart cycles.
"""

import json
import os
import sys
import time
from typing import Any, Dict, Optional, Tuple


class Supervisor:
    """Monitors heartbeat, queue status, and lifecycle of the watcher process."""

    def __init__(self, relay_dir: Optional[str] = None):
        self.relay_dir = relay_dir or os.path.abspath("telegram-relay")
        self.heartbeat_file = os.path.join(self.relay_dir, "watcher-state.json")
        self.queue_file = os.path.join(self.relay_dir, "queue.jsonl")
        self.handled_file = os.path.join(self.relay_dir, "handled.txt")

    def inspect_status(
        self,
        stale_threshold_seconds: int = 180,
        term_limit_seconds: int = 3000
    ) -> Dict[str, Any]:
        """Inspect watcher operational state."""
        now = time.time()
        status: Dict[str, Any] = {
            "alive": False,
            "stale": False,
            "term_expired": False,
            "unhandled_count": 0,
            "heartbeat_age": None,
            "term_age": None,
            "pid": None
        }

        # Check queue
        handled = set()
        if os.path.exists(self.handled_file):
            try:
                with open(self.handled_file, "r", encoding="utf-8") as f:
                    handled = {l.strip() for l in f if l.strip()}
            except Exception:
                pass

        if os.path.exists(self.queue_file):
            try:
                with open(self.queue_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            item = json.loads(line)
                            k = f"{item.get('chat_id')}:{item.get('message_id')}"
                            if k not in handled:
                                status["unhandled_count"] += 1
                        except Exception:
                            pass
            except Exception:
                pass

        # Check heartbeat
        if os.path.exists(self.heartbeat_file):
            try:
                with open(self.heartbeat_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                started_at = data.get("started_at", 0)
                beat_at = data.get("beat_at", 0)
                status["pid"] = data.get("pid")

                h_age = max(0, now - beat_at)
                t_age = max(0, now - started_at)
                status["heartbeat_age"] = h_age
                status["term_age"] = t_age

                if h_age < stale_threshold_seconds:
                    status["alive"] = True
                else:
                    status["stale"] = True

                if t_age >= term_limit_seconds:
                    status["term_expired"] = True

            except Exception:
                status["stale"] = True

        return status

    def check_exit_code(self) -> int:
        """Returns 0 if action needed (unhandled msgs, dead/stale watcher), 1 if quiet."""
        status = self.inspect_status()
        if status["unhandled_count"] > 0:
            return 0
        if not status["alive"] or status["stale"] or status["term_expired"]:
            return 0
        return 1

"""Unified Command-Line Interface for Pickle Telegram Connector.

Provides a comprehensive set of subcommands for direct CLI execution,
script integration, daemon execution, and supervisor monitoring.
"""

import argparse
import json
import os
import sys
import time

from .auth import get_pickle_agent_card_spec, setup_interactive
from .client import TelegramClient
from .relay import RelayManager
from .supervisor import Supervisor
from .watcher import Watcher


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pickle Telegram Connector CLI"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # Core API commands
    sub.add_parser("get-me", help="Get bot identity")

    p_upd = sub.add_parser("get-updates", help="Query incoming updates directly")
    p_upd.add_argument("--offset", type=int, default=None)
    p_upd.add_argument("--timeout", type=int, default=0)
    p_upd.add_argument("--limit", type=int, default=100)

    p_send = sub.add_parser("send-message", help="Send a text message")
    p_send.add_argument("--chat-id", required=True, help="Target chat or user ID")
    p_send.add_argument("--text", required=True, help="Message text")
    p_send.add_argument("--reply-to", type=int, default=None, help="Message ID to reply to")
    p_send.add_argument("--thread-id", type=int, default=None, help="Thread ID (for forum topics)")
    p_send.add_argument("--typing", action="store_true", default=False, help="Show typing indicator")

    p_photo = sub.add_parser("send-photo", help="Upload and send a photo")
    p_photo.add_argument("--chat-id", required=True, help="Target chat ID")
    p_photo.add_argument("--photo", required=True, help="Path to image file")
    p_photo.add_argument("--caption", default=None, help="Photo caption")
    p_photo.add_argument("--reply-to", type=int, default=None, help="Reply message ID")

    p_react = sub.add_parser("react", help="Set emoji reaction on message")
    p_react.add_argument("--chat-id", required=True)
    p_react.add_argument("--message-id", type=int, required=True)
    p_react.add_argument("--emoji", default="👀")

    p_chat = sub.add_parser("get-chat", help="Get chat info")
    p_chat.add_argument("--chat-id", required=True)

    # Watcher & Relay commands
    p_watch = sub.add_parser("watch", help="Run low-latency watch slice")
    p_watch.add_argument("--slice", type=int, default=600, help="Slice duration in seconds")
    p_watch.add_argument("--wait-lock", type=int, default=0, help="Wait lock timeout in seconds")

    sub.add_parser("daemon", help="Run continuous watcher daemon for systemd/docker")

    sub.add_parser("fetch", help="One-shot update fetch to queue.jsonl")

    sub.add_parser("supervisor-check", help="Check watcher health (0=action needed, 1=quiet)")

    sub.add_parser("status", help="Print connector and queue health report")

    p_setup = sub.add_parser("setup", help="Securely input and validate bot token")
    p_setup.add_argument("--token", help="Direct token argument (optional)")
    p_setup.add_argument("--config", help="Target config file path")

    sub.add_parser("card-spec", help="Print Pickle Agent token card invocation spec")

    args = parser.parse_args()

    if args.cmd == "setup":
        res = setup_interactive(config_path=args.config, token_input=args.token)
        return 0 if res.get("ok") else 1

    elif args.cmd == "card-spec":
        spec = get_pickle_agent_card_spec()
        print(json.dumps(spec, ensure_ascii=False, indent=2))
        return 0

    client = TelegramClient()
    relay = RelayManager()

    if args.cmd == "get-me":
        res = client.get_me()
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1

    elif args.cmd == "get-updates":
        res = client.get_updates(offset=args.offset, limit=args.limit, timeout=args.timeout)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1

    elif args.cmd == "send-message":
        if args.typing:
            client.send_chat_action(args.chat_id, "typing")
            time.sleep(1)
        res = client.send_message(
            chat_id=args.chat_id,
            text=args.text,
            reply_to=args.reply_to,
            thread_id=args.thread_id
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1

    elif args.cmd == "send-photo":
        res = client.send_photo(
            chat_id=args.chat_id,
            photo_path=args.photo,
            caption=args.caption,
            reply_to=args.reply_to
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1

    elif args.cmd == "react":
        res = client.set_reaction(
            chat_id=args.chat_id,
            message_id=args.message_id,
            emoji=args.emoji
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1

    elif args.cmd == "get-chat":
        res = client.get_chat(chat_id=args.chat_id)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1

    elif args.cmd == "watch":
        watcher = Watcher(client=client, relay=relay)
        outcome = watcher.run_slice(
            slice_seconds=args.slice,
            wait_lock_seconds=args.wait_lock
        )
        status = outcome.get("status")
        items = outcome.get("items", [])
        if status == "RELEVANT":
            print(f"RELEVANT {len(items)}")
            for item in items:
                print(json.dumps(item, ensure_ascii=False))
            return 0
        elif status == "NONE":
            print("NONE")
            return 0
        elif status == "LOCKED":
            print("LOCKED")
            return 0
        else:
            print(f"ERROR: {outcome.get('description', 'Watch failed')}", file=sys.stderr)
            return 1

    elif args.cmd == "daemon":
        watcher = Watcher(client=client, relay=relay)
        def default_handler(item):
            print(f"[+] Message received from {item.get('from')}: {item.get('text')}")
        watcher.run_forever(handler=default_handler)
        return 0

    elif args.cmd == "fetch":
        current_offset = relay.get_offset()
        resp = client.get_updates(offset=current_offset, timeout=0)
        if not resp.get("ok"):
            print(f"ERROR: {resp.get('description')}", file=sys.stderr)
            return 1

        updates = resp.get("result", [])
        if not updates:
            print("NONE")
            return 0

        relevant = []
        max_id = 0
        for u in updates:
            uid = u.get("update_id", 0)
            if uid > max_id:
                max_id = uid
            rec = relay.enqueue_update(u)
            if rec:
                relevant.append(rec)

        if max_id > 0:
            relay.set_offset(max_id + 1)

        if relevant:
            print(f"RELEVANT {len(relevant)}")
            for r in relevant:
                print(json.dumps(r, ensure_ascii=False))
        else:
            print("NONE")
        return 0

    elif args.cmd == "supervisor-check":
        sup = Supervisor(relay_dir=relay.relay_dir)
        code = sup.check_exit_code()
        st = sup.inspect_status()
        if code == 0:
            print(f"fired: unhandled={st['unhandled_count']}, alive={st['alive']}, stale={st['stale']}")
        else:
            print("quiet")
        return code

    elif args.cmd == "status":
        sup = Supervisor(relay_dir=relay.relay_dir)
        st = sup.inspect_status()
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())

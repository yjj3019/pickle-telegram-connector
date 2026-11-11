"""Secure Credential Management & Agent Setup Card Specification.

Provides secure token ingestion routines for both standalone Linux CLI
(using masked getpass) and Pickle AI Agent conversational interfaces
(using the single-field OTP token card pattern).
"""

import getpass
import json
import os
import stat
import sys
from typing import Any, Dict, Optional

from .client import TelegramClient


def get_pickle_agent_card_spec() -> Dict[str, Any]:
    """Returns the Pickle Agent tool call specification for the secure token card.

    In the Pickle AI agent runtime, plaintext API tokens must never be sent
    or received through open chat text. Instead, the agent invokes `ask_user`
    with `kind='otp'` and `service='Telegram Bot Token'`. This opens a native
    single-field secure input card in the user's app UI, routing the credential
    directly into the secure enclave.
    """
    return {
        "tool": "ask_user",
        "parameters": {
            "kind": "otp",
            "service": "Telegram Bot Token",
            "question": "안전한 텔레그램 연동을 위해 BotFather에게 발급받은 봇 토큰(HTTP API Token)을 입력해 주세요. (보안 입력창으로 안전하게 전달됩니다)"
        }
    }


def setup_interactive(
    config_path: Optional[str] = None,
    token_input: Optional[str] = None
) -> Dict[str, Any]:
    """Interactively prompt for Telegram Bot Token securely and validate via getMe."""
    target_path = config_path or os.path.abspath("telegram-relay/local.json")
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    token = token_input
    if not token:
        print("[*] Telegram Bot Token Setup (Secure Input)")
        print("    Token will be masked and validated against api.telegram.org.")
        try:
            token = getpass.getpass("Enter Bot Token: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[!] Setup aborted.")
            sys.exit(1)

    if not token:
        print("[-] Error: Token cannot be empty.", file=sys.stderr)
        return {"ok": False, "error": "empty_token"}

    print("[*] Validating token with Telegram Bot API...")
    try:
        client = TelegramClient(bot_token=token)
        res = client.get_me()
    except Exception as e:
        print(f"[-] Validation failed: {e}", file=sys.stderr)
        return {"ok": False, "error": str(e)}

    if not res.get("ok"):
        print(f"[-] Telegram rejected the token: {res.get('description')}", file=sys.stderr)
        return {"ok": False, "error": res.get("description")}

    bot_info = res["result"]
    bot_id = bot_info["id"]
    bot_username = bot_info.get("username", "")
    bot_name = bot_info.get("first_name", "")

    print(f"[✓] Token valid! Connected as @{bot_username} ({bot_name}, ID: {bot_id})")

    # Read existing owner_ids if present
    owner_ids = []
    if os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                owner_ids = old_data.get("owner_ids", [])
        except Exception:
            pass

    config_data = {
        "bot_token": token,
        "bot_id": bot_id,
        "bot_username": bot_username,
        "owner_ids": owner_ids or [],
        "group_ids": []
    }

    tmp_path = target_path + f".tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)

    # Secure permissions: only owner can read/write (0600)
    os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp_path, target_path)

    print(f"[✓] Secure configuration saved to: {target_path} (mode: 0600)")
    return {
        "ok": True,
        "bot_id": bot_id,
        "bot_username": bot_username,
        "config_path": target_path
    }

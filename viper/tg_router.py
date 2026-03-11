"""Viper TG Router — routes messages to INBOUND or OUTREACH channels.

Two channel types:
  INBOUND  — Pipeline 2 (job scanner leads)
  OUTREACH — Pipeline 1 (prospector/outreach approval)

Reads VIPER_INBOUND_CHAT_ID / VIPER_OUTREACH_CHAT_ID from env.
Fallback: single TELEGRAM_CHAT_ID with [INBOUND]/[OUTREACH] prefix.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# Load TG credentials
_TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
_INBOUND_CHAT_ID = os.getenv("VIPER_INBOUND_CHAT_ID", "")
_OUTREACH_CHAT_ID = os.getenv("VIPER_OUTREACH_CHAT_ID", "")

if not _TG_TOKEN:
    _shelby_env = Path.home() / "shelby" / ".env"
    if _shelby_env.exists():
        for line in _shelby_env.read_text().splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                _TG_TOKEN = line.split("=", 1)[1].strip()
            elif line.startswith("TELEGRAM_CHAT_ID="):
                _TG_CHAT_ID = line.split("=", 1)[1].strip()
            elif line.startswith("VIPER_INBOUND_CHAT_ID="):
                _INBOUND_CHAT_ID = line.split("=", 1)[1].strip()
            elif line.startswith("VIPER_OUTREACH_CHAT_ID="):
                _OUTREACH_CHAT_ID = line.split("=", 1)[1].strip()


def _resolve_chat_id(channel: str) -> tuple[str, str]:
    """Return (chat_id, prefix) for the given channel type.

    If dedicated channel IDs are set, use them (no prefix needed).
    Otherwise fallback to single chat with prefix label.
    """
    if channel == "INBOUND" and _INBOUND_CHAT_ID:
        return _INBOUND_CHAT_ID, ""
    if channel == "OUTREACH" and _OUTREACH_CHAT_ID:
        return _OUTREACH_CHAT_ID, ""
    # Fallback: single channel with prefix
    return _TG_CHAT_ID, f"[{channel}] "


def send(
    text: str,
    channel: str = "INBOUND",
    buttons: list[list[dict]] | None = None,
) -> bool:
    """Send a Telegram message to the appropriate Viper channel.

    Args:
        text: HTML-formatted message text.
        channel: "INBOUND" or "OUTREACH".
        buttons: Optional inline keyboard buttons.
    """
    if not _TG_TOKEN:
        log.warning("[TG_ROUTER] No TELEGRAM_BOT_TOKEN configured")
        return False

    chat_id, prefix = _resolve_chat_id(channel)
    if not chat_id:
        log.warning("[TG_ROUTER] No chat_id for channel %s", channel)
        return False

    full_text = f"{prefix}{text}" if prefix else text

    url = f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage"
    payload: dict = {
        "chat_id": chat_id,
        "text": full_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True
        log.error("[TG_ROUTER] API error %d: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        log.error("[TG_ROUTER] Send failed: %s", e)
        return False

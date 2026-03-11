"""Viper Telegram alerts — sends job leads and summaries to Jordan."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# Load TG credentials from env or Shelby's .env
_TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

if not _TG_TOKEN:
    _shelby_env = Path.home() / "shelby" / ".env"
    if _shelby_env.exists():
        for line in _shelby_env.read_text().splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                _TG_TOKEN = line.split("=", 1)[1].strip()
            elif line.startswith("TELEGRAM_CHAT_ID="):
                _TG_CHAT_ID = line.split("=", 1)[1].strip()


def _send_tg(text: str, buttons: list[list[dict]] | None = None) -> bool:
    """Send a Telegram message with optional inline keyboard."""
    if not _TG_TOKEN or not _TG_CHAT_ID:
        log.warning("[TG] Credentials not configured")
        return False

    url = f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage"
    payload: dict = {
        "chat_id": _TG_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True
        log.error("[TG] API error %d: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        log.error("[TG] Send failed: %s", e)
        return False


def send_job_alert(
    title: str,
    source: str,
    category: str,
    skills: list[str],
    budget: str,
    url: str,
    score: int,
    bid_count: int | None = None,
    description: str = "",
    suggested_bid: str = "",
    suggested_delivery: str = "",
    client_country: str = "",
    job_hash: str = "",
) -> bool:
    """Send a job lead alert to Jordan's TG with BID/SKIP buttons."""
    skills_str = ", ".join(skills[:6]) if skills else "—"
    bid_str = f"\nBids: {bid_count}" if bid_count is not None else ""
    country_str = f"\nClient: {client_country}" if client_country else ""
    budget_str = f"\nBudget: {budget}" if budget else ""
    bid_suggest = f"\nSuggested bid: {suggested_bid}" if suggested_bid else ""
    delivery_str = f"\nDelivery: {suggested_delivery}" if suggested_delivery else ""

    # Truncate description
    desc_preview = description[:200].replace("<", "&lt;").replace(">", "&gt;") if description else ""
    desc_block = f"\n\n{desc_preview}..." if desc_preview else ""

    text = (
        f"<b>VIPER LEAD — {source}</b>\n\n"
        f"<b>{title[:100]}</b>\n"
        f"Category: {category}\n"
        f"Skills: {skills_str}\n"
        f"Score: {score}/100"
        f"{budget_str}{bid_str}{country_str}"
        f"{bid_suggest}{delivery_str}"
        f"{desc_block}\n\n"
        f"<a href=\"{url}\">View posting</a>"
    )

    buttons = [
        [
            {"text": "BID", "callback_data": f"viper_bid:{job_hash[:20]}"},
            {"text": "SKIP", "callback_data": f"viper_skip:{job_hash[:20]}"},
        ],
    ]

    return _send_tg(text, buttons)


def send_summary(total_scanned: int, new_matches: int, alerts_sent: int) -> bool:
    """Send end-of-cycle summary."""
    text = (
        f"<b>Viper Scan Complete</b>\n\n"
        f"Scanned: {total_scanned}\n"
        f"Matches (score 70+): {new_matches}\n"
        f"Alerts sent: {alerts_sent}"
    )
    return _send_tg(text)

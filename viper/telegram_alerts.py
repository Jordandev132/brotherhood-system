"""Viper Telegram alerts — sends job leads and summaries to Jordan.

Uses tg_router for channel routing (INBOUND channel for Pipeline 2 leads).
"""
from __future__ import annotations

import logging

from viper.tg_router import send as tg_send

log = logging.getLogger(__name__)

# Source emoji map
_SOURCE_EMOJI = {
    "HackerNews": "Y",
    "GoogleAlerts": "G",
    "Reddit": "R",
    "IndieHackers": "IH",
    "ProductHunt": "PH",
    "n8n_community": "n8n",
    "Make_community": "Make",
    "RemoteOK": "ROK",
    "WeWorkRemotely": "WWR",
}


def _score_bar(score: int) -> str:
    """Build a visual score bar like ████████░░ 85/100."""
    filled = score // 10
    empty = 10 - filled
    return "\u2588" * filled + "\u2591" * empty + f" {score}/100"


def _skill_tags(skills: list[str]) -> str:
    """Build hashtag string from skills like #chatbot #automation #ai."""
    if not skills:
        return ""
    return " ".join(f"#{s.replace(' ', '_')}" for s in skills[:5])


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
    """Send a clean, compact job lead alert to Jordan's TG with BID/SKIP."""
    source_tag = _SOURCE_EMOJI.get(source, source)
    score_bar = _score_bar(score)
    tags = _skill_tags(skills)

    # Budget line
    budget_line = f"Budget: {budget}" if budget else ""

    # Description preview (150 chars)
    desc_clean = description[:150].replace("<", "&lt;").replace(">", "&gt;") if description else ""
    desc_line = f"{desc_clean}..." if desc_clean else ""

    # Build the compact message
    lines = [
        f"<b>{source_tag} | {title[:100]}</b>",
        f"<code>{score_bar}</code>",
    ]
    if tags:
        lines.append(tags)
    if budget_line:
        lines.append(budget_line)
    lines.append("")
    if desc_line:
        lines.append(desc_line)
        lines.append("")
    lines.append(f'<a href="{url}">Open</a>')

    text = "\n".join(lines)

    buttons = [
        [
            {"text": "BID", "callback_data": f"viper_bid:{job_hash[:20]}"},
            {"text": "SKIP", "callback_data": f"viper_skip:{job_hash[:20]}"},
        ],
    ]

    return tg_send(text, channel="INBOUND", buttons=buttons)


def send_summary(total_scanned: int, new_matches: int, alerts_sent: int) -> bool:
    """Send end-of-cycle summary."""
    text = (
        f"<b>Viper Scan Complete</b>\n\n"
        f"Scanned: {total_scanned}\n"
        f"Matches (score 70+): {new_matches}\n"
        f"Alerts sent: {alerts_sent}"
    )
    return tg_send(text, channel="INBOUND")

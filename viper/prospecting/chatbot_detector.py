"""Detect existing chat widgets on a business website.

Three-tier confidence system:
    DETECTED  — known widget found → auto-skip, don't send outreach
    NOT_FOUND — clean scan, sufficient HTML → auto-send outreach
    UNCERTAIN — blocked, JS-heavy, or scan incomplete → flag for Jordan
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Minimum HTML bytes for a confident "not found" verdict.
# Pages shorter than this are likely JS-rendered shells or blocked responses.
_MIN_HTML_FOR_CLEAN = 2000

# Signals that the page blocked us or is a JS shell
_BLOCK_SIGNALS = [
    "access denied",
    "403 forbidden",
    "just a moment",        # Cloudflare challenge
    "checking your browser",
    "enable javascript",
    "please enable cookies",
    "captcha",
    "cf-browser-verification",
    "ray id",               # Cloudflare
]

_SIGNATURES: list[tuple[str, list[str]]] = [
    ("Intercom", ["intercom", "widget.intercom.io", "intercomSettings"]),
    ("Drift", ["drift.com", "driftt.com", "drift-widget"]),
    ("Tawk.to", ["tawk.to", "embed.tawk.to"]),
    ("Tidio", ["tidio", "tidioChatCode", "code.tidio.co"]),
    ("LiveChat", ["livechatinc.com", "cdn.livechatinc.com", "__lc_inited"]),
    ("Zendesk Chat", ["zopim", "zendesk.com/embeddable", "zdassets.com"]),
    ("Freshchat", ["freshchat", "wchat.freshchat.com"]),
    ("Crisp", ["crisp.chat", "client.crisp.chat"]),
    ("HubSpot Chat", ["hubspot.com/conversations", "js.hs-scripts.com", "hbspt"]),
    ("Olark", ["olark", "static.olark.com"]),
    ("Chatwoot", ["chatwoot", "app.chatwoot.com"]),
    ("Botpress", ["botpress", "cdn.botpress.cloud"]),
    ("ManyChat", ["manychat", "mcwidget"]),
    ("Landbot", ["landbot", "cdn.landbot.io"]),
]


class Confidence(Enum):
    """Three-tier chatbot detection confidence."""
    DETECTED = "DETECTED"       # known widget found → auto-skip
    NOT_FOUND = "NOT_FOUND"     # clean scan → auto-send
    UNCERTAIN = "UNCERTAIN"     # can't tell → Jordan reviews


@dataclass
class ChatbotDetectionResult:
    """Result of chatbot presence detection."""
    has_chatbot: bool = False
    chatbot_name: str = ""
    confidence: Confidence = Confidence.UNCERTAIN
    reason: str = ""


def detect_chatbot(html: str) -> ChatbotDetectionResult:
    """Detect chatbot widgets via string matching on raw HTML.

    Returns one of three outcomes:
        DETECTED  — known widget signature matched
        NOT_FOUND — clean HTML, no widgets, no blocking signals
        UNCERTAIN — empty/tiny HTML, blocked page, or JS-rendered shell
    """
    # No HTML at all → scrape failed
    if not html:
        return ChatbotDetectionResult(
            confidence=Confidence.UNCERTAIN,
            reason="no HTML received (scrape failed or site unreachable)",
        )

    html_lower = html.lower()

    # Check for known widget signatures first
    for name, markers in _SIGNATURES:
        for marker in markers:
            if marker.lower() in html_lower:
                return ChatbotDetectionResult(
                    has_chatbot=True,
                    chatbot_name=name,
                    confidence=Confidence.DETECTED,
                    reason=f"matched signature: {marker}",
                )

    # No widget found — but can we trust the scan?

    # Check if page blocked us
    block_hits = [sig for sig in _BLOCK_SIGNALS if sig in html_lower]
    if block_hits:
        return ChatbotDetectionResult(
            confidence=Confidence.UNCERTAIN,
            reason=f"page may have blocked scraping ({block_hits[0]})",
        )

    # Check if HTML is too short (JS-rendered shell)
    if len(html) < _MIN_HTML_FOR_CLEAN:
        return ChatbotDetectionResult(
            confidence=Confidence.UNCERTAIN,
            reason=f"HTML too short ({len(html)} bytes) — likely JS-rendered",
        )

    # Clean scan — enough HTML, no blocks, no widgets
    return ChatbotDetectionResult(
        has_chatbot=False,
        confidence=Confidence.NOT_FOUND,
        reason="clean scan, no chat widgets detected",
    )

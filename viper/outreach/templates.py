"""Niche-personalized cold outreach templates for local business prospecting.

Rules:
- Sound human, not robotic. Write like a real person, not a template.
- Lead with THEIR problem, not our product.
- Video previews (mobile + desktop) in EVERY email.
- Demo link in every email — it's the hook.
- Short. Scannable. Every sentence earns the next.
- NO pitching SEO/content writing in cold emails.
"""
from __future__ import annotations

_DEMO_BASE = "https://darkcode-ai.github.io/chatbot-demos/"

# Verified demo slugs — these return 200 on GitHub Pages
_DEMO_SLUGS = {
    "dental": "dental-demo",
    "real_estate": "realestate-demo",
}


def get_outreach_message(
    niche: str,
    business_name: str,
    demo_url: str,
    contact_name: str = "",
    findings: str = "",
) -> dict[str, str]:
    """Return personalized subject + body for a niche.

    Returns dict with 'subject' and 'body' keys (plain text).
    """
    greeting = f"Hi {contact_name}" if contact_name else "Hi"
    niche_key = resolve_niche_key(niche) if niche not in _TEMPLATES else niche
    template = _TEMPLATES.get(niche_key, _TEMPLATES["general"])

    findings_block = ""
    if findings:
        findings_block = (
            f"I took a look at {business_name}'s website and noticed "
            f"a few things:\n\n{findings}\n\n"
        )

    # Video block for every niche — uses the demo_url to build video paths
    video_block = (
        "Here's a 30-second walkthrough so you can see it in action:\n"
        f"  Horizontal: {demo_url}videos/desktop-preview.mp4\n"
        f"  Vertical: {demo_url}videos/mobile-preview.mp4\n"
    )

    return {
        "subject": template["subject"].format(business_name=business_name),
        "body": template["body"].format(
            greeting=greeting,
            business_name=business_name,
            demo_url=demo_url,
            findings=findings_block,
            video_block=video_block,
        ),
    }


_TEMPLATES: dict[str, dict[str, str]] = {
    "dental": {
        "subject": "I built something for {business_name} — 2 min to check out",
        "body": (
            "{greeting},\n\n"
            "{findings}"
            "I know this sounds forward, but I actually built a working chat "
            "assistant specifically for dental practices like {business_name}.\n\n"
            "It handles the stuff that eats up your front desk's time — "
            "insurance questions, appointment requests, hours, which dentist "
            "handles what. Works 24/7, even when you're closed.\n\n"
            "Here's the live demo (takes 30 seconds to try):\n"
            "{demo_url}\n\n"
            "{video_block}\n"
            "If you're curious, just reply to this email. I'll build a custom "
            "version for {business_name} within 24 hours — free, no strings.\n\n"
            "Jordan\n"
            "DarkCode AI\n"
            "darkcodeai.carrd.co"
        ),
    },
    "real_estate": {
        "subject": "Built this for {business_name} — worth 30 seconds",
        "body": (
            "{greeting},\n\n"
            "{findings}"
            "Someone's browsing your listings at 11 PM. They have questions "
            "about the neighborhood, the HOA, whether you handle rentals too. "
            "They're not going to wait until morning — they'll move on.\n\n"
            "I built a chat assistant that handles those conversations, "
            "answers property questions, and captures their info before "
            "they disappear. It's trained on YOUR listings and services.\n\n"
            "Here's a working demo:\n"
            "{demo_url}\n\n"
            "{video_block}\n"
            "Reply if you want me to build one for {business_name}. Takes "
            "me 24 hours, costs you nothing to try.\n\n"
            "Jordan\n"
            "DarkCode AI\n"
            "darkcodeai.carrd.co"
        ),
    },
    "chiropractor": {
        "subject": "Quick idea for {business_name}",
        "body": (
            "{greeting},\n\n"
            "{findings}"
            "When someone's back goes out at 9 PM, they're Googling "
            "chiropractors right then. If your site can't answer their "
            "questions and book them in, they'll call whoever can.\n\n"
            "I built a chat assistant that handles insurance questions, "
            "explains your treatments in plain English, and books "
            "appointments — even at 2 AM.\n\n"
            "Here's a working demo:\n"
            "{demo_url}\n\n"
            "{video_block}\n"
            "Want me to build one for {business_name}? Reply and I'll "
            "have a custom version ready in 24 hours. Free to try.\n\n"
            "Jordan\n"
            "DarkCode AI\n"
            "darkcodeai.carrd.co"
        ),
    },
    "auto_repair": {
        "subject": "Quick idea for {business_name}",
        "body": (
            "{greeting},\n\n"
            "{findings}"
            "When someone's car breaks down, they need answers NOW — "
            "not a voicemail. What services you offer, rough pricing, "
            "whether you can fit them in today.\n\n"
            "I built a chat assistant that handles all of that. Answers "
            "service questions, gives estimate ranges, books appointments "
            "on the spot. Works 24/7.\n\n"
            "Here's a working demo:\n"
            "{demo_url}\n\n"
            "{video_block}\n"
            "Interested? Reply and I'll build a custom version for "
            "{business_name}. 24 hours, no cost to try.\n\n"
            "Jordan\n"
            "DarkCode AI\n"
            "darkcodeai.carrd.co"
        ),
    },
    "general": {
        "subject": "I built something for {business_name}",
        "body": (
            "{greeting},\n\n"
            "{findings}"
            "I noticed {business_name} doesn't have a chat assistant on "
            "the site yet — so I went ahead and built a working demo.\n\n"
            "It handles common questions, books appointments, and captures "
            "visitor info when you're not around. Basically a front desk "
            "that never sleeps.\n\n"
            "Here's the live demo (takes 30 seconds):\n"
            "{demo_url}\n\n"
            "{video_block}\n"
            "Worth a look? Reply and I'll customize it for "
            "{business_name} in 24 hours. Free, no strings.\n\n"
            "Jordan\n"
            "DarkCode AI\n"
            "darkcodeai.carrd.co"
        ),
    },
}

# Map common niche search terms to template keys
NICHE_MAP: dict[str, str] = {
    "dental practice": "dental",
    "dental office": "dental",
    "dentist": "dental",
    "orthodontist": "dental",
    "pediatric dentist": "dental",
    "real estate": "real_estate",
    "realtor": "real_estate",
    "real estate agent": "real_estate",
    "real estate agency": "real_estate",
    "chiropractor": "chiropractor",
    "chiropractic": "chiropractor",
    "auto repair": "auto_repair",
    "auto shop": "auto_repair",
    "mechanic": "auto_repair",
    "car repair": "auto_repair",
}


def resolve_niche_key(niche_query: str) -> str:
    """Map a search query niche to a template key."""
    return NICHE_MAP.get(niche_query.lower(), "general")


# ── Forum Reply Templates ──
# For community leads (Make.com, n8n, Reddit, etc.)
# Short, casual, demo-first. No pitch, no pricing.
# Jordan copy-pastes into the forum thread manually.

_FORUM_TEMPLATES: dict[str, str] = {
    "automation": (
        "Hey — I build exactly this type of automation. "
        "Here's a working demo of something similar I put together: {demo_url}\n\n"
        "DM me if you want to talk details."
    ),
    "chatbot": (
        "Hey — I build custom chatbots like this. "
        "Here's a live demo you can try right now: {demo_url}\n\n"
        "DM me if you want to talk details."
    ),
    "general": (
        "Hey — I've built something similar. "
        "Here's a working demo: {demo_url}\n\n"
        "DM me if you want to talk details."
    ),
}

_FORUM_TYPE_KEYWORDS: dict[str, list[str]] = {
    "automation": [
        "automation", "workflow", "n8n", "make.com", "zapier",
        "integrate", "api", "trigger",
    ],
    "chatbot": [
        "chatbot", "chat bot", "assistant", "widget",
        "customer support", "faq bot", "ai bot",
    ],
}


def get_forum_reply(
    post_context: str = "",
    demo_url: str = "https://darkcode-ai.github.io/chatbot-demos/belknapdental-com/",
    reply_type: str = "",
) -> str:
    """Generate a short forum reply for community leads.

    Args:
        post_context: Original forum post text (used for type detection).
        demo_url: Demo link to include.
        reply_type: Force a type ("automation", "chatbot", "general").
                    If empty, auto-detects from post_context.

    Returns:
        Ready-to-paste forum reply string.
    """
    if not reply_type and post_context:
        post_lower = post_context.lower()
        for rtype, keywords in _FORUM_TYPE_KEYWORDS.items():
            if any(kw in post_lower for kw in keywords):
                reply_type = rtype
                break

    if not reply_type:
        reply_type = "general"

    template = _FORUM_TEMPLATES.get(reply_type, _FORUM_TEMPLATES["general"])
    return template.format(demo_url=demo_url)

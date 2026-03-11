"""Niche-personalized cold outreach templates for local business prospecting.

Rules:
- Sound human, not robotic. Write like a real person, not a template.
- Lead with THEIR problem, not our product.
- Video links ONLY for niches with verified videos (real_estate).
- Demo link in every email — it's the hook.
- Mention SEO/content writing as bonus value.
- Short. Scannable. Every sentence earns the next.
"""
from __future__ import annotations


def get_outreach_message(
    niche: str,
    business_name: str,
    demo_url: str,
    contact_name: str = "",
    findings: str = "",
) -> dict[str, str]:
    """Return personalized subject + body for a niche.

    Args:
        findings: Pre-formatted audit findings string (bulleted list).
                  Injected into the email body via {findings} placeholder.

    Returns dict with 'subject' and 'body' keys (plain text).
    """
    greeting = f"Hi {contact_name}" if contact_name else "Hi"
    template = _TEMPLATES.get(niche.lower(), _TEMPLATES["general"])

    # Build findings block — only if we have actual findings
    findings_block = ""
    if findings:
        findings_block = (
            f"I took a look at {business_name}'s website and noticed "
            f"a few things:\n\n{findings}\n\n"
        )

    # Video block — only for niches with verified videos
    video_block = ""
    if niche.lower() in _VIDEO_NICHES:
        video_block = _VIDEO_NICHES[niche.lower()].format(demo_url=demo_url)

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


# Video preview blocks — ONLY niches with verified working mp4s
_VIDEO_NICHES: dict[str, str] = {
    "real_estate": (
        "\nHere's a 30-second walkthrough so you can see it in action:\n"
        "  Mobile: {demo_url}videos/mobile-preview.mp4\n"
        "  Desktop: {demo_url}videos/desktop-preview.mp4\n"
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
            "I also do SEO and content writing for dental practices — "
            "blog posts that actually rank, Google Business optimization, "
            "the stuff that gets new patients finding you online.\n\n"
            "If you're curious, just reply to this email. I'll build a custom "
            "version for {business_name} in 24 hours — free, no strings.\n\n"
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
            "{demo_url}\n"
            "{video_block}\n"
            "I also handle SEO and content for real estate — neighborhood "
            "guides, market update blogs, the content that gets you ranking "
            "above the Zillows and Redfins for local searches.\n\n"
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
            "I also write content that ranks — treatment pages, blog posts "
            "about common conditions, the stuff that brings in organic "
            "traffic without paying for ads.\n\n"
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
            "I also do SEO for auto shops — getting you ranking for "
            "'brake repair near me', 'oil change [your city]', the "
            "searches that bring in real customers.\n\n"
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
            "I also handle SEO and content writing — blog posts, landing "
            "pages, Google Business optimization. The stuff that brings "
            "in organic traffic without ad spend.\n\n"
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

"""Niche-personalized cold outreach templates for local business prospecting."""
from __future__ import annotations


def get_outreach_message(
    niche: str,
    business_name: str,
    demo_url: str,
    contact_name: str = "",
) -> dict[str, str]:
    """Return personalized subject + body for a niche.

    Returns dict with 'subject' and 'body' keys (plain text).
    """
    greeting = f"Hi {contact_name}" if contact_name else "Hi there"
    template = _TEMPLATES.get(niche.lower(), _TEMPLATES["general"])
    return {
        "subject": template["subject"].format(business_name=business_name),
        "body": template["body"].format(
            greeting=greeting,
            business_name=business_name,
            demo_url=demo_url,
        ),
    }


_TEMPLATES: dict[str, dict[str, str]] = {
    "dental": {
        "subject": "Built something for {business_name} — 24/7 patient booking",
        "body": (
            "{greeting},\n\n"
            "Your front desk can't answer calls after hours. "
            "I built something that can:\n\n"
            "{demo_url}\n\n"
            "It handles the #1 question dental patients ask — insurance — "
            "plus appointment booking, hours, and doctor availability. "
            "24/7, no hold time, no missed calls.\n\n"
            "Built specifically for {business_name}. Free to try.\n\n"
            "— DarkCode AI"
        ),
    },
    "real_estate": {
        "subject": "Built something for {business_name} — instant property answers",
        "body": (
            "{greeting},\n\n"
            "Buyers browsing your listings at 11 PM have questions. "
            "I built something that answers them instantly:\n\n"
            "{demo_url}\n\n"
            "It handles property details, scheduling showings, neighborhood info, "
            "and captures leads — all while you sleep. "
            "No more losing buyers to agents who respond faster.\n\n"
            "Built specifically for {business_name}. Free to try.\n\n"
            "— DarkCode AI"
        ),
    },
    "chiropractor": {
        "subject": "Built something for {business_name} — 24/7 patient intake",
        "body": (
            "{greeting},\n\n"
            "New patients want to book before the pain goes away. "
            "Your website can't do that at 2 AM. This can:\n\n"
            "{demo_url}\n\n"
            "Answers insurance questions, explains your treatments, "
            "and books appointments around the clock. "
            "No more voicemails that never convert.\n\n"
            "Built specifically for {business_name}. Free to try.\n\n"
            "— DarkCode AI"
        ),
    },
    "auto_repair": {
        "subject": "Built something for {business_name} — instant service quotes",
        "body": (
            "{greeting},\n\n"
            "Car owners Google their problem, find your shop, and then... "
            "call during business hours? Most won't. This will catch them:\n\n"
            "{demo_url}\n\n"
            "Answers service questions, gives estimate ranges, "
            "and books appointments — 24/7, no phone tag.\n\n"
            "Built specifically for {business_name}. Free to try.\n\n"
            "— DarkCode AI"
        ),
    },
    "general": {
        "subject": "Built a 24/7 assistant for {business_name}",
        "body": (
            "{greeting},\n\n"
            "Your website visitors have questions after hours. "
            "I built something that answers them instantly:\n\n"
            "{demo_url}\n\n"
            "It handles FAQs, books appointments, and captures leads — "
            "24/7, no hold time. Your front desk will thank you.\n\n"
            "Built specifically for {business_name}. Free to try.\n\n"
            "— DarkCode AI"
        ),
    },
}

# Map common niche search terms to template keys
NICHE_MAP: dict[str, str] = {
    "dental practice": "dental",
    "dental office": "dental",
    "dentist": "dental",
    "orthodontist": "dental",
    "real estate": "real_estate",
    "realtor": "real_estate",
    "real estate agent": "real_estate",
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

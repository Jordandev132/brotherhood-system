"""Viper Proposal Generator — auto-generates convincing proposals on BID.

When Jordan hits BID, this module:
1. Reads the lead details
2. Generates a tailored proposal using our skill set
3. Sends to TG with SEND/COPY button

Proposals are persuasive, specific, and show we already understand their problem.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

import requests

from viper.tg_router import send as tg_send

log = logging.getLogger(__name__)

# ── Our full service capabilities ────────────────────────────────────

CAPABILITIES = {
    "core": [
        "AI chatbots & virtual assistants (custom-trained on client data)",
        "n8n / Make / Zapier automation workflows",
        "Web scraping pipelines (Selenium, Playwright, APIs)",
        "API integrations & backend development (Python, Flask, Django)",
        "Telegram / Discord / WhatsApp bots",
        "AI agents & LLM-powered tools (Claude, GPT, Gemini)",
    ],
    "marketing": [
        "SEO audits & optimization (technical + on-page)",
        "Content writing & copywriting (blogs, landing pages, ad copy)",
        "Social media automation & scheduling",
        "Lead generation & outbound automation",
        "Meta/Google Ads automation",
        "Email marketing automation",
    ],
    "data": [
        "Automated dashboards & reporting",
        "Data pipelines & ETL workflows",
        "CRM automation & enrichment",
        "LinkedIn / Indeed scraping for outreach",
    ],
}

# ── Proposal templates by lead type ──────────────────────────────────

def generate_proposal(lead: dict) -> str:
    """Generate a tailored proposal for a lead.

    Returns the proposal text ready to post/send.
    """
    title = lead.get("title", "")
    description = lead.get("description", "")
    source = lead.get("source", "")
    skills = [s.lower() for s in lead.get("skills", [])]
    url = lead.get("url", "")

    # Detect what they need
    needs = _detect_needs(title, description, skills)

    # Build the proposal
    proposal = _build_proposal(needs, title, description, source)

    return proposal


def _detect_needs(title: str, description: str, skills: list[str]) -> list[str]:
    """Detect what the client needs from title + description."""
    text = f"{title} {description}".lower()
    needs = []

    patterns = {
        "automation": r"automat|workflow|n8n|make\.com|zapier",
        "scraping": r"scrap|crawl|extract|linkedin.*scrap|indeed.*scrap",
        "chatbot": r"chatbot|chat bot|virtual assistant|ai assistant|customer support bot",
        "api": r"api integrat|connect.*api|api.*develop",
        "ads": r"meta ads|google ads|ad copy|campaign|creatives|facebook ads",
        "seo": r"seo|search engine|ranking|organic|keyword",
        "content": r"content writ|copywriting|blog|landing page|ad copy",
        "dashboard": r"dashboard|report|analytics|kpi|metrics",
        "email": r"email.*automat|outbound|cold email|email market|lemlist",
        "social": r"social media|instagram|tiktok|posting|scheduling",
        "bot": r"telegram|discord|whatsapp|slack.*bot",
        "lead_gen": r"lead gen|outbound|sales automat|outreach",
        "ai": r"ai agent|llm|gpt|claude|openai|machine learn",
    }

    for need, pattern in patterns.items():
        if re.search(pattern, text):
            needs.append(need)

    return needs if needs else ["automation", "ai"]


def _build_proposal(needs: list[str], title: str, description: str, source: str) -> str:
    """Build a persuasive proposal tailored to their needs."""

    # Opening — show we read their post
    opener = _craft_opener(needs, title, description)

    # Middle — what we bring
    relevant_skills = _match_skills(needs)

    # Proof / differentiator
    proof = _craft_proof(needs)

    # CTA
    cta = _craft_cta(source)

    lines = []
    lines.append(opener)
    lines.append("")
    lines.append("Here's what I can help with:")
    lines.append("")
    for skill in relevant_skills[:6]:
        lines.append(f"- {skill}")
    lines.append("")
    lines.append(proof)
    lines.append("")
    lines.append(cta)

    return "\n".join(lines)


def _craft_opener(needs: list[str], title: str, description: str) -> str:
    """Write a specific opener that shows we understand their problem."""
    desc_lower = description.lower()

    if "n8n" in desc_lower or "make" in desc_lower:
        return (
            "Hey — this is exactly what I do. I build production n8n and Make workflows "
            "for marketing and sales teams. Not just simple Zaps — full automation systems "
            "with error handling, monitoring, and scalability built in."
        )
    if "chatbot" in desc_lower or "chat bot" in desc_lower:
        return (
            "Hey — I build custom AI chatbots trained on your specific business data. "
            "Not generic templates — bots that actually know your services, pricing, "
            "FAQ, and can book appointments or capture leads 24/7."
        )
    if "scrap" in desc_lower:
        return (
            "Hey — I build production scraping pipelines that actually work at scale. "
            "Anti-detection, proxy rotation, structured data extraction, "
            "and automated scheduling built in from day one."
        )
    if "seo" in desc_lower or "content" in desc_lower:
        return (
            "Hey — I handle both the technical SEO side (site audits, speed optimization, "
            "schema markup) and content strategy (keyword research, blog writing, "
            "landing page copy that converts)."
        )

    return (
        "Hey — this caught my eye. I'm a freelance AI automation engineer "
        "and this is right in my wheelhouse. Let me break down how I can help."
    )


def _match_skills(needs: list[str]) -> list[str]:
    """Return relevant skills matched to their needs."""
    matched = []

    skill_map = {
        "automation": [
            "End-to-end n8n & Make workflow development (I build production systems, not prototypes)",
            "Error handling, retry logic, and monitoring built into every workflow",
            "Weekly maintenance & iteration as your needs evolve",
        ],
        "scraping": [
            "LinkedIn & Indeed scraping pipelines with anti-detection",
            "Structured data extraction → CRM/Notion/Sheets integration",
            "Proxy rotation & rate limiting for reliable long-term operation",
        ],
        "chatbot": [
            "Custom AI chatbot trained on YOUR business data (services, FAQ, pricing)",
            "Works 24/7 — handles inquiries, books appointments, captures leads",
            "Deploys on your website, WhatsApp, Telegram, or any platform",
        ],
        "api": [
            "API integrations (REST, GraphQL, webhooks) — any platform to any platform",
            "Meta Graph API, WhatsApp Business API, Notion API specialist",
            "Custom middleware & data transformation pipelines",
        ],
        "ads": [
            "Meta Ads automation — campaign creation, ad copy generation, creative workflows",
            "Automated reporting dashboards for ad performance",
            "AI-powered ad copy & creative generation at scale",
        ],
        "seo": [
            "Full technical SEO audits (site speed, crawlability, schema markup)",
            "On-page optimization & keyword strategy",
            "Content-driven SEO — blog posts, landing pages optimized for search",
        ],
        "content": [
            "AI-assisted content writing (blogs, landing pages, product descriptions)",
            "Conversion-focused copywriting — AIDA, PAS frameworks",
            "Content calendar automation & multi-platform distribution",
        ],
        "dashboard": [
            "Automated dashboards & reporting (live KPIs, no manual updates)",
            "Data pipeline from any source → unified dashboard",
            "Scheduled reports via email/Slack/Notion",
        ],
        "email": [
            "Cold email & outbound automation (Lemlist, Resend, custom SMTP)",
            "Email sequence builder with personalization at scale",
            "Deliverability optimization (SPF, DKIM, warmup)",
        ],
        "social": [
            "Social media automation — scheduling, cross-posting, analytics",
            "Content repurposing pipeline (one piece → multiple platforms)",
            "Engagement tracking & automated responses",
        ],
        "bot": [
            "Telegram / Discord / WhatsApp bot development",
            "Custom commands, inline keyboards, webhook integrations",
            "AI-powered conversational bots with context memory",
        ],
        "lead_gen": [
            "Lead generation automation — scrape → enrich → score → outreach",
            "Multi-channel outbound sequences (email, LinkedIn, WhatsApp)",
            "CRM integration & lead scoring pipelines",
        ],
        "ai": [
            "AI agent development (Claude, GPT-4, Gemini) — custom tools & actions",
            "LLM-powered workflows — summarization, classification, generation",
            "RAG systems for domain-specific AI assistants",
        ],
    }

    for need in needs:
        if need in skill_map:
            matched.extend(skill_map[need])

    # Always add SEO + content as extra value
    if "seo" not in needs:
        matched.append("Bonus: SEO audits & content writing to drive organic traffic")
    if "content" not in needs:
        matched.append("Bonus: AI-powered content writing for blogs, ads, and landing pages")

    return matched[:8]


def _craft_proof(needs: list[str]) -> str:
    """Add credibility / differentiator."""
    return (
        "I work async, communicate clearly, and ship fast. "
        "I'm not a prompt engineer who discovered n8n last week — "
        "I build real production systems that handle edge cases and scale. "
        "Happy to share examples of similar work."
    )


def _craft_cta(source: str) -> str:
    """Call to action based on platform."""
    if "n8n" in source.lower() or "community" in source.lower():
        return "DM me or drop a reply — happy to jump on a quick async chat to scope this out."
    if "reddit" in source.lower():
        return "DM me if interested — I'll send over relevant examples."
    if "hackernews" in source.lower() or "hn" in source.lower():
        return "Email in my profile — let's discuss scope and timeline."
    return "Let me know if you'd like to discuss — I can scope this out quickly."


# ── Send proposal to TG ─────────────────────────────────────────────

def send_proposal_to_tg(lead: dict, proposal: str) -> bool:
    """Send generated proposal to TG for Jordan's review."""
    source = lead.get("source", "?")
    title = lead.get("title", "")[:60]
    url = lead.get("url", "")
    lead_hash = lead.get("hash", "")

    text = (
        f"<b>PROPOSAL READY</b>\n\n"
        f"For: {title}\n"
        f"Source: {source}\n"
        f"Link: {url}\n\n"
        f"<b>--- Proposal ---</b>\n\n"
        f"{_escape_html(proposal)}\n\n"
        f"<i>Copy and post on the platform.</i>"
    )

    buttons = [
        [
            {"text": "SEND", "callback_data": f"proposal_send:{lead_hash[:16]}"},
            {"text": "REGENERATE", "callback_data": f"proposal_regen:{lead_hash[:16]}"},
        ],
    ]

    return tg_send(text, channel="INBOUND", buttons=buttons)


def _escape_html(text: str) -> str:
    """Escape HTML special chars for TG."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Auto-generate on BID ────────────────────────────────────────────

def auto_generate_for_lead(lead: dict) -> bool:
    """Called when Jordan hits BID — generates and sends proposal."""
    log.info("[PROPOSAL] Generating for: %s", lead.get("title", "")[:50])

    proposal = generate_proposal(lead)
    ok = send_proposal_to_tg(lead, proposal)

    if ok:
        log.info("[PROPOSAL] Sent to TG for review")
    else:
        log.error("[PROPOSAL] Failed to send to TG")

    return ok

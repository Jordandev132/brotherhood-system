"""MailerLite integration for nurture sequences.

Handles:
- Adding ROI Calculator leads to MailerLite
- Triggering 7-email nurture sequence via MailerLite automation
- Subscriber management

Uses MailerLite API (free tier: 1,000 subscribers, 12,000 emails/month).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_API_BASE = "https://connect.mailerlite.com/api"
_ENV_FILE = Path.home() / "polymarket-bot" / ".env"
_CAPTURES_FILE = Path.home() / "polymarket-bot" / "data" / "roi_captures.json"

ROI_GROUP_NAME = "ROI Calculator Leads"

NICHE_DATA = {
    "dental practice": {
        "label": "dental practice",
        "problem": "The #1 reason dental practices lose patients after hours",
        "stat": "67% of patients who can't book online call a competitor instead",
        "case_study": "A dental practice in NH added an AI assistant and captured 23 more appointments in the first month — that's $34,500 in lifetime value.",
        "trend": "73% of dental practices plan to implement AI patient communication by end of 2026",
    },
    "real estate agency": {
        "label": "real estate agency",
        "problem": "The #1 reason real estate leads go cold before you can respond",
        "stat": "Real estate leads go cold in under 5 minutes — and 78% of buyers go with the first agent who responds",
        "case_study": "A real estate team saw 40% more scheduled showings from their website after adding 24/7 AI-powered lead capture.",
        "trend": "81% of top-producing agents are now using AI tools to respond to leads faster than competitors",
    },
    "hvac company": {
        "label": "HVAC company",
        "problem": "The #1 reason HVAC businesses lose their highest-value customers",
        "stat": "After-hours emergency HVAC calls are worth 3x a regular service call — and they go to whoever answers first",
        "case_study": "An HVAC company went from missing 12 after-hours calls per week to catching every single one with AI.",
        "trend": "64% of home service businesses are adopting AI chatbots in 2026 to capture after-hours revenue",
    },
    "law firm": {
        "label": "law firm",
        "problem": "The #1 reason law firms lose potential clients before intake",
        "stat": "78% of potential legal clients contact multiple firms — first response wins the case",
        "case_study": "A law firm's client intake rate jumped 35% after adding 24/7 AI-powered screening.",
        "trend": "58% of law firms say AI client intake has become essential for staying competitive",
    },
    "med spa": {
        "label": "med spa",
        "problem": "The #1 reason med spa clients book with your competitor instead",
        "stat": "Med spa clients book impulsively — if your booking isn't instant, they scroll to the next option",
        "case_study": "A med spa doubled their online bookings within 3 weeks of adding an AI booking assistant.",
        "trend": "70% of aesthetic practices are implementing AI booking to capture impulse appointments",
    },
}

NURTURE_SEQUENCE = [
    {
        "day": 0,
        "subject": "Your AI ROI Report for {business_type}",
        "body": (
            "Hi{first_name_line},\n\n"
            "Here are your results from the DarkCode AI ROI Calculator:\n\n"
            "- Monthly revenue lost to missed calls: ${monthly_lost:,.0f}\n"
            "- Annual revenue at risk: ${annual_lost:,.0f}\n"
            "- Estimated monthly savings with AI: ${monthly_savings:,.0f}\n"
            "- ROI timeline: pays for itself in {roi_days} days\n"
            "- Net annual gain: ${net_annual:,.0f}\n\n"
            "We build AI assistants specifically for {business_type_lower}s. "
            "They handle calls, book appointments, and capture leads 24/7 — "
            "so you never miss another opportunity.\n\n"
            "If you want to see what this looks like for your business, "
            "I'm happy to build a free demo.\n\n"
            "— Jordan\nDarkCode AI"
        ),
    },
    {
        "day": 3,
        "subject": "{problem}",
        "body": (
            "Hi{first_name_line},\n\n"
            "{stat}.\n\n"
            "Most business owners don't realize how much revenue walks out "
            "the door when no one's there to answer. It's not about being lazy — "
            "it's about being human. You can't be available 24/7.\n\n"
            "But AI can.\n\n"
            "That's why we built DarkCode AI — to make sure {business_type_lower}s "
            "never miss a lead, even at 2 AM.\n\n"
            "Just thought you'd find that useful.\n\n"
            "— Jordan"
        ),
    },
    {
        "day": 7,
        "subject": "How a {business_type_lower} captured $34K in one month",
        "body": (
            "Hi{first_name_line},\n\n"
            "{case_study}\n\n"
            "The setup took less than a week. No coding needed on their end. "
            "The AI handles scheduling, answers common questions, and captures "
            "contact info from every visitor — day and night.\n\n"
            "Want to see a live demo built specifically for {business_type_lower}s?\n\n"
            "Just reply \"demo\" and I'll set one up for you.\n\n"
            "— Jordan"
        ),
    },
    {
        "day": 12,
        "subject": "3 questions to ask before buying an AI chatbot",
        "body": (
            "Hi{first_name_line},\n\n"
            "Thinking about AI for your business? Here are 3 things most people forget to ask:\n\n"
            "1. Does it actually learn your business, or just give generic answers?\n"
            "   (Ours is trained on YOUR services, hours, pricing, and team.)\n\n"
            "2. Can it capture leads and book appointments, or just chat?\n"
            "   (Ours does both — plus sends you the lead info instantly.)\n\n"
            "3. What happens when someone asks something it can't answer?\n"
            "   (Ours gracefully collects their info and routes to you.)\n\n"
            "If you're evaluating options, I'm happy to answer questions — "
            "no pitch, just honest advice.\n\n"
            "— Jordan"
        ),
    },
    {
        "day": 18,
        "subject": "{trend}",
        "body": (
            "Hi{first_name_line},\n\n"
            "{trend}. Your competitors are already moving.\n\n"
            "The businesses that adopt AI early don't just save money — "
            "they capture the customers that everyone else is losing after hours "
            "and on weekends.\n\n"
            "The ROI calculator showed your business could recover "
            "${annual_lost:,.0f}/year. That's not theoretical — it's what "
            "you're leaving on the table right now.\n\n"
            "Happy to chat if you want to explore this.\n\n"
            "— Jordan"
        ),
    },
    {
        "day": 24,
        "subject": "Is your {business_type_lower} ready for AI?",
        "body": (
            "Hi{first_name_line},\n\n"
            "Quick self-assessment:\n\n"
            "- Do you miss calls after hours or on weekends? \n"
            "- Do website visitors leave without booking? \n"
            "- Does your receptionist spend time answering the same questions? \n"
            "- Do leads go cold before you can follow up? \n\n"
            "If you checked even one — AI can help.\n\n"
            "We've helped {business_type_lower}s solve all four. "
            "If you're curious, I can show you exactly how in 15 minutes.\n\n"
            "— Jordan"
        ),
    },
    {
        "day": 30,
        "subject": "15 minutes — let's talk about your AI opportunity",
        "body": (
            "Hi{first_name_line},\n\n"
            "Over the past month, I've shared how AI is changing the game "
            "for {business_type_lower}s — from capturing after-hours leads to "
            "automating scheduling.\n\n"
            "Your ROI calculator showed ${annual_lost:,.0f}/year in recoverable "
            "revenue. That number doesn't get smaller over time.\n\n"
            "If you want to see what this looks like for YOUR business specifically, "
            "let's hop on a quick 15-minute call. No pressure, no commitment — "
            "just a conversation.\n\n"
            "Book a time here: https://darkcodeai.carrd.co\n\n"
            "Or just reply to this email and we'll figure out a time.\n\n"
            "— Jordan\nDarkCode AI"
        ),
    },
]


def _get_ml_key() -> str | None:
    key = os.environ.get("MAILERLITE_API_KEY")
    if key:
        return key
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            if line.startswith("MAILERLITE_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _load_captures() -> list[dict]:
    if _CAPTURES_FILE.exists():
        try:
            return json.loads(_CAPTURES_FILE.read_text())
        except Exception:
            return []
    return []


def _save_captures(captures: list[dict]) -> None:
    _CAPTURES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CAPTURES_FILE.write_text(json.dumps(captures, indent=2, ensure_ascii=False))


def capture_roi_lead(
    email: str,
    business_type: str,
    missed_calls: int,
    ltv: float,
    receptionist_cost: float,
    monthly_lost: float,
    annual_lost: float,
    monthly_savings: float,
    roi_days: int,
    net_annual: float,
    first_name: str = "",
) -> dict:
    """Store a lead from the ROI Calculator and queue for MailerLite."""
    captures = _load_captures()

    fields = {
        "business_type": business_type,
        "missed_calls": missed_calls,
        "ltv": ltv,
        "receptionist_cost": receptionist_cost,
        "monthly_lost": monthly_lost,
        "annual_lost": annual_lost,
        "monthly_savings": monthly_savings,
        "roi_days": roi_days,
        "net_annual": net_annual,
        "first_name": first_name,
    }

    for c in captures:
        if c.get("email", "").lower() == email.lower():
            log.info("Duplicate ROI capture for %s — updating", email)
            c.update({**fields, "updated_at": datetime.now(timezone.utc).isoformat()})
            _save_captures(captures)
            return c

    record = {
        "email": email,
        **fields,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "mailerlite_synced": False,
        "nurture_started": False,
    }
    captures.append(record)
    _save_captures(captures)
    log.info("ROI lead captured: %s (%s)", email, business_type)
    return record


def render_nurture_email(step_index: int, lead_data: dict) -> dict:
    """Render a nurture sequence email for a given step and lead."""
    if step_index < 0 or step_index >= len(NURTURE_SEQUENCE):
        raise ValueError(f"Invalid step index: {step_index}")

    template = NURTURE_SEQUENCE[step_index]
    btype = lead_data.get("business_type", "small business").lower()
    niche = NICHE_DATA.get(btype, NICHE_DATA.get("dental practice", {}))
    first_name = lead_data.get("first_name", "")
    first_name_line = f" {first_name}" if first_name else ""

    fmt = {
        "first_name_line": first_name_line,
        "business_type": lead_data.get("business_type", "your business"),
        "business_type_lower": btype,
        "monthly_lost": lead_data.get("monthly_lost", 0),
        "annual_lost": lead_data.get("annual_lost", 0),
        "monthly_savings": lead_data.get("monthly_savings", 0),
        "roi_days": lead_data.get("roi_days", 30),
        "net_annual": lead_data.get("net_annual", 0),
        "problem": niche.get("problem", ""),
        "stat": niche.get("stat", ""),
        "case_study": niche.get("case_study", ""),
        "trend": niche.get("trend", ""),
    }

    subject = template["subject"].format(**fmt)
    body = template["body"].format(**fmt)
    return {"subject": subject, "body": body, "day": template["day"]}


def get_unsynced_captures() -> list[dict]:
    """Get ROI captures not yet synced to MailerLite."""
    return [c for c in _load_captures() if not c.get("mailerlite_synced")]


def get_all_captures() -> list[dict]:
    """Get all ROI Calculator captures."""
    return _load_captures()

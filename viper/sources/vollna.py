"""Vollna/Upwork webhook source — receives Upwork leads via Vollna alerts.

Vollna monitors Upwork 24/7 with filters and sends matches via webhook.
This module processes the webhook payload and writes to the lead pipeline.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
INBOX_FILE = DATA_DIR / "vollna_inbox.json"


@dataclass
class VollnaLead:
    title: str = ""
    description: str = ""
    url: str = ""
    budget: str = ""
    proposals: int = 0
    client_rating: float = 0.0
    client_spend: str = ""
    client_country: str = ""
    category: str = ""
    skills: list[str] = field(default_factory=list)
    job_id: str = ""
    surfaced_at: str = ""


def process_webhook(payload: dict) -> VollnaLead | None:
    """Process a Vollna webhook payload into a VollnaLead.

    Vollna sends different payload formats depending on configuration.
    This handles the common fields.
    """
    if not payload:
        return None

    title = payload.get("title", "")
    url = payload.get("url", "") or payload.get("link", "")
    if not title and not url:
        log.warning("[VOLLNA] Empty webhook payload")
        return None

    description = payload.get("description", "") or payload.get("snippet", "")
    budget = payload.get("budget", "") or payload.get("amount", "")
    if isinstance(budget, (int, float)):
        budget = f"${budget:,.0f}"

    proposals = 0
    raw_proposals = payload.get("proposals", payload.get("bids", 0))
    try:
        proposals = int(raw_proposals)
    except (ValueError, TypeError):
        pass

    client_rating = 0.0
    raw_rating = payload.get("client_rating", payload.get("rating", 0))
    try:
        client_rating = float(raw_rating)
    except (ValueError, TypeError):
        pass

    # Extract skills from tags or skills array
    skills = payload.get("skills", []) or payload.get("tags", [])
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",")]

    # Generate a job ID from URL if not provided
    job_id = payload.get("id", "") or payload.get("job_id", "")
    if not job_id and url:
        job_id = url.rstrip("/").split("/")[-1].split("~")[-1]

    lead = VollnaLead(
        title=title.strip(),
        description=description[:1000].strip(),
        url=url.strip(),
        budget=str(budget),
        proposals=proposals,
        client_rating=client_rating,
        client_spend=str(payload.get("client_spend", "")),
        client_country=str(payload.get("client_country", "")),
        category=_classify(title, description),
        skills=skills[:10],
        job_id=job_id,
        surfaced_at=datetime.now(timezone.utc).isoformat(),
    )

    # Persist to inbox for the scanner to pick up
    _save_to_inbox(lead)

    log.info("[VOLLNA] Received lead: %s ($%s, %d proposals)", title[:60], budget, proposals)
    return lead


def _classify(title: str, description: str) -> str:
    """Quick category classification."""
    text = f"{title} {description}".lower()
    coding_kw = ["python", "bot", "scraper", "api", "automation", "chatbot",
                  "ai", "developer", "backend", "flask", "django", "telegram",
                  "whatsapp", "discord", "n8n", "zapier"]
    content_kw = ["seo", "content", "writing", "blog", "article", "copywriting",
                  "marketing", "newsletter"]

    has_coding = any(kw in text for kw in coding_kw)
    has_content = any(kw in text for kw in content_kw)

    if has_coding and has_content:
        return "mixed"
    elif has_coding:
        return "coding"
    elif has_content:
        return "content"
    return "other"


def _save_to_inbox(lead: VollnaLead) -> None:
    """Append lead to vollna_inbox.json for the scanner to pick up."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    inbox = []
    if INBOX_FILE.exists():
        try:
            inbox = json.loads(INBOX_FILE.read_text())
        except Exception:
            inbox = []

    inbox.append({
        "source": "upwork_vollna",
        "title": lead.title,
        "description": lead.description,
        "url": lead.url,
        "budget": lead.budget,
        "proposals": lead.proposals,
        "client_rating": lead.client_rating,
        "client_spend": lead.client_spend,
        "client_country": lead.client_country,
        "category": lead.category,
        "skills": lead.skills,
        "job_id": lead.job_id,
        "surfaced_at": lead.surfaced_at,
        "processed": False,
    })

    # Keep last 200 entries
    if len(inbox) > 200:
        inbox = inbox[-200:]

    INBOX_FILE.write_text(json.dumps(inbox, indent=2))


def get_unprocessed() -> list[dict]:
    """Get unprocessed Vollna leads from the inbox."""
    if not INBOX_FILE.exists():
        return []
    try:
        inbox = json.loads(INBOX_FILE.read_text())
        return [l for l in inbox if not l.get("processed")]
    except Exception:
        return []


def mark_processed(job_ids: list[str]) -> None:
    """Mark leads as processed in the inbox."""
    if not INBOX_FILE.exists():
        return
    try:
        inbox = json.loads(INBOX_FILE.read_text())
        ids_set = set(job_ids)
        for lead in inbox:
            if lead.get("job_id") in ids_set:
                lead["processed"] = True
        INBOX_FILE.write_text(json.dumps(inbox, indent=2))
    except Exception as e:
        log.error("[VOLLNA] Failed to mark processed: %s", str(e)[:200])

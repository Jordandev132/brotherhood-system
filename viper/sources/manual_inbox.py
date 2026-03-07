"""Manual inbox source — Jordan drops leads via Shelby or direct file edit.

File: data/gig_inbox.json
Format:
{
    "inbox": [
        {
            "url": "https://upwork.com/jobs/xxxxx",
            "source": "upwork_manual",
            "notes": "Looks like a good real estate bot gig",
            "added_at": "2026-03-06T10:00:00Z",
            "processed": false
        }
    ]
}

Viper checks this file every scan cycle. When processed, marks processed: true.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
INBOX_FILE = DATA_DIR / "gig_inbox.json"


@dataclass
class ManualLead:
    url: str = ""
    source: str = ""
    title: str = ""
    notes: str = ""
    added_at: str = ""
    job_id: str = ""
    category: str = "other"
    matched_skills: list[str] = field(default_factory=list)


def scan_inbox() -> list[ManualLead]:
    """Read unprocessed leads from the manual inbox."""
    if not INBOX_FILE.exists():
        return []

    try:
        data = json.loads(INBOX_FILE.read_text())
    except Exception as e:
        log.error("[INBOX] Failed to read inbox: %s", str(e)[:200])
        return []

    inbox = data.get("inbox", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

    leads: list[ManualLead] = []
    for item in inbox:
        if item.get("processed"):
            continue

        url = item.get("url", "")
        if not url:
            continue

        # Generate ID from URL
        job_id = item.get("id", "") or f"manual_{hash(url) & 0xFFFFFFFF:08x}"

        # Detect source from URL if not provided
        source = item.get("source", "manual")
        if source == "manual" and url:
            if "upwork.com" in url:
                source = "upwork_manual"
            elif "fiverr.com" in url:
                source = "fiverr_manual"
            elif "linkedin.com" in url:
                source = "linkedin_manual"
            # freelancer.com KILLED — do not detect

        leads.append(ManualLead(
            url=url,
            source=source,
            title=item.get("title", "") or _title_from_url(url),
            notes=item.get("notes", ""),
            added_at=item.get("added_at", ""),
            job_id=job_id,
        ))

    log.info("[INBOX] Found %d unprocessed manual leads", len(leads))
    return leads


def _title_from_url(url: str) -> str:
    """Generate a title from URL path."""
    try:
        path = url.split("?")[0].rstrip("/").split("/")[-1]
        return path.replace("-", " ").replace("_", " ").title()[:100] or "Manual Lead"
    except Exception:
        return "Manual Lead"


def mark_processed(urls: list[str]) -> None:
    """Mark leads as processed in the inbox file."""
    if not INBOX_FILE.exists():
        return

    try:
        data = json.loads(INBOX_FILE.read_text())
    except Exception:
        return

    inbox = data.get("inbox", []) if isinstance(data, dict) else data
    urls_set = set(urls)

    for item in inbox:
        if item.get("url") in urls_set:
            item["processed"] = True

    if isinstance(data, dict):
        data["inbox"] = inbox
    else:
        data = inbox

    INBOX_FILE.write_text(json.dumps(data, indent=2))
    log.info("[INBOX] Marked %d leads as processed", len(urls))


def add_lead(url: str, source: str = "manual", notes: str = "") -> None:
    """Add a lead to the inbox (called by Shelby when Jordan says 'Add lead: ...')."""
    from datetime import datetime, timezone

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    data = {"inbox": []}
    if INBOX_FILE.exists():
        try:
            data = json.loads(INBOX_FILE.read_text())
            if isinstance(data, list):
                data = {"inbox": data}
        except Exception:
            data = {"inbox": []}

    data["inbox"].append({
        "url": url,
        "source": source,
        "notes": notes,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "processed": False,
    })

    INBOX_FILE.write_text(json.dumps(data, indent=2))
    log.info("[INBOX] Added manual lead: %s", url[:80])

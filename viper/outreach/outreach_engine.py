"""Outreach engine — orchestrates the Viper→Shelby auto-outreach pipeline.

When Viper finds a prospect scored >= 7:
1. Check if already contacted (dedup)
2. Build personalized outreach message
3. Send via SendGrid
4. Log in SQLite
5. Notify Jordan via Telegram

Jordan only gets involved when a prospect replies.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from viper.outreach.sendgrid_mailer import send_email
from viper.outreach.templates import get_outreach_message, resolve_niche_key
from viper.outreach.outreach_log import already_contacted, log_outreach

log = logging.getLogger(__name__)

# Demo URL base — GitHub Pages
_DEMO_BASE = "https://darkcode-ai.github.io/chatbot-demos/"


def _notify_jordan(message: str) -> None:
    """Send Telegram notification to Jordan via shared notifier."""
    try:
        sys.path.insert(0, str(Path.home()))
        from shared.telegram_notify import notify, NotifyType, Urgency
        notify(NotifyType.ALERT, message, Urgency.IMMEDIATE)
    except Exception as e:
        log.warning("TG notification failed: %s — printing instead", e)
        print(f"  [TG] {message}")


def run_outreach(
    prospects: list,
    niche: str,
    city: str,
    min_score: float = 7.0,
    demo_slug: str = "",
    dry_run: bool = False,
) -> dict:
    """Send outreach emails to qualified prospects.

    Args:
        prospects: list of LocalProspect objects (from prospect_writer)
        niche: search niche (e.g., "dental practice")
        city: search city (e.g., "Dover NH")
        min_score: minimum score to qualify (default 7.0)
        demo_slug: slug for demo URL (e.g., "belknapdental-com")
        dry_run: if True, compose messages but don't actually send

    Returns:
        dict with 'sent', 'skipped', 'failed', 'already_contacted' counts
    """
    niche_key = resolve_niche_key(niche)
    stats = {"sent": 0, "skipped": 0, "failed": 0, "already_contacted": 0}
    sent_names = []

    qualified = [p for p in prospects if p.score >= min_score]
    if not qualified:
        print(f"  No prospects scored >= {min_score}. Nothing to send.")
        return stats

    print(f"\n  [outreach] {len(qualified)} prospects qualify (score >= {min_score})")

    for p in qualified:
        # Must have email
        if not p.email:
            log.debug("Skipping %s — no email", p.business_name)
            stats["skipped"] += 1
            continue

        # Dedup check
        if already_contacted(p.email, niche, city):
            log.info("Already contacted %s — skipping", p.business_name)
            stats["already_contacted"] += 1
            continue

        # Build demo URL
        if demo_slug:
            demo_url = f"{_DEMO_BASE}{demo_slug}/"
        else:
            # Generate slug from business name
            slug = p.business_name.lower().replace(" ", "-").replace(".", "")
            slug = "".join(c for c in slug if c.isalnum() or c == "-")
            demo_url = f"{_DEMO_BASE}{slug}/"

        # Build message
        msg = get_outreach_message(
            niche=niche_key,
            business_name=p.business_name,
            demo_url=demo_url,
            contact_name=p.contact_name,
        )

        if dry_run:
            print(f"  [DRY RUN] Would email {p.email}: {msg['subject']}")
            stats["sent"] += 1
            sent_names.append(p.business_name)
            continue

        # Send
        result = send_email(
            to_email=p.email,
            subject=msg["subject"],
            body=msg["body"],
            to_name=p.contact_name,
        )

        # Log
        log_outreach(
            business_name=p.business_name,
            email=p.email,
            niche=niche,
            city=city,
            subject=msg["subject"],
            score=p.score,
            demo_url=demo_url,
            sendgrid_status=result["status_code"],
            error=result.get("error", ""),
            prospect_data=p.to_dict(),
        )

        if result["success"]:
            stats["sent"] += 1
            sent_names.append(p.business_name)
            print(f"  [outreach] Sent to {p.business_name} ({p.email})")
        else:
            stats["failed"] += 1
            print(f"  [outreach] FAILED {p.business_name}: {result['error']}")

    # Notify Jordan
    if stats["sent"] > 0:
        names_str = ", ".join(sent_names[:5])
        if len(sent_names) > 5:
            names_str += f" +{len(sent_names) - 5} more"
        prefix = "[DRY RUN] " if dry_run else ""
        _notify_jordan(
            f"{prefix}Viper outreach: {stats['sent']} emails sent to "
            f"{niche} businesses in {city}. "
            f"Targets: {names_str}"
        )

    print(f"\n  [outreach] Done: {stats['sent']} sent, "
          f"{stats['skipped']} skipped (no email), "
          f"{stats['failed']} failed, "
          f"{stats['already_contacted']} already contacted")

    return stats

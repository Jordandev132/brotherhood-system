"""Thin audit layer — formats existing scrape data as email-ready findings.

NOT a new scraping pass. Uses data already collected by demos/scraper.py
and chatbot_detector.py to generate prospect-specific pain points for
outreach emails.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AuditFinding:
    """Single audit finding ready to paste into an email."""
    issue: str
    email_line: str


def audit_site(prospect) -> list[AuditFinding]:
    """Generate audit findings from existing prospect data.

    Args:
        prospect: LocalProspect from prospect_writer.py

    Returns:
        List of AuditFinding objects (max 3 for email brevity).
    """
    findings: list[AuditFinding] = []

    # 1. No chatbot detected
    if prospect.chatbot_confidence == "NOT_FOUND":
        findings.append(AuditFinding(
            issue="No live chat or chatbot",
            email_line=(
                "No live chat or chatbot on your site — after-hours inquiries "
                "go unanswered"
            ),
        ))

    # 2. No email extracted
    if not prospect.email:
        findings.append(AuditFinding(
            issue="No visible email address",
            email_line=(
                "No visible email address — visitors can't reach you easily"
            ),
        ))

    # 3. No contact form or buried
    if not prospect.contact_form_url:
        findings.append(AuditFinding(
            issue="Contact form missing or hard to find",
            email_line=(
                "Contact form missing or hard to find — potential customers "
                "drop off before reaching you"
            ),
        ))

    # 4. Low scrape quality (proxy for mobile/speed issues)
    if prospect.scrape_quality < 50 and prospect.scrape_quality > 0:
        findings.append(AuditFinding(
            issue="Possible mobile/speed issues",
            email_line=(
                "Several pages couldn't load properly — possible mobile "
                "or speed issues affecting visitor experience"
            ),
        ))

    # Cap at 3 findings for email brevity
    return findings[:3]


def format_findings_for_email(findings: list[AuditFinding]) -> str:
    """Format findings as a bulleted list for email insertion.

    Returns empty string if no findings.
    """
    if not findings:
        return ""
    lines = [f"- {f.email_line}" for f in findings]
    return "\n".join(lines)

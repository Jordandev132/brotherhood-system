"""Site auditor — full site crawl via Cloudflare Browser Rendering.

Uses Cloudflare's /crawl endpoint to crawl up to 50 pages per prospect.
Detects: chatbot presence (any page), FAQ page, contact form, services,
appointment booking, page count. Generates email-ready findings.

Fallback: if no Cloudflare creds, uses the old local-only audit.

Crawl results cached in data/site_audits/ as JSON per prospect.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
AUDIT_DIR = DATA_DIR / "site_audits"

_CF_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
_CF_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")

if not _CF_ACCOUNT_ID:
    _dotenv = Path.home() / "polymarket-bot" / ".env"
    if _dotenv.exists():
        for line in _dotenv.read_text().splitlines():
            if line.startswith("CLOUDFLARE_ACCOUNT_ID="):
                _CF_ACCOUNT_ID = line.split("=", 1)[1].strip()
            elif line.startswith("CLOUDFLARE_API_TOKEN="):
                _CF_API_TOKEN = line.split("=", 1)[1].strip()

_CRAWL_URL = (
    f"https://api.cloudflare.com/client/v4/accounts/{_CF_ACCOUNT_ID}"
    f"/browser-rendering/crawl"
    if _CF_ACCOUNT_ID else ""
)

# Chatbot indicators to search for across all crawled pages
_CHATBOT_PATTERNS = [
    r"tidio", r"intercom", r"drift\.com", r"crisp\.chat", r"livechat",
    r"zendesk", r"freshchat", r"hubspot.*chat", r"tawk\.to", r"olark",
    r"chatbot", r"chat-widget", r"chat_widget", r"live-chat",
    r"messenger-widget", r"chat-bubble", r"webchat",
    r"dialogflow", r"botpress", r"manychat", r"chatfuel",
]
_CHATBOT_RE = re.compile("|".join(_CHATBOT_PATTERNS), re.IGNORECASE)

# FAQ page detection
_FAQ_PATTERNS = [
    r"/faq", r"/frequently-asked", r"/questions", r"/help",
    r"/knowledge-base", r"/kb", r"/support",
]
_FAQ_RE = re.compile("|".join(_FAQ_PATTERNS), re.IGNORECASE)

# Contact form detection
_CONTACT_PATTERNS = [
    r"/contact", r"/get-in-touch", r"/reach-us", r"/connect",
    r"contact-form", r"form.*submit", r"name.*email.*message",
]
_CONTACT_RE = re.compile("|".join(_CONTACT_PATTERNS), re.IGNORECASE)

# Booking/appointment detection
_BOOKING_PATTERNS = [
    r"book\s*(an?\s*)?appointment", r"schedule\s*(an?\s*)?appointment",
    r"online\s*booking", r"book\s*now", r"schedule\s*now",
    r"calendly", r"acuity", r"appointy", r"setmore",
]
_BOOKING_RE = re.compile("|".join(_BOOKING_PATTERNS), re.IGNORECASE)


@dataclass
class AuditFinding:
    """Single audit finding ready to paste into an email."""
    issue: str
    email_line: str


@dataclass
class CrawlResult:
    """Full site crawl analysis result."""
    url: str = ""
    pages_crawled: int = 0
    has_chatbot: bool = False
    chatbot_name: str = ""
    chatbot_pages: list[str] = field(default_factory=list)
    has_faq: bool = False
    faq_url: str = ""
    faq_question_count: int = 0
    has_contact_form: bool = False
    contact_form_url: str = ""
    contact_form_depth: int = 0
    has_booking: bool = False
    services: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    error: str = ""
    # SEO audit fields
    has_meta_title: bool = False
    meta_title: str = ""
    has_meta_description: bool = False
    meta_description: str = ""
    has_og_tags: bool = False
    has_viewport: bool = False
    has_schema_markup: bool = False
    schema_types: list[str] = field(default_factory=list)
    missing_alt_images: int = 0
    total_images: int = 0
    has_h1: bool = False
    h1_count: int = 0
    has_ssl: bool = False


def _analyze_seo(html: str, result: CrawlResult) -> None:
    """Extract SEO signals from homepage HTML."""
    # Meta title
    title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if title_m and title_m.group(1).strip():
        result.has_meta_title = True
        result.meta_title = title_m.group(1).strip()[:120]

    # Meta description
    desc_m = re.search(
        r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']',
        html, re.IGNORECASE,
    )
    if not desc_m:
        # Try reversed attribute order
        desc_m = re.search(
            r'<meta[^>]*content=["\']([^"\']*)["\'][^>]*name=["\']description["\']',
            html, re.IGNORECASE,
        )
    if desc_m and desc_m.group(1).strip():
        result.has_meta_description = True
        result.meta_description = desc_m.group(1).strip()[:200]

    # Open Graph tags
    if re.search(r'<meta[^>]*property=["\']og:', html, re.IGNORECASE):
        result.has_og_tags = True

    # Viewport (mobile responsiveness)
    if re.search(r'<meta[^>]*name=["\']viewport["\']', html, re.IGNORECASE):
        result.has_viewport = True

    # H1 tags
    h1_matches = re.findall(r"<h1[^>]*>", html, re.IGNORECASE)
    result.h1_count = len(h1_matches)
    result.has_h1 = result.h1_count > 0

    # Image alt text audit
    img_tags = re.findall(r"<img[^>]*>", html, re.IGNORECASE)
    result.total_images = len(img_tags)
    for img in img_tags:
        if not re.search(r'alt=["\'][^"\']+["\']', img, re.IGNORECASE):
            result.missing_alt_images += 1


def _crawl_site_cf(website_url: str) -> CrawlResult:
    """Crawl a site using Cloudflare Browser Rendering /crawl endpoint."""
    result = CrawlResult(url=website_url)

    if not _CRAWL_URL or not _CF_API_TOKEN:
        result.error = "Cloudflare credentials not configured"
        return result

    headers = {
        "Authorization": f"Bearer {_CF_API_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "url": website_url,
        "render": False,
        "limit": 50,
    }

    try:
        resp = requests.post(_CRAWL_URL, json=payload, headers=headers, timeout=60)
        if resp.status_code != 200:
            result.error = f"CF API {resp.status_code}: {resp.text[:200]}"
            log.error("[SITE_AUDIT] Cloudflare crawl failed: %s", result.error)
            return result

        data = resp.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            result.error = f"CF API error: {errors}"
            log.error("[SITE_AUDIT] Cloudflare crawl error: %s", result.error)
            return result

        crawl_result = data.get("result", {})
        pages = crawl_result.get("pages", [])
        result.pages_crawled = len(pages)

        # SSL check from URL
        result.has_ssl = website_url.startswith("https")

        for idx, page in enumerate(pages):
            page_url = page.get("url", "")
            content = page.get("content", "")
            result.pages.append(page_url)

            # SEO checks on homepage (first page)
            if idx == 0:
                _analyze_seo(content, result)

            # Check for chatbot on this page
            chatbot_match = _CHATBOT_RE.search(content)
            if chatbot_match:
                result.has_chatbot = True
                if not result.chatbot_name:
                    result.chatbot_name = chatbot_match.group(0)
                result.chatbot_pages.append(page_url)

            # Check for FAQ page
            if _FAQ_RE.search(page_url):
                result.has_faq = True
                result.faq_url = page_url
                # Count questions (look for ? or numbered items)
                questions = re.findall(r"\?", content)
                result.faq_question_count = max(
                    result.faq_question_count, len(questions)
                )

            # Check for contact form
            if _CONTACT_RE.search(page_url) or _CONTACT_RE.search(content):
                result.has_contact_form = True
                if not result.contact_form_url:
                    result.contact_form_url = page_url
                    # Estimate depth from URL path segments
                    path = page_url.replace(website_url, "").strip("/")
                    result.contact_form_depth = len(path.split("/")) if path else 0

            # Check for booking capability
            if _BOOKING_RE.search(content):
                result.has_booking = True

            # Schema markup detection (any page)
            if not result.has_schema_markup:
                schema_matches = re.findall(
                    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                    content, re.DOTALL | re.IGNORECASE,
                )
                if schema_matches:
                    result.has_schema_markup = True
                    for blob in schema_matches:
                        try:
                            sd = json.loads(blob)
                            st = sd.get("@type", "")
                            if st and st not in result.schema_types:
                                result.schema_types.append(st)
                        except (json.JSONDecodeError, AttributeError):
                            pass
                # Also check microdata
                if re.search(r'itemscope|itemprop', content, re.IGNORECASE):
                    result.has_schema_markup = True

        log.info(
            "[SITE_AUDIT] Crawled %s: %d pages, chatbot=%s, faq=%s, contact=%s",
            website_url[:50], result.pages_crawled,
            result.has_chatbot, result.has_faq, result.has_contact_form,
        )

    except requests.Timeout:
        result.error = "Cloudflare crawl timed out"
        log.error("[SITE_AUDIT] Timeout crawling %s", website_url[:60])
    except Exception as e:
        result.error = str(e)[:200]
        log.error("[SITE_AUDIT] Crawl error for %s: %s", website_url[:60], result.error)

    return result


def _save_crawl_result(prospect_name: str, crawl: CrawlResult) -> None:
    """Save crawl result to data/site_audits/ as JSON."""
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", prospect_name.lower()).strip("-")[:60]
    filepath = AUDIT_DIR / f"{slug}.json"

    data = {
        "url": crawl.url,
        "pages_crawled": crawl.pages_crawled,
        "has_chatbot": crawl.has_chatbot,
        "chatbot_name": crawl.chatbot_name,
        "chatbot_pages": crawl.chatbot_pages,
        "has_faq": crawl.has_faq,
        "faq_url": crawl.faq_url,
        "faq_question_count": crawl.faq_question_count,
        "has_contact_form": crawl.has_contact_form,
        "contact_form_url": crawl.contact_form_url,
        "contact_form_depth": crawl.contact_form_depth,
        "has_booking": crawl.has_booking,
        "services": crawl.services,
        "pages": crawl.pages,
        "error": crawl.error,
        "seo": {
            "has_meta_title": crawl.has_meta_title,
            "meta_title": crawl.meta_title,
            "has_meta_description": crawl.has_meta_description,
            "meta_description": crawl.meta_description,
            "has_og_tags": crawl.has_og_tags,
            "has_viewport": crawl.has_viewport,
            "has_schema_markup": crawl.has_schema_markup,
            "schema_types": crawl.schema_types,
            "has_h1": crawl.has_h1,
            "h1_count": crawl.h1_count,
            "has_ssl": crawl.has_ssl,
            "total_images": crawl.total_images,
            "missing_alt_images": crawl.missing_alt_images,
        },
    }
    filepath.write_text(json.dumps(data, indent=2))


def crawl_and_audit(prospect) -> tuple[CrawlResult | None, list[AuditFinding]]:
    """Full site crawl + audit. Returns (crawl_result, findings).

    Uses Cloudflare if creds available, otherwise falls back to local audit.
    """
    website = getattr(prospect, "website", "") or ""
    if not website:
        return None, audit_site(prospect)

    # Check if CF creds are available
    if not _CF_ACCOUNT_ID or not _CF_API_TOKEN:
        log.debug("[SITE_AUDIT] No CF creds, falling back to local audit")
        return None, audit_site(prospect)

    crawl = _crawl_site_cf(website)

    if crawl.error:
        log.warning("[SITE_AUDIT] CF crawl failed, falling back: %s", crawl.error)
        return crawl, audit_site(prospect)

    # Save crawl result
    biz_name = getattr(prospect, "business_name", "unknown")
    _save_crawl_result(biz_name, crawl)

    # Generate findings from crawl data
    findings = _findings_from_crawl(crawl, biz_name)
    return crawl, findings


def _findings_from_crawl(crawl: CrawlResult, business_name: str) -> list[AuditFinding]:
    """Generate email-ready findings from Cloudflare crawl results.

    Prioritizes the most impactful issues. Returns max 3 for email brevity.
    """
    findings: list[AuditFinding] = []

    pages_str = f"all {crawl.pages_crawled} pages of" if crawl.pages_crawled > 1 else ""

    # 1. No chatbot anywhere on the site (highest priority — our core pitch)
    if not crawl.has_chatbot:
        findings.append(AuditFinding(
            issue=f"No chatbot on any of {crawl.pages_crawled} pages",
            email_line=(
                f"I looked through {pages_str} your site — no chatbot anywhere. "
                f"After-hours inquiries go completely unanswered"
            ),
        ))

    # 2. No mobile viewport = not mobile-friendly
    if not crawl.has_viewport:
        findings.append(AuditFinding(
            issue="No mobile viewport tag — site isn't mobile-optimized",
            email_line=(
                "Your site doesn't have a mobile viewport tag — it won't display "
                "properly on phones, and Google penalizes that in search rankings"
            ),
        ))

    # 3. Missing meta description (hurts click-through from Google)
    if not crawl.has_meta_description:
        findings.append(AuditFinding(
            issue="No meta description — poor Google snippet",
            email_line=(
                "No meta description on your homepage — when people find you on "
                "Google, the preview text is random instead of a clear pitch"
            ),
        ))

    # 4. No schema markup (missed rich snippet opportunity)
    if not crawl.has_schema_markup:
        findings.append(AuditFinding(
            issue="No schema markup — missing rich search results",
            email_line=(
                "No structured data markup — your business info (hours, reviews, "
                "address) won't show up as rich results on Google"
            ),
        ))

    # 5. Images without alt text (accessibility + SEO)
    if crawl.total_images > 0 and crawl.missing_alt_images > 2:
        pct = round(crawl.missing_alt_images / crawl.total_images * 100)
        findings.append(AuditFinding(
            issue=f"{crawl.missing_alt_images}/{crawl.total_images} images missing alt text",
            email_line=(
                f"{pct}% of your images are missing alt text — that hurts both "
                f"accessibility and how Google indexes your site"
            ),
        ))

    # 6. FAQ page with questions that could be automated
    if crawl.has_faq and crawl.faq_question_count > 0:
        faq_path = crawl.faq_url.split("/")[-1] if crawl.faq_url else "FAQ"
        findings.append(AuditFinding(
            issue=f"FAQ has {crawl.faq_question_count} questions — automatable",
            email_line=(
                f"Your FAQ on /{faq_path} has {crawl.faq_question_count} questions "
                f"that could be automated with a chatbot"
            ),
        ))

    # 7. Contact form buried deep
    if crawl.has_contact_form and crawl.contact_form_depth >= 2:
        findings.append(AuditFinding(
            issue=f"Contact form is {crawl.contact_form_depth + 1} clicks from homepage",
            email_line=(
                f"Your contact form is {crawl.contact_form_depth + 1} clicks from "
                f"the homepage — most visitors drop off before reaching it"
            ),
        ))
    elif not crawl.has_contact_form:
        findings.append(AuditFinding(
            issue="No contact form found",
            email_line=(
                "No contact form found across your site — visitors have no easy "
                "way to reach you"
            ),
        ))

    # 8. No SSL
    if not crawl.has_ssl:
        findings.append(AuditFinding(
            issue="No HTTPS — browser shows 'Not Secure' warning",
            email_line=(
                "Your site loads over HTTP instead of HTTPS — visitors see a "
                "'Not Secure' warning in their browser, which kills trust"
            ),
        ))

    # 9. No appointment booking
    if not crawl.has_booking:
        findings.append(AuditFinding(
            issue="No online booking capability",
            email_line="No online appointment booking — customers can't self-serve",
        ))

    # 10. No Open Graph tags (bad social sharing)
    if not crawl.has_og_tags:
        findings.append(AuditFinding(
            issue="No Open Graph tags — poor social media previews",
            email_line=(
                "No Open Graph tags — when someone shares your site on Facebook "
                "or LinkedIn, the preview looks broken"
            ),
        ))

    # 11. Multiple or missing H1 tags
    if not crawl.has_h1:
        findings.append(AuditFinding(
            issue="No H1 tag on homepage",
            email_line=(
                "No H1 heading on your homepage — Google uses this to understand "
                "what your business does"
            ),
        ))
    elif crawl.h1_count > 1:
        findings.append(AuditFinding(
            issue=f"{crawl.h1_count} H1 tags on homepage (should be 1)",
            email_line=(
                f"Your homepage has {crawl.h1_count} H1 headings instead of 1 — "
                f"this confuses search engines about your main topic"
            ),
        ))

    return findings[:3]


def audit_site(prospect) -> list[AuditFinding]:
    """Generate audit findings from existing prospect data (local fallback).

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

    return findings[:3]


def format_findings_for_email(findings: list[AuditFinding]) -> str:
    """Format findings as a bulleted list for email insertion.

    Returns empty string if no findings.
    """
    if not findings:
        return ""
    lines = [f"- {f.email_line}" for f in findings]
    return "\n".join(lines)

"""Output prospects as JSON + terminal summary table."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from viper.prospecting.maps_scraper import MapsListing
from viper.prospecting.chatbot_detector import ChatbotDetectionResult, Confidence
from viper.prospecting.local_scorer import ProspectScore
from viper.demos.scraper import ScrapedBusiness

log = logging.getLogger(__name__)

# ── Contact name extraction from email / business name ──

_GENERIC_EMAIL_PREFIXES = frozenset([
    "info", "office", "admin", "contact", "support", "frontdesk",
    "manager", "team", "sales", "hello", "help", "billing",
    "service", "inquiry", "reception", "mail", "noreply",
    "noreply", "webmaster", "postmaster", "general", "marketing",
    "contactus", "realestateinquiry", "press", "pressable",
    "accessibility", "dtx", "wor", "hr", "jobs", "careers",
]
)

# Common first names for prefix-matching concatenated emails (e.g. chrismehr → Chris)
_COMMON_FIRST_NAMES = frozenset([
    "adam", "al", "alex", "amy", "andrea", "andrew", "angela", "ann",
    "anna", "anne", "ashley", "barbara", "ben", "bill", "bob", "brian",
    "carol", "charles", "chris", "dan", "daniel", "darcy", "david",
    "dean", "deborah", "diane", "don", "donna", "dorothy", "ed",
    "elizabeth", "emily", "eric", "gary", "gail", "greg", "helen",
    "jack", "james", "jane", "jason", "jeff", "jen", "jennifer",
    "jessica", "jim", "joe", "john", "joseph", "josh", "julie",
    "karen", "kate", "katherine", "kathleen", "keith", "kelly",
    "ken", "kevin", "kim", "larry", "laura", "linda", "lisa",
    "mark", "mary", "matt", "matthew", "meg", "melissa", "michael",
    "michelle", "mike", "nancy", "nate", "nathan", "nick", "nico",
    "nicole", "pat", "paul", "peter", "rachel", "ray", "rebecca",
    "richard", "robert", "ron", "ruth", "ryan", "sage", "sam",
    "sandra", "sarah", "scott", "sharon", "stephanie", "stephen",
    "steven", "sue", "susan", "ted", "thomas", "tim", "tom",
    "tony", "william",
])


def name_from_email(email: str) -> str:
    """Extract a first name from an email address.

    Patterns handled:
    - first.last@ → First
    - FIRST.LAST@ → First
    - first@ (short, in _COMMON_FIRST_NAMES only) → First
    - chrismehr@ → Chris (prefix match against common names)
    - info@, office@ etc. → "" (generic, skip)
    - sage@cambridgesage → "" (local part in domain = business handle)
    """
    if not email or "@" not in email:
        return ""
    local = email.split("@")[0].lower().strip()
    domain_prefix = email.split("@")[1].split(".")[0].lower()

    # Skip generic prefixes
    if local in _GENERIC_EMAIL_PREFIXES:
        return ""

    # Skip business handles — local part embedded in domain
    # sage@cambridgesage, nico@nicorealty, etc.
    if len(local) >= 3 and local in domain_prefix:
        return ""

    # first.last@ or first.middle.last@ → use first part
    if "." in local:
        parts = [p for p in local.split(".") if p]
        first = parts[0]
        # Single letter = initial (j.fermin) — try second part instead
        if len(first) == 1 and len(parts) >= 2 and len(parts[1]) >= 2:
            first = parts[1]
        # "johnj" stuck together — strip trailing single initial
        if len(first) > 2 and first[-1].isalpha() and first[:-1] in _COMMON_FIRST_NAMES:
            first = first[:-1]
        if len(first) >= 2 and first in _COMMON_FIRST_NAMES:
            return first.capitalize()
        if len(first) >= 2 and first not in _GENERIC_EMAIL_PREFIXES:
            return first.capitalize()

    # Short local part — ONLY accept if in _COMMON_FIRST_NAMES
    if local.isalpha() and 2 <= len(local) <= 8:
        if local in _COMMON_FIRST_NAMES:
            return local.capitalize()
        # NOT in our list? Don't guess. Return empty.
        return ""

    # Longer concatenated names — try prefix match (chrismehr → Chris)
    if local.isalpha() and len(local) > 8:
        for length in range(7, 2, -1):  # Try longest prefix first
            prefix = local[:length]
            if prefix in _COMMON_FIRST_NAMES:
                return prefix.capitalize()

    return ""


def name_from_business(business_name: str) -> str:
    """Extract a first name from a business name that contains a person's name.

    Patterns handled:
    - "Darcy Bento, South Boston Realtor" → Darcy
    - "Nicole M. Blanchard at Compass" → Nicole
    - "John J. Dean Jr. - Engel & Volkers" → John
    - "Nathan Riel - The Riel Estate Team" → Nathan
    - "Gail Roberts, Ed Feijo & Team" → Gail
    - "Chris Doherty" (entire name IS the business) → Chris
    """
    if not business_name:
        return ""

    name = business_name.strip()

    # "Name, Title/Location" — split on comma, check if first part is a person
    # "Name - Company" — split on dash
    # "Name at Company" — split on " at "
    for sep in [",", " - ", " – ", " at ", " | ", " with "]:
        if sep in name:
            first_part = name.split(sep)[0].strip()
            extracted = _extract_person_name(first_part)
            if extracted:
                return extracted
            break  # Only try the first separator found

    # Entire business name might be a person's name (e.g. "Chris Doherty")
    extracted = _extract_person_name(name)
    if extracted:
        return extracted

    return ""


def _extract_person_name(text: str) -> str:
    """Check if text looks like a person's name. Return first name or ""."""
    # Strip titles/suffixes
    text = re.sub(r'\b(Jr\.?|Sr\.?|III|II|IV|Esq\.?)\b', '', text).strip()

    # "Firstname M. Lastname" or "Firstname Lastname"
    m = re.match(
        r'^([A-Z][a-z]{2,})\s+(?:[A-Z]\.?\s+)?([A-Z][a-z]{2,})\s*$',
        text,
    )
    if m:
        first = m.group(1).lower()
        if first in _COMMON_FIRST_NAMES:
            return m.group(1)

    return ""

# ── Contact name validation ──

# Words that are roles/titles/business terms — never a person's first name
_BAD_CONTACT_WORDS = frozenset([
    "broker", "partner", "manager", "team", "staff", "office", "admin",
    "owner", "president", "ceo", "cfo", "cto", "agent", "associate",
    "associates", "director", "coordinator", "specialist", "consultant",
    "group", "company", "corp", "corporation", "services", "realty",
    "dental", "medical", "health", "clinic", "practice", "center",
    "inc", "llc", "llp", "pllc", "pc", "dds", "dmd", "md",
    "premier", "golden", "century", "national", "american", "united",
    "north", "south", "east", "west", "central", "valley",
    "watch", "click", "view", "read", "the",
])


def validate_contact_name(name: str, business_name: str = "") -> bool:
    """Check if an extracted contact name is actually usable in a greeting.

    Returns False for:
    - Empty/whitespace names
    - Role/title words (Broker, Partner, Manager)
    - Names containing slashes, numbers, special chars
    - Single-character names
    - Single-word names that appear in the business name but aren't the
      FIRST word of a "Person Name, Title" pattern
    """
    if not name or not name.strip():
        return False

    clean = name.strip()

    # Reject if contains slash, numbers, or non-name chars
    if any(c in clean for c in "/\\@#$%^&*()0123456789"):
        return False

    # Check each word against bad words list
    for word in clean.lower().split():
        if word in _BAD_CONTACT_WORDS:
            return False

    # Strip Dr. prefix for length check
    stripped = re.sub(r'^dr\\.?\\s*', '', clean, flags=re.IGNORECASE).strip()
    if len(stripped) < 2:
        return False

    # Single-word name that appears in the business name?
    # Allow only if the business name STARTS with that name (person-named biz)
    if business_name and " " not in stripped:
        biz_lower = business_name.lower()
        name_lower = stripped.lower()
        if name_lower in biz_lower.split():
            biz_first = biz_lower.split()[0] if biz_lower else ""
            if name_lower != biz_first:
                return False

    return True


_DATA_DIR = Path.home() / "polymarket-bot" / "data" / "prospects"
_TZ = ZoneInfo("America/New_York")


@dataclass
class LocalProspect:
    """Outreach-ready prospect record."""
    business_name: str = ""
    contact_name: str = ""
    website: str = ""
    phone: str = ""
    email: str = ""
    contact_form_url: str = ""
    address: str = ""
    has_chatbot: bool = False
    chatbot_name: str = ""
    chatbot_confidence: str = "UNCERTAIN"  # DETECTED, NOT_FOUND, UNCERTAIN
    google_rating: float = 0.0
    review_count: int = 0
    maps_url: str = ""
    score: float = 0.0
    score_breakdown: dict = field(default_factory=dict)
    outreach_priority: str = "LOW"
    pitch_angle: str = ""
    scraped_at: str = ""
    scrape_quality: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _pick_contact_name(listing: MapsListing, scraped: ScrapedBusiness | None) -> str:
    """Extract contact first name. Priority: email → business name → website scrape.

    Every extracted name is validated before returning. If validation fails,
    returns "" so the lead gets held as needs_contact_name.
    """
    biz = listing.business_name

    # 1. Email address (first.last@, chrismehr@, nico@ etc.)
    email = scraped.email if scraped else ""
    name = name_from_email(email)
    if name and validate_contact_name(name, biz):
        return name

    # 2. Business name ("Darcy Bento, South Boston Realtor" → Darcy)
    name = name_from_business(biz)
    if name and validate_contact_name(name, biz):
        return name

    # 3. Website scrape (Dr. pattern, schema.org, team cards — fallback)
    if scraped and scraped.team_members:
        full = scraped.team_members[0]
        if full.startswith("Dr.") or full.startswith("Dr "):
            parts = full.split()
            candidate = " ".join(parts[:2]) if len(parts) >= 2 else full
        else:
            candidate = full.split()[0].rstrip(",")
        if validate_contact_name(candidate, biz):
            return candidate

    return ""


def build_prospect(
    listing: MapsListing,
    scraped: ScrapedBusiness | None,
    chatbot: ChatbotDetectionResult | None,
    score: ProspectScore,
) -> LocalProspect:
    """Assemble a LocalProspect from pipeline components."""
    now = datetime.now(_TZ).isoformat(timespec="seconds")
    return LocalProspect(
        business_name=listing.business_name,
        contact_name=_pick_contact_name(listing, scraped),
        website=listing.website_url or (scraped.url if scraped else ""),
        phone=listing.phone or (scraped.phone if scraped else ""),
        email=scraped.email if scraped else "",
        contact_form_url=scraped.contact_form_url if scraped else "",
        address=listing.address or (scraped.address if scraped else ""),
        has_chatbot=chatbot.has_chatbot if chatbot else False,
        chatbot_name=chatbot.chatbot_name if chatbot else "",
        chatbot_confidence=chatbot.confidence.value if chatbot else "UNCERTAIN",
        google_rating=listing.rating,
        review_count=listing.review_count,
        maps_url=listing.maps_url,
        score=score.total,
        score_breakdown=score.breakdown,
        outreach_priority=score.priority,
        pitch_angle=score.pitch_angle,
        scraped_at=now,
        scrape_quality=scraped.quality_score if scraped else 0,
    )


def write_prospects(
    prospects: list[LocalProspect],
    niche: str,
    city: str,
) -> Path:
    """Write prospects list to JSON file. Returns the file path."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    slug_niche = niche.lower().replace(" ", "-")
    slug_city = city.lower().replace(" ", "-").replace(",", "")
    date_str = datetime.now(_TZ).strftime("%Y-%m-%d")
    filename = f"{slug_niche}_{slug_city}_{date_str}.json"

    out_path = _DATA_DIR / filename
    payload = [p.to_dict() for p in prospects]
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    log.info("Wrote %d prospects to %s", len(prospects), out_path)
    return out_path


def print_summary(prospects: list[LocalProspect], top_n: int = 20) -> None:
    """Print a ranked table of top prospects to terminal."""
    if not prospects:
        print("\n  No prospects found.\n")
        return

    top = prospects[:top_n]
    print(f"\n{'='*100}")
    print(f"  TOP {len(top)} PROSPECTS (sorted by score)")
    print(f"{'='*100}")
    print(
        f"  {'#':>2}  {'Score':>5}  {'Pri':>4}  {'Chat Status':>11}  "
        f"{'Rating':>6}  {'Phone':>14}  {'Name':<35}"
    )
    print(f"  {'-'*2}  {'-'*5}  {'-'*4}  {'-'*11}  {'-'*6}  {'-'*14}  {'-'*35}")

    for i, p in enumerate(top, 1):
        if p.chatbot_confidence == "DETECTED":
            chat_col = p.chatbot_name[:11]
        elif p.chatbot_confidence == "NOT_FOUND":
            chat_col = "None"
        else:
            chat_col = "UNCERTAIN"
        rating_col = f"{p.google_rating:.1f}/{p.review_count}" if p.review_count else "—"
        phone_col = p.phone or "—"
        name_col = p.business_name[:35]
        print(
            f"  {i:>2}  {p.score:>5.1f}  {p.outreach_priority:>4}  {chat_col:>11}  "
            f"{rating_col:>6}  {phone_col:>14}  {name_col:<35}"
        )

    print(f"{'='*100}")

    # Priority breakdown
    high = sum(1 for p in top if p.outreach_priority == "HIGH")
    med = sum(1 for p in top if p.outreach_priority == "MEDIUM")
    low = sum(1 for p in top if p.outreach_priority == "LOW")
    print(f"  Priority: {high} HIGH, {med} MEDIUM, {low} LOW")

    # Chatbot confidence breakdown
    detected = sum(1 for p in top if p.chatbot_confidence == "DETECTED")
    not_found = sum(1 for p in top if p.chatbot_confidence == "NOT_FOUND")
    uncertain = sum(1 for p in top if p.chatbot_confidence == "UNCERTAIN")
    print(f"  Chatbots: {detected} DETECTED (skip), {not_found} NOT_FOUND (send), {uncertain} UNCERTAIN (Jordan reviews)")
    print()

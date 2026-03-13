"""Score local business prospects on a 1-10 scale."""
from __future__ import annotations

from dataclasses import dataclass, field

from viper.prospecting.maps_scraper import MapsListing
from viper.prospecting.chatbot_detector import ChatbotDetectionResult, Confidence
from viper.demos.scraper import ScrapedBusiness


@dataclass
class ProspectScore:
    """Scored prospect with breakdown and priority."""
    total: float = 0.0
    breakdown: dict = field(default_factory=dict)
    priority: str = "LOW"  # HIGH, MEDIUM, LOW
    pitch_angle: str = ""


def score_prospect(
    listing: MapsListing,
    scraped: ScrapedBusiness | None,
    chatbot: ChatbotDetectionResult | None,
) -> ProspectScore:
    """Score a prospect across 5 dimensions (max 10 points)."""
    result = ProspectScore()
    bd = {}

    # A. Chatbot status (max 4)
    if chatbot is None or chatbot.confidence == Confidence.UNCERTAIN:
        bd["chatbot"] = 2.0  # can't tell — Jordan reviews
    elif chatbot.confidence == Confidence.DETECTED:
        bd["chatbot"] = 0.0
    else:  # NOT_FOUND
        bd["chatbot"] = 4.0

    # B. Website reachability (max 2)
    if scraped and scraped.pages_scraped > 0:
        bd["website"] = 2.0
    elif listing.website_url:
        bd["website"] = 1.0  # has URL but scrape failed
    else:
        bd["website"] = 0.5  # no website at all

    # C. Contact info (max 2)
    has_email = bool(scraped and scraped.email) if scraped else False
    has_contact_form = bool(scraped and scraped.contact_form_url) if scraped else False
    has_phone = bool(listing.phone or (scraped and scraped.phone))

    if has_email:
        bd["contact"] = 2.0
    elif has_contact_form:
        bd["contact"] = 1.0
    elif has_phone:
        bd["contact"] = 0.5
    else:
        bd["contact"] = 0.0

    # D. Business signals (max 1)
    if listing.rating >= 4.0 and listing.review_count >= 20:
        bd["signals"] = 1.0
    else:
        bd["signals"] = 0.0

    # E. Data quality (max 1)
    if scraped and scraped.quality_score >= 60:
        bd["quality"] = 1.0
    else:
        bd["quality"] = 0.0

    total = sum(bd.values())
    result.total = round(total, 1)
    result.breakdown = bd

    # Priority bands
    if total >= 7:
        result.priority = "HIGH"
    elif total >= 4:
        result.priority = "MEDIUM"
    else:
        result.priority = "LOW"

    # Pitch angle
    result.pitch_angle = _build_pitch(listing, scraped, chatbot)

    return result


def score_prospect_v3(
    listing: MapsListing,
    scraped: ScrapedBusiness | None,
    chatbot: ChatbotDetectionResult | None,
    tech_stack: dict | None = None,
    pagespeed: dict | None = None,
    gbp: dict | None = None,
) -> ProspectScore:
    """Score a prospect across 8 dimensions (max 10 points).

    V3 scoring uses enrichment data for finer-grained assessment:
    A. Chatbot status (3.0) — core pitch relevance
    B. Website quality (1.5) — reachability + speed
    C. Contact info (1.5) — email > form > phone
    D. Business signals (1.5) — rating, reviews, engagement
    E. Data quality (0.5) — scrape completeness
    F. Tech sophistication (0.5) — modern stack = harder sell
    G. SEO opportunity (1.0) — low scores = more angles
    H. Engagement gap (0.5) — review response rate
    """
    result = ProspectScore()
    bd = {}

    # A. Chatbot status (max 3.0)
    if chatbot is None or chatbot.confidence == Confidence.UNCERTAIN:
        bd["chatbot"] = 1.5
    elif chatbot.confidence == Confidence.DETECTED:
        bd["chatbot"] = 0.0
    else:  # NOT_FOUND
        bd["chatbot"] = 3.0

    # B. Website quality (max 1.5)
    if scraped and scraped.pages_scraped > 0:
        base = 1.0
        # Bonus for good PageSpeed
        if pagespeed and pagespeed.get("performance_score", 0) >= 80:
            base = 0.5  # Fast site = less opportunity to help
        bd["website"] = base
    elif listing.website_url:
        bd["website"] = 1.5  # Has URL but problems = opportunity
    else:
        bd["website"] = 0.5

    # C. Contact info (max 1.5)
    has_email = bool(scraped and scraped.email) if scraped else False
    has_form = bool(scraped and scraped.contact_form_url) if scraped else False
    has_phone = bool(listing.phone or (scraped and scraped.phone))

    if has_email:
        bd["contact"] = 1.5
    elif has_form:
        bd["contact"] = 1.0
    elif has_phone:
        bd["contact"] = 0.5
    else:
        bd["contact"] = 0.0

    # D. Business signals (max 1.5)
    rating = listing.rating
    reviews = listing.review_count
    if gbp:
        rating = gbp.get("rating", rating) or rating
        reviews = gbp.get("review_count", reviews) or reviews

    if rating >= 4.0 and reviews >= 50:
        bd["signals"] = 1.5  # Strong business, worth pursuing
    elif rating >= 4.0 and reviews >= 20:
        bd["signals"] = 1.0
    elif rating >= 3.5 and reviews >= 10:
        bd["signals"] = 0.5
    else:
        bd["signals"] = 0.0

    # E. Data quality (max 0.5)
    if scraped and scraped.quality_score >= 60:
        bd["quality"] = 0.5
    else:
        bd["quality"] = 0.0

    # F. Tech sophistication (max 0.5)
    # Lower tech = more opportunity; high-tech sites already have solutions
    if tech_stack:
        chat_widgets = tech_stack.get("chat_widgets", [])
        total = tech_stack.get("total_detected", 0)
        if chat_widgets:
            bd["tech"] = 0.0  # Already has chat widget
        elif total >= 8:
            bd["tech"] = 0.1  # Very sophisticated — harder sell
        elif total >= 4:
            bd["tech"] = 0.3  # Moderate tech
        else:
            bd["tech"] = 0.5  # Low tech = more opportunity
    else:
        bd["tech"] = 0.3  # Unknown

    # G. SEO opportunity (max 1.0)
    if pagespeed:
        seo = pagespeed.get("seo_score", 0)
        perf = pagespeed.get("performance_score", 0)
        if seo < 50 or perf < 50:
            bd["seo"] = 1.0  # Major SEO problems = great angle
        elif seo < 70 or perf < 70:
            bd["seo"] = 0.7
        elif seo < 90:
            bd["seo"] = 0.3
        else:
            bd["seo"] = 0.0  # Great SEO — less angle
    else:
        bd["seo"] = 0.5  # Unknown

    # H. Engagement gap (max 0.5)
    # Low review response rate = customer service gap = our pitch
    response_rate = 0.0
    if gbp:
        response_rate = gbp.get("review_response_rate", 0.0)

    if response_rate < 20:
        bd["engagement"] = 0.5  # Barely responds to reviews
    elif response_rate < 50:
        bd["engagement"] = 0.3
    else:
        bd["engagement"] = 0.0  # Actively engaging

    total = sum(bd.values())
    result.total = round(total, 1)
    result.breakdown = bd

    if total >= 7:
        result.priority = "HIGH"
    elif total >= 4:
        result.priority = "MEDIUM"
    else:
        result.priority = "LOW"

    result.pitch_angle = _build_pitch(listing, scraped, chatbot)
    return result


def _build_pitch(
    listing: MapsListing,
    scraped: ScrapedBusiness | None,
    chatbot: ChatbotDetectionResult | None,
) -> str:
    """Generate a deterministic one-liner pitch angle for Jordan."""
    if not listing.website_url:
        return "No website — pitch website + chatbot bundle"

    if chatbot and chatbot.has_chatbot:
        return f"Has {chatbot.chatbot_name} — pitch upgrade to custom AI"

    if scraped and scraped.pages_scraped > 0:
        return "No chatbot — pitch 24/7 booking automation"

    return "Website unreachable — pitch modern site + chatbot"

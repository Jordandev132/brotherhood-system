"""Two-pass Sonnet email personalizer.

Pass 1: Feed ALL scraped data → structured analysis (weaknesses, best angle).
Pass 2: Generate personalized opener (1-2 sentences) + subject line.

Budget guard: Only called at Gate 1 YES (not during scanning).
~5-10 leads/day = ~$0.04-$0.08/day.

Cost: ~$2-3/month (Sonnet 4.6: $3/$15 per 1M tokens I/O).
"""
from __future__ import annotations

import json
import logging
import os
import random
from pathlib import Path

log = logging.getLogger(__name__)


def _load_api_key() -> str:
    """Load Anthropic API key from env/.env."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        env_path = Path.home() / "polymarket-bot" / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    return key


# ── Fallback templates (from existing _OPENER_VARIANTS in templates.py) ──
_FALLBACK_OPENERS = [
    "Spent a few minutes on your site — nothing catching visitors after hours.",
    "Checked out your site — looks like you don't have live chat set up yet.",
    "I pulled up your site on my phone and tried asking a question after 5 PM. No way to get an answer.",
    "Looked at your site earlier — visitors with questions outside office hours have nowhere to go.",
]


def _fallback_template() -> dict:
    """Return a random fallback opener when Sonnet fails."""
    return {
        "opener": random.choice(_FALLBACK_OPENERS),
        "subject": "",  # empty = let templates.py generate it
    }


def _pass1_analyze(
    prospect_data: dict,
    crawl_data: dict | None,
    gbp_data: dict | None,
    niche: str,
) -> str:
    """Pass 1: Analyze all scraped data into structured insights.

    Returns structured analysis text for Pass 2.
    """
    api_key = _load_api_key()
    if not api_key:
        log.warning("[PERSONALIZER] No ANTHROPIC_API_KEY, using fallback")
        return ""

    # Build context from all available data
    context_parts = []

    biz_name = prospect_data.get("business_name", "")
    website = prospect_data.get("website", "")
    context_parts.append(f"Business: {biz_name}")
    context_parts.append(f"Website: {website}")
    context_parts.append(f"Niche: {niche}")

    if prospect_data.get("google_rating"):
        context_parts.append(f"Google Rating: {prospect_data['google_rating']}/5 ({prospect_data.get('review_count', 0)} reviews)")

    if prospect_data.get("chatbot_confidence"):
        context_parts.append(f"Chatbot: {prospect_data['chatbot_confidence']}")

    if prospect_data.get("tech_stack"):
        ts = prospect_data["tech_stack"]
        if ts.get("cms"):
            context_parts.append(f"CMS: {ts['cms']}")
        if ts.get("frameworks"):
            context_parts.append(f"Frameworks: {', '.join(ts['frameworks'])}")

    if prospect_data.get("performance_score"):
        context_parts.append(f"PageSpeed Performance: {prospect_data['performance_score']}/100")
    if prospect_data.get("seo_score"):
        context_parts.append(f"SEO Score: {prospect_data['seo_score']}/100")

    if gbp_data:
        if gbp_data.get("review_response_rate"):
            context_parts.append(f"Review Response Rate: {gbp_data['review_response_rate']}%")
        if gbp_data.get("photos_count"):
            context_parts.append(f"GBP Photos: {gbp_data['photos_count']}")

    if crawl_data:
        if crawl_data.get("pages_crawled"):
            context_parts.append(f"Pages Crawled: {crawl_data['pages_crawled']}")
        if crawl_data.get("has_faq"):
            context_parts.append(f"Has FAQ page: yes ({crawl_data.get('faq_question_count', 0)} questions)")
        if not crawl_data.get("has_schema_markup"):
            context_parts.append("Missing schema markup")
        if not crawl_data.get("has_meta_description"):
            context_parts.append("Missing meta description")
        if not crawl_data.get("has_viewport"):
            context_parts.append("Missing mobile viewport")

    context = "\n".join(context_parts)

    prompt = f"""Analyze this local business for cold email outreach. I sell custom AI chatbots.

BUSINESS DATA:
{context}

Return a JSON object with:
- "weaknesses": list of 3 specific weaknesses I can reference (be specific, use data)
- "best_angle": the single strongest pain point to lead with
- "specific_detail": one hyper-specific detail from their site/data that proves I actually looked

Be concise. No fluff. Use the actual data above."""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        log.error("[PERSONALIZER] Pass 1 failed: %s", e)
        return ""


def _pass2_generate(
    analysis: str,
    business_name: str,
    contact_name: str,
    niche: str,
) -> dict:
    """Pass 2: Generate personalized opener + subject from analysis.

    Returns dict with 'opener' and 'subject' keys.
    """
    api_key = _load_api_key()
    if not api_key:
        return _fallback_template()

    prompt = f"""Based on this analysis, write a cold email opener for {business_name}.

ANALYSIS:
{analysis}

Contact name: {contact_name or 'unknown'}
Niche: {niche}

RULES:
- Write ONE opener sentence (1-2 lines max). Reference ONE specific detail from the analysis.
- Write ONE subject line. Never mention DarkCode. Frame as a question about their business.
- Sound like a real person who visited their site, not a salesperson.
- No generic compliments ("love your site", "great business").
- No mentioning AI/chatbots in the opener — save that for the body.
- No "I noticed" or "I built" — just state the observation.

Return JSON: {{"opener": "...", "subject": "..."}}"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Parse JSON from response
        # Handle potential markdown code blocks
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        result = json.loads(text)
        opener = result.get("opener", "")
        subject = result.get("subject", "")

        if opener:
            log.info("[PERSONALIZER] Generated opener for %s: %s...", business_name[:20], opener[:50])
            return {"opener": opener, "subject": subject}

    except json.JSONDecodeError:
        log.warning("[PERSONALIZER] Pass 2 JSON parse failed for %s", business_name[:20])
    except Exception as e:
        log.error("[PERSONALIZER] Pass 2 failed: %s", e)

    return _fallback_template()


def personalize_email(
    prospect_data: dict,
    crawl_data: dict | None = None,
    gbp_data: dict | None = None,
    niche: str = "",
    contact_name: str = "",
) -> dict:
    """Two-pass Sonnet personalizer. Returns {"opener": str, "subject": str}.

    Pass 1: Analyze all data → structured insights.
    Pass 2: Generate personalized opener + subject.

    Falls back to template variants if Sonnet fails.
    """
    business_name = prospect_data.get("business_name", "")

    # Pass 1 — analyze
    analysis = _pass1_analyze(prospect_data, crawl_data, gbp_data, niche)
    if not analysis:
        return _fallback_template()

    # Pass 2 — generate
    result = _pass2_generate(analysis, business_name, contact_name, niche)
    return result

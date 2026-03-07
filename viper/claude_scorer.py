"""Claude API lead scorer — AI-powered 6-dimension lead scoring.

Scores leads on: fit, budget, competition, client_quality, urgency.
Produces composite score, recommended_bid, recommended_action, and one_line_summary.

Uses Claude Haiku for cost efficiency (~$0.001 per lead).
"""
from __future__ import annotations

import json
import logging
import os

import anthropic

log = logging.getLogger(__name__)

# Use Haiku for cost efficiency — scoring doesn't need Opus/Sonnet
MODEL = "claude-haiku-4-5-20251001"

SCORING_PROMPT = """Score this lead for an AI automation agency selling chatbots, web scraping, and Python automation services at $500-$5,000.

Lead:
Title: {title}
Description: {description}
Budget: {budget}
Source: {source}
URL: {url}
Proposals/Bids: {proposals}
Client Info: {client_info}

Score on these dimensions (1-10 each):
- fit: Does this match our services (chatbots, automation, scraping, bots)?
- budget: Is the budget worth our time ($500+ preferred)?
- competition: Low competition = higher score
- client_quality: Serious buyer signals (verified payment, clear scope, real business)?
- urgency: How time-sensitive is this?

Also provide:
- composite_score: Weighted average (fit 30%, budget 25%, competition 20%, client_quality 15%, urgency 10%)
- recommended_bid: Dollar amount we should bid
- recommended_action: "bid_now" | "review" | "skip"
- one_line_summary: 1 sentence summary for Telegram alert

Respond ONLY in JSON. No markdown. No explanation."""


def _get_client() -> anthropic.Anthropic | None:
    """Get Anthropic client."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.warning("[CLAUDE_SCORER] No ANTHROPIC_API_KEY set")
        return None
    return anthropic.Anthropic(api_key=api_key)


def score_lead(lead: dict) -> dict:
    """Score a lead using Claude API. Returns enriched lead with scores.

    Falls back to rule-based scoring if Claude API fails.
    """
    client = _get_client()
    if not client:
        return _fallback_score(lead)

    # Build client info string
    client_info_parts = []
    if lead.get("client_country"):
        client_info_parts.append(f"Country: {lead['client_country']}")
    if lead.get("client_rating"):
        client_info_parts.append(f"Rating: {lead['client_rating']}")
    if lead.get("client_spend"):
        client_info_parts.append(f"Spend: {lead['client_spend']}")
    client_info = ", ".join(client_info_parts) or "Unknown"

    prompt = SCORING_PROMPT.format(
        title=lead.get("title", "N/A"),
        description=(lead.get("description", "N/A") or "N/A")[:500],
        budget=lead.get("budget", "N/A") or lead.get("budget_hint", "N/A"),
        source=lead.get("source", "N/A"),
        url=lead.get("url", "N/A"),
        proposals=lead.get("proposals", lead.get("bid_count", "Unknown")),
        client_info=client_info,
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        scores = json.loads(text)

        lead["scores"] = {
            "fit": _clamp(scores.get("fit", 5)),
            "budget": _clamp(scores.get("budget", 5)),
            "competition": _clamp(scores.get("competition", 5)),
            "client_quality": _clamp(scores.get("client_quality", 5)),
            "urgency": _clamp(scores.get("urgency", 5)),
            "composite_score": round(_clamp(scores.get("composite_score", 5.0), 1.0, 10.0), 1),
            "recommended_bid": str(scores.get("recommended_bid", "")),
            "recommended_action": scores.get("recommended_action", "review"),
            "one_line_summary": str(scores.get("one_line_summary", "")),
        }
        lead["composite_score"] = lead["scores"]["composite_score"]
        lead["status"] = "new"

        log.info("[CLAUDE_SCORER] Scored '%s' → %.1f (%s)",
                 lead.get("title", "")[:40],
                 lead["composite_score"],
                 lead["scores"]["recommended_action"])

        return lead

    except json.JSONDecodeError as e:
        log.warning("[CLAUDE_SCORER] JSON parse error: %s — falling back", str(e)[:100])
        return _fallback_score(lead)
    except anthropic.APIError as e:
        log.error("[CLAUDE_SCORER] API error: %s — falling back", str(e)[:200])
        return _fallback_score(lead)
    except Exception as e:
        log.error("[CLAUDE_SCORER] Unexpected error: %s — falling back", str(e)[:200])
        return _fallback_score(lead)


def score_batch(leads: list[dict], max_per_cycle: int = 20) -> list[dict]:
    """Score multiple leads, with a cap per cycle to control costs.

    At ~$0.001/lead with Haiku, 20 leads = ~$0.02/cycle.
    """
    scored = []
    for i, lead in enumerate(leads[:max_per_cycle]):
        scored.append(score_lead(lead))
    return scored


def _clamp(value, lo: float = 1, hi: float = 10) -> float:
    """Clamp a value to [lo, hi]."""
    try:
        return max(lo, min(hi, float(value)))
    except (ValueError, TypeError):
        return 5.0


def _fallback_score(lead: dict) -> dict:
    """Rule-based scoring when Claude API is unavailable."""
    title = (lead.get("title", "") + " " + lead.get("description", "")).lower()

    # Fit
    ai_kw = ["chatbot", "bot", "ai", "automation", "scraper", "telegram", "whatsapp", "n8n"]
    fit_hits = sum(1 for kw in ai_kw if kw in title)
    fit = min(10, 3 + fit_hits * 2)

    # Budget
    budget_str = lead.get("budget", "") or lead.get("budget_hint", "")
    import re
    nums = re.findall(r"\d[\d,]*", budget_str.replace(",", ""))
    budget_val = float(nums[-1]) if nums else 0
    if budget_val >= 1000:
        budget = 9
    elif budget_val >= 500:
        budget = 7
    elif budget_val >= 200:
        budget = 5
    else:
        budget = 3

    # Competition
    bids = lead.get("proposals", lead.get("bid_count", 0)) or 0
    if bids == 0:
        competition = 9
    elif bids <= 5:
        competition = 7
    elif bids <= 15:
        competition = 5
    else:
        competition = 3

    # Client quality
    source = lead.get("source", "")
    if "hackernews" in source.lower():
        client_quality = 8
    elif lead.get("client_rating", 0) and float(lead.get("client_rating", 0)) >= 4.5:
        client_quality = 8
    else:
        client_quality = 5

    # Urgency
    urgency = 5  # Default medium

    composite = round(
        fit * 0.30 + budget * 0.25 + competition * 0.20 +
        client_quality * 0.15 + urgency * 0.10, 1
    )

    # Action
    if composite >= 7.5:
        action = "bid_now"
    elif composite >= 5.5:
        action = "review"
    else:
        action = "skip"

    lead["scores"] = {
        "fit": fit,
        "budget": budget,
        "competition": competition,
        "client_quality": client_quality,
        "urgency": urgency,
        "composite_score": composite,
        "recommended_bid": f"${max(200, int(budget_val * 0.8))}" if budget_val else "$200",
        "recommended_action": action,
        "one_line_summary": lead.get("title", "")[:80],
    }
    lead["composite_score"] = composite
    lead["status"] = "new"

    return lead

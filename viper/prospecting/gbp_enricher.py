"""Google Business Profile enricher via Outscraper API.

Enriches prospects with review data, response rates, photos, hours.
Free tier: 500 requests/month. Budget guard: only call for score >= 6.0.

Cost: $0 (free tier).
Jordan task: Sign up at https://outscraper.com/ + API key.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

import time

import requests

log = logging.getLogger(__name__)

_API_URL = "https://api.app.outscraper.com/maps/search-v3"
_TIMEOUT = 30
_POLL_INTERVAL = 3  # seconds between async result polls
_MAX_POLLS = 10  # max 30 seconds waiting


def _load_api_key() -> str:
    """Load Outscraper API key from env/.env."""
    key = os.getenv("OUTSCRAPER_API_KEY", "")
    if not key:
        env_path = Path.home() / "polymarket-bot" / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("OUTSCRAPER_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    return key


@dataclass
class GBPData:
    """Google Business Profile enrichment data."""
    rating: float = 0.0
    review_count: int = 0
    review_1_star: int = 0
    review_2_star: int = 0
    review_3_star: int = 0
    review_4_star: int = 0
    review_5_star: int = 0
    review_response_rate: float = 0.0  # KEY pain point for email
    hours: str = ""
    photos_count: int = 0
    category: str = ""
    verified: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def enrich_from_gbp(business_name: str, address: str = "") -> GBPData:
    """Enrich a prospect with Google Business Profile data via Outscraper.

    Args:
        business_name: Business name to search.
        address: Optional address for disambiguation.

    Returns:
        GBPData with review stats, response rate, photos, hours.
    """
    result = GBPData()
    api_key = _load_api_key()

    if not api_key:
        result.error = "OUTSCRAPER_API_KEY not configured"
        log.debug("[GBP] No API key, skipping enrichment")
        return result

    if not business_name:
        result.error = "No business name provided"
        return result

    query = f"{business_name} {address}".strip()

    headers = {"X-API-KEY": api_key}
    params = {
        "query": query,
        "limit": 1,
        "language": "en",
        "region": "US",
    }

    try:
        resp = requests.get(_API_URL, params=params, headers=headers, timeout=_TIMEOUT)

        # Handle async 202 response — poll for results
        if resp.status_code == 202:
            poll_data = resp.json()
            poll_url = poll_data.get("results_location", "")
            if not poll_url:
                result.error = "Outscraper returned 202 but no results_location"
                return result

            log.info("[GBP] Async request for %s, polling...", business_name[:30])
            data = None
            for _ in range(_MAX_POLLS):
                time.sleep(_POLL_INTERVAL)
                poll_resp = requests.get(poll_url, headers=headers, timeout=_TIMEOUT)
                if poll_resp.status_code == 200:
                    poll_json = poll_resp.json()
                    if poll_json.get("status") == "Success":
                        data = poll_json
                        break
                    elif poll_json.get("status") == "Pending":
                        continue
                    else:
                        result.error = f"Outscraper poll status: {poll_json.get('status')}"
                        return result

            if data is None:
                result.error = "Outscraper async timeout — results not ready"
                log.error("[GBP] Poll timeout for %s", business_name[:40])
                return result

        elif resp.status_code != 200:
            result.error = f"Outscraper API {resp.status_code}: {resp.text[:200]}"
            log.error("[GBP] API error for %s: %s", business_name[:40], result.error)
            return result
        else:
            data = resp.json()

        # Outscraper returns nested results
        results_list = data.get("data", [])
        if not results_list or not results_list[0]:
            result.error = "No results found"
            log.debug("[GBP] No results for %s", business_name[:40])
            return result

        biz = results_list[0][0] if isinstance(results_list[0], list) else results_list[0]

        result.rating = biz.get("rating", 0.0) or 0.0
        result.review_count = biz.get("reviews", 0) or 0
        result.photos_count = biz.get("photos_count", 0) or 0
        result.category = biz.get("category", "") or ""
        result.verified = biz.get("verified", False) or False

        # Working hours
        hours_list = biz.get("working_hours", {})
        if isinstance(hours_list, dict):
            result.hours = str(hours_list)
        elif isinstance(hours_list, str):
            result.hours = hours_list

        # Review breakdown (if available from reviews data)
        reviews_data = biz.get("reviews_data", {})
        if isinstance(reviews_data, dict):
            result.review_1_star = reviews_data.get("1", 0)
            result.review_2_star = reviews_data.get("2", 0)
            result.review_3_star = reviews_data.get("3", 0)
            result.review_4_star = reviews_data.get("4", 0)
            result.review_5_star = reviews_data.get("5", 0)

        # Review response rate (if owner reply data available)
        owner_answer = biz.get("reviews_per_score_1", {}).get("owner_answer", 0)
        if result.review_count > 0:
            # Outscraper sometimes provides owner_responses_count
            owner_responses = biz.get("owner_responses_count", 0)
            if owner_responses:
                result.review_response_rate = round(
                    owner_responses / result.review_count * 100, 1
                )

        log.info(
            "[GBP] %s: %.1f rating, %d reviews, %.0f%% response rate",
            business_name[:30], result.rating, result.review_count,
            result.review_response_rate,
        )

    except requests.Timeout:
        result.error = "Outscraper API timed out"
        log.error("[GBP] Timeout for %s", business_name[:40])
    except Exception as e:
        result.error = str(e)[:200]
        log.error("[GBP] Error for %s: %s", business_name[:40], result.error)

    return result

"""Google PageSpeed Insights auditor — free API, 25K queries/day.

Fetches Lighthouse scores for mobile + desktop. Zero cost.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_TIMEOUT = 30


def _load_api_key() -> str:
    """Load Google PageSpeed API key from env/.env (optional — works without key at lower rate)."""
    key = os.getenv("PAGESPEED_API_KEY", "")
    if not key:
        env_path = Path.home() / "polymarket-bot" / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("PAGESPEED_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    return key


@dataclass
class PageSpeedResult:
    """Lighthouse audit result for a single URL + strategy."""
    url: str = ""
    strategy: str = "mobile"  # "mobile" or "desktop"
    performance_score: float = 0.0
    seo_score: float = 0.0
    accessibility_score: float = 0.0
    fcp_ms: float = 0.0  # First Contentful Paint
    lcp_ms: float = 0.0  # Largest Contentful Paint
    cls: float = 0.0     # Cumulative Layout Shift
    tbt_ms: float = 0.0  # Total Blocking Time
    mobile_friendly: bool = True
    opportunities: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _format_findings(result: PageSpeedResult) -> list[str]:
    """Generate email-ready lines for scores < 70."""
    findings: list[str] = []

    if result.performance_score > 0 and result.performance_score < 70:
        findings.append(
            f"Your site scores {result.performance_score:.0f}/100 on Google's "
            f"speed test ({result.strategy}) — below the 90+ that ranks well"
        )

    if result.seo_score > 0 and result.seo_score < 70:
        findings.append(
            f"Google's SEO audit gives your site {result.seo_score:.0f}/100 — "
            f"there are quick fixes that could improve your search ranking"
        )

    if result.accessibility_score > 0 and result.accessibility_score < 70:
        findings.append(
            f"Accessibility score is {result.accessibility_score:.0f}/100 — "
            f"this affects both user experience and ADA compliance"
        )

    if result.lcp_ms > 4000:
        findings.append(
            f"Your page takes {result.lcp_ms / 1000:.1f}s to load the main "
            f"content — visitors expect under 2.5 seconds"
        )

    if result.cls > 0.25:
        findings.append(
            f"Layout shift score is {result.cls:.2f} — elements jump around "
            f"while loading, which frustrates visitors"
        )

    for opp in result.opportunities[:2]:
        findings.append(opp)

    return findings


def audit_pagespeed(url: str, strategy: str = "mobile") -> PageSpeedResult:
    """Run a PageSpeed Insights audit.

    Args:
        url: Full website URL to audit.
        strategy: "mobile" or "desktop".

    Returns:
        PageSpeedResult with Lighthouse scores and opportunities.
    """
    result = PageSpeedResult(url=url, strategy=strategy)

    if not url:
        result.error = "No URL provided"
        return result

    params: dict = {
        "url": url,
        "strategy": strategy,
        "category": ["PERFORMANCE", "SEO", "ACCESSIBILITY"],
    }

    api_key = _load_api_key()
    if api_key:
        params["key"] = api_key

    try:
        resp = requests.get(_API_URL, params=params, timeout=_TIMEOUT)
        if resp.status_code != 200:
            result.error = f"PageSpeed API {resp.status_code}: {resp.text[:200]}"
            log.error("[PAGESPEED] API error for %s: %s", url[:60], result.error)
            return result

        data = resp.json()
        lighthouse = data.get("lighthouseResult", {})
        categories = lighthouse.get("categories", {})
        audits = lighthouse.get("audits", {})

        # Category scores (0-1 → 0-100)
        perf = categories.get("performance", {})
        seo = categories.get("seo", {})
        a11y = categories.get("accessibility", {})

        result.performance_score = round((perf.get("score") or 0) * 100, 1)
        result.seo_score = round((seo.get("score") or 0) * 100, 1)
        result.accessibility_score = round((a11y.get("score") or 0) * 100, 1)

        # Core Web Vitals
        fcp = audits.get("first-contentful-paint", {})
        result.fcp_ms = fcp.get("numericValue", 0)

        lcp = audits.get("largest-contentful-paint", {})
        result.lcp_ms = lcp.get("numericValue", 0)

        cls_audit = audits.get("cumulative-layout-shift", {})
        result.cls = cls_audit.get("numericValue", 0)

        tbt = audits.get("total-blocking-time", {})
        result.tbt_ms = tbt.get("numericValue", 0)

        # Mobile-friendly check
        if strategy == "mobile":
            viewport = audits.get("viewport", {})
            result.mobile_friendly = (viewport.get("score") or 0) >= 0.9

        # Top opportunities (actionable suggestions)
        opportunities: list[str] = []
        for audit_key, audit_data in audits.items():
            if audit_data.get("scoreDisplayMode") == "opportunity":
                title = audit_data.get("title", "")
                savings = audit_data.get("numericValue", 0)
                if savings > 500 and title:  # >500ms potential savings
                    opportunities.append(
                        f"{title} (could save ~{savings / 1000:.1f}s)"
                    )
        result.opportunities = opportunities[:5]

        log.info(
            "[PAGESPEED] %s (%s): perf=%.0f seo=%.0f a11y=%.0f",
            url[:50], strategy, result.performance_score,
            result.seo_score, result.accessibility_score,
        )

    except requests.Timeout:
        result.error = "PageSpeed API timed out"
        log.error("[PAGESPEED] Timeout for %s", url[:60])
    except Exception as e:
        result.error = str(e)[:200]
        log.error("[PAGESPEED] Error for %s: %s", url[:60], result.error)

    return result

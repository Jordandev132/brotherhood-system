"""CLI entry point — local business prospector pipeline."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Allow running as `python viper/run_prospector.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from viper.prospecting.maps_scraper import discover_businesses, deduplicate_listings
from viper.prospecting.chatbot_detector import detect_chatbot, ChatbotDetectionResult
from viper.prospecting.local_scorer import score_prospect, score_prospect_v3
from viper.prospecting.prospect_writer import (
    build_prospect,
    write_prospects,
    print_summary,
)
from viper.prospecting.site_auditor import audit_site, format_findings_for_email
from viper.prospecting.tech_fingerprinter import fingerprint_tech_stack
from viper.prospecting.pagespeed_auditor import audit_pagespeed
from viper.prospecting.gbp_enricher import enrich_from_gbp
from viper.prospecting.apollo_enricher import enrich_email as apollo_enrich_email, extract_domain
from viper.demos.scraper import scrape_business, ScrapedBusiness
from viper.outreach.email_sequences import get_due_followups, generate_followup_draft

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("prospector")

_SITE_DELAY = 1.5  # seconds between website scrapes


def _check_follow_up_sequences() -> int:
    """Check for due follow-up emails and print drafts for review."""
    due = get_due_followups()
    if not due:
        print("No follow-up emails due right now.")
        return 0

    print(f"\n{len(due)} follow-up(s) due:\n")
    for step_info in due:
        draft = generate_followup_draft(step_info)
        print(f"  [{step_info['step_id']}] Step {step_info['step']} ({step_info['type']}) "
              f"→ {step_info['business_name']} ({step_info['email']})")
        print(f"  Subject: {draft['subject']}")
        print(f"  Body preview: {draft['body'][:100]}...")
        print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Viper Local Business Prospector — find outreach-ready leads",
    )
    parser.add_argument("niche", help='Business niche, e.g. "dental practice"')
    parser.add_argument("city", help='City + state, e.g. "Dover NH"')
    parser.add_argument("--max", type=int, default=25, help="Max Maps results (default 25)")
    parser.add_argument("--no-enrich", action="store_true", help="Skip website scraping")
    parser.add_argument("--headless", default="true", help="Browser mode (true/false)")
    parser.add_argument("--delay", type=float, default=2.5, help="Seconds between Maps scrolls")
    parser.add_argument(
        "--auto-outreach", action="store_true",
        help="Auto-send cold emails to prospects scored >= 7 via SendGrid",
    )
    parser.add_argument(
        "--outreach-dry-run", action="store_true",
        help="Compose outreach messages but don't actually send (preview mode)",
    )
    parser.add_argument(
        "--demo-slug", default="",
        help="Demo URL slug (e.g., 'belknapdental-com'). Auto-generated if not set.",
    )
    parser.add_argument(
        "--check-sequences", action="store_true",
        help="Check for due follow-up emails and generate drafts for Jordan's approval",
    )
    args = parser.parse_args()

    # Sequence check mode — standalone, doesn't run the full pipeline
    if args.check_sequences:
        return _check_follow_up_sequences()

    headless = args.headless.lower() != "false"
    has_outreach = args.auto_outreach or args.outreach_dry_run
    total_steps = 6 if has_outreach else 5

    # Step 1 — Google Maps discovery
    print(f"\n[1/{total_steps}] Searching Google Maps: \"{args.niche}\" in {args.city} ...")
    try:
        listings = discover_businesses(
            niche=args.niche,
            city=args.city,
            max_results=args.max,
            headless=headless,
            delay=args.delay,
        )
    except RuntimeError as e:
        print(f"\n  CAPTCHA BLOCKED: {e}")
        return 1

    if not listings:
        print("  No results found on Google Maps.")
        return 0

    print(f"  Found {len(listings)} businesses")

    # Dedup — merge listings sharing same website domain
    listings = deduplicate_listings(listings)
    print(f"  After dedup: {len(listings)} unique practices")

    # Step 2 — Enrich each listing (V3 pipeline)
    prospects = []
    total = len(listings)

    for i, listing in enumerate(listings, 1):
        scraped: ScrapedBusiness | None = None
        chatbot: ChatbotDetectionResult | None = None
        tech_stack_data: dict | None = None
        pagespeed_mobile_data: dict | None = None
        pagespeed_desktop_data: dict | None = None
        gbp_data_dict: dict | None = None
        apollo_contacts_list: list | None = None

        if not args.no_enrich and listing.website_url:
            pct = int(i / total * 100)
            print(f"  [2/{total_steps}] Enriching {i}/{total} ({pct}%) — {listing.business_name[:40]}", end="\r")

            try:
                scraped = scrape_business(listing.website_url)
            except Exception as e:
                log.debug("Scrape failed for %s: %s", listing.website_url, e)

            # Chatbot detection
            raw_html = ""
            if scraped and scraped.raw_html:
                raw_html = scraped.raw_html
                chatbot = detect_chatbot(raw_html)
            elif listing.website_url:
                from viper.demos.scraper import _fetch_raw_html
                raw_html = _fetch_raw_html(listing.website_url) or ""
                if raw_html:
                    chatbot = detect_chatbot(raw_html)

            # Tech stack fingerprinting (V3)
            if raw_html:
                try:
                    ts_result = fingerprint_tech_stack(listing.website_url, raw_html)
                    tech_stack_data = ts_result.to_dict()
                except Exception as e:
                    log.debug("Tech fingerprint failed for %s: %s", listing.website_url, e)

            # PageSpeed audit (V3)
            try:
                ps_mobile = audit_pagespeed(listing.website_url, "mobile")
                if not ps_mobile.error:
                    pagespeed_mobile_data = ps_mobile.to_dict()
                ps_desktop = audit_pagespeed(listing.website_url, "desktop")
                if not ps_desktop.error:
                    pagespeed_desktop_data = ps_desktop.to_dict()
            except Exception as e:
                log.debug("PageSpeed failed for %s: %s", listing.website_url, e)

            time.sleep(_SITE_DELAY)

        # GBP enrichment (V3) — budget guard: pre-score >= 6.0
        pre_score = score_prospect(listing, scraped, chatbot)
        if pre_score.total >= 6.0:
            try:
                gbp_result = enrich_from_gbp(listing.business_name, listing.address)
                if not gbp_result.error:
                    gbp_data_dict = gbp_result.to_dict()
            except Exception as e:
                log.debug("GBP enrich failed for %s: %s", listing.business_name, e)

        # Apollo email enrichment (V3) — replaces Hunter.io
        if pre_score.total >= 7.0 and scraped and not scraped.email and listing.website_url:
            domain = extract_domain(listing.website_url)
            if domain:
                try:
                    contacts = apollo_enrich_email(domain, listing.business_name, limit=3)
                    if contacts:
                        apollo_contacts_list = [c.to_dict() for c in contacts]
                        best = contacts[0]
                        scraped.email = best.email
                        name = f"{best.first_name} {best.last_name}".strip()
                        if name and not scraped.team_members:
                            scraped.team_members.append(name)
                        log.info("Apollo found email for %s: %s", listing.business_name, scraped.email)
                except Exception as e:
                    log.debug("Apollo enrich failed for %s: %s", listing.business_name, e)

        # Step 3 — Score with V3 (8 dimensions)
        score = score_prospect_v3(
            listing, scraped, chatbot,
            tech_stack=tech_stack_data,
            pagespeed=pagespeed_mobile_data,
            gbp=gbp_data_dict,
        )

        # Step 4 — Build prospect record with V3 enrichment
        prospect = build_prospect(
            listing, scraped, chatbot, score,
            tech_stack=tech_stack_data,
            pagespeed_mobile=pagespeed_mobile_data,
            pagespeed_desktop=pagespeed_desktop_data,
            gbp_data=gbp_data_dict,
            apollo_contacts=apollo_contacts_list,
        )
        prospects.append(prospect)

    print(f"\n[3/{total_steps}] Scored {len(prospects)} prospects")

    # Sort by score descending
    prospects.sort(key=lambda p: p.score, reverse=True)

    # Step 3.5 — Site audit (attach findings to each prospect)
    for p in prospects:
        p.audit_findings = audit_site(p)

    # Step 4 — Write output
    out_path = write_prospects(prospects, args.niche, args.city)
    print(f"[4/{total_steps}] Saved to {out_path}")

    # Step 5 — Terminal summary
    print(f"[5/{total_steps}] Results:")
    print_summary(prospects)

    # Step 6 — Auto-outreach (if enabled)
    if has_outreach:
        print(f"[6/{total_steps}] Auto-outreach...")
        from viper.outreach.outreach_engine import run_outreach
        stats = run_outreach(
            prospects=prospects,
            niche=args.niche,
            city=args.city,
            min_score=7.0,
            demo_slug=args.demo_slug,
            dry_run=args.outreach_dry_run,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())

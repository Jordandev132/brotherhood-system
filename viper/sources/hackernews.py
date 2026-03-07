"""Hacker News lead scanner — Algolia API for hiring + freelancer threads.

Scans both "Who is hiring?" and "Freelancer? Seeking freelancer?" monthly threads.
Free API, no key needed, 10K requests/hour.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

import requests

log = logging.getLogger(__name__)

# Algolia HN API — free, no key needed
HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
HN_ITEM_URL = "https://hn.algolia.com/api/v1/items"

# Thread types to scan
THREAD_QUERIES = [
    "Who is hiring",
    "Freelancer? Seeking freelancer",
]

KEYWORDS = [
    "chatbot", "chat bot", "ai bot", "automation", "automate",
    "web scraping", "scraper", "scraping", "data extraction",
    "whatsapp bot", "telegram bot", "discord bot",
    "customer service bot", "lead capture", "booking bot",
    "python automation", "workflow automation", "n8n", "make.com", "zapier",
    "ai agent", "ai assistant", "virtual assistant",
    "small business", "real estate", "appointment",
]

SKILL_KEYWORDS = {
    "coding": [
        "python", "bot", "scraper", "scraping", "api",
        "automation", "flask", "django", "backend", "data pipeline",
        "devops", "scripting", "etl", "telegram", "discord",
        "chatbot", "ai", "llm", "gpt", "whatsapp", "selenium",
        "n8n", "zapier", "make.com", "appointment", "booking",
        "real estate", "lead capture", "virtual assistant",
    ],
    "content": [
        "seo", "content", "copywriting", "writer", "writing",
        "marketing", "blog", "technical writer", "newsletter",
    ],
}

SKIP_WORDS = [
    "wordpress", "php", "ios", "swift", "kotlin", "java ",
    "c++", "rust ", "golang", "onsite only", "no remote",
    "react native", "unity",
]


@dataclass
class HNJob:
    title: str = ""
    text: str = ""
    url: str = ""
    comment_id: str = ""
    parent_id: str = ""
    matched_skills: list[str] = field(default_factory=list)
    category: str = ""
    author: str = ""
    thread_type: str = ""  # "hiring" or "freelancer"


def _extract_title(text: str) -> str:
    """Extract company/role from first line of HN hiring comment."""
    first_line = text.split("\n")[0].strip()
    first_line = re.sub(r"<[^>]+>", "", first_line)
    return first_line[:120] if first_line else "HN Hiring Post"


def _extract_url(text: str) -> str:
    """Pull first URL from the comment."""
    m = re.search(r'href="(https?://[^"]+)"', text)
    if m:
        return m.group(1)
    m = re.search(r"(https?://\S+)", text)
    if m:
        return m.group(1)
    return ""


def _classify(text: str) -> tuple[str, list[str]]:
    """Classify text and return (category, matched_skills)."""
    clean = text.lower()

    if any(skip in clean for skip in SKIP_WORDS):
        return "", []

    coding_hits = [k for k in SKILL_KEYWORDS["coding"] if k in clean]
    content_hits = [k for k in SKILL_KEYWORDS["content"] if k in clean]

    if coding_hits and content_hits:
        return "mixed", coding_hits + content_hits
    elif coding_hits:
        return "coding", coding_hits
    elif content_hits:
        return "content", content_hits
    return "", []


def _find_thread(query: str) -> dict | None:
    """Find the latest monthly thread matching the query."""
    try:
        resp = requests.get(
            HN_SEARCH_URL,
            params={
                "query": query,
                "tags": "story",
                "numericFilters": "created_at_i>%d" % (time.time() - 45 * 86400),
            },
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning("[HN] Search HTTP %d for '%s'", resp.status_code, query)
            return None

        stories = resp.json().get("hits", [])
        q_lower = query.lower()
        for s in stories:
            title = (s.get("title") or "").lower()
            if q_lower.split()[0] in title:  # Match first word of query
                return s
    except Exception as e:
        log.error("[HN] Thread search error: %s", str(e)[:200])

    return None


def _get_thread_comments(story_id: str) -> list[dict]:
    """Get all top-level comments for a thread using items API."""
    try:
        resp = requests.get(f"{HN_ITEM_URL}/{story_id}", timeout=20)
        if resp.status_code != 200:
            log.warning("[HN] Items HTTP %d for story %s", resp.status_code, story_id)
            return []
        return resp.json().get("children", [])
    except Exception as e:
        log.error("[HN] Comments fetch error: %s", str(e)[:200])
        return []


def scan_hackernews() -> list[HNJob]:
    """Scan HN for recent hiring and freelancer thread comments matching our skills."""
    jobs: list[HNJob] = []

    for query in THREAD_QUERIES:
        thread = _find_thread(query)
        if not thread:
            log.info("[HN] No recent '%s' thread found", query)
            continue

        story_id = thread.get("objectID", "")
        thread_type = "freelancer" if "freelanc" in query.lower() else "hiring"
        log.info("[HN] Found %s thread: %s (id=%s)", thread_type, thread.get("title", ""), story_id)

        # Use items API for full thread (gets all children)
        comments = _get_thread_comments(story_id)

        for comment in comments:
            text = comment.get("text", "") or ""
            if len(text) < 50:
                continue

            clean = re.sub(r"<[^>]+>", " ", text)

            # For hiring threads, require "remote" mention
            if thread_type == "hiring" and "remote" not in clean.lower():
                continue

            # Check for our keywords OR skill match
            lower = clean.lower()
            has_keyword = any(kw in lower for kw in KEYWORDS)
            category, matched = _classify(clean)

            if not category and not has_keyword:
                continue

            # If keyword matched but no skill classification, default to coding
            if not category and has_keyword:
                category = "coding"
                matched = [kw for kw in KEYWORDS if kw in lower][:5]

            cid = str(comment.get("id", ""))
            title = _extract_title(text)
            apply_url = _extract_url(text)
            hn_url = f"https://news.ycombinator.com/item?id={cid}"

            jobs.append(HNJob(
                title=title,
                text=clean[:500].strip(),
                url=apply_url or hn_url,
                comment_id=cid,
                parent_id=story_id,
                matched_skills=matched,
                category=category,
                author=comment.get("author", ""),
                thread_type=thread_type,
            ))

        time.sleep(1)  # Be polite between thread fetches

    log.info("[HN] Found %d matching jobs across %d thread types", len(jobs), len(THREAD_QUERIES))
    return jobs

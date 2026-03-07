"""Viper Lead Engine — standalone runner.

Modes:
  --loop     : Run scanner loop + Reddit stream in background
  --scan     : Single scan cycle (default)
  --stream   : Reddit stream only (blocking)
"""
from __future__ import annotations

import logging
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/polymarket-bot/.env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from viper.job_hunter import run_scan, run_loop


def _reddit_stream_callback(job):
    """Handle a Reddit lead from the stream — score and write immediately."""
    from viper.lead_writer import write_leads
    from viper.job_hunter import _job_hash

    lead = {
        "source": "reddit",
        "title": job.title,
        "description": job.body,
        "url": job.url,
        "category": job.category,
        "skills": job.matched_skills,
        "budget": job.budget_hint,
        "hash": _job_hash("reddit", job.job_id),
        "job_id": job.job_id,
        "subreddit": job.subreddit,
    }

    try:
        write_leads([lead])
    except Exception as e:
        logging.getLogger(__name__).error("Stream lead write failed: %s", str(e)[:200])


def _start_reddit_stream():
    """Start Reddit streaming in a background thread."""
    try:
        from viper.sources.reddit import stream_reddit
        stream_reddit(_reddit_stream_callback)
    except Exception as e:
        logging.getLogger(__name__).error("Reddit stream failed: %s", str(e)[:200])


def _reddit_configured() -> bool:
    """Check if Reddit credentials are set."""
    return bool(os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_SECRET"))


def main():
    log = logging.getLogger(__name__)
    interval = int(os.getenv("VIPER_JOB_SCAN_INTERVAL", "30"))

    if "--stream" in sys.argv:
        if not _reddit_configured():
            log.info("Reddit not configured — stream not started")
            return
        log.info("Starting Reddit stream only...")
        _start_reddit_stream()

    elif "--loop" in sys.argv:
        # Start Reddit stream in background (only if configured)
        if _reddit_configured():
            stream_thread = threading.Thread(target=_start_reddit_stream, daemon=True)
            stream_thread.start()
            log.info("Reddit stream started in background")
        else:
            log.info("Reddit not configured — stream skipped")

        # Run scanner loop in main thread
        run_loop(interval_minutes=interval)

    else:
        # Single scan
        result = run_scan()
        print(f"Scan complete: {result}")


if __name__ == "__main__":
    main()

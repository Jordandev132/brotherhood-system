"""Viper Lead Engine — standalone runner.

Modes:
  --loop     : Run scanner loop (30min interval, all sources)
  --scan     : Single scan cycle (default)
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/polymarket-bot/.env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from viper.job_hunter import run_scan, run_loop
from viper.tg_callback_poller import start_polling


def main():
    log = logging.getLogger(__name__)
    interval = int(os.getenv("VIPER_JOB_SCAN_INTERVAL", "30"))

    # Start BID/SKIP callback pollers for Viper bots (daemon threads)
    start_polling()

    if "--loop" in sys.argv:
        log.info("Starting Viper Job Hunter loop (interval=%d min)", interval)
        log.info("Sources: HN + Google Alerts + Reddit + RemoteOK + WWR")
        run_loop(interval_minutes=interval)
    else:
        # Single scan
        result = run_scan()
        print(f"Scan complete: {result}")


if __name__ == "__main__":
    main()

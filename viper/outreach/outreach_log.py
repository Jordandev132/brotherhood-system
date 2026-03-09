"""SQLite outreach log — tracks every email sent, prevents duplicates."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

_DB_PATH = Path.home() / "polymarket-bot" / "data" / "outreach_log.db"
_TZ = ZoneInfo("America/New_York")


def _get_db() -> sqlite3.Connection:
    """Get or create the outreach log database."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS outreach (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name TEXT NOT NULL,
            email TEXT NOT NULL,
            niche TEXT DEFAULT '',
            city TEXT DEFAULT '',
            subject TEXT DEFAULT '',
            score REAL DEFAULT 0,
            demo_url TEXT DEFAULT '',
            status TEXT DEFAULT 'sent',
            sendgrid_status INTEGER DEFAULT 0,
            error TEXT DEFAULT '',
            prospect_data TEXT DEFAULT '{}',
            sent_at TEXT NOT NULL,
            reply_at TEXT DEFAULT '',
            UNIQUE(email, niche, city)
        )
    """)
    conn.commit()
    return conn


def already_contacted(email: str, niche: str = "", city: str = "") -> bool:
    """Check if we already emailed this prospect."""
    conn = _get_db()
    row = conn.execute(
        "SELECT id FROM outreach WHERE email = ? AND niche = ? AND city = ?",
        (email, niche, city),
    ).fetchone()
    conn.close()
    return row is not None


def log_outreach(
    business_name: str,
    email: str,
    niche: str,
    city: str,
    subject: str,
    score: float,
    demo_url: str,
    sendgrid_status: int,
    error: str = "",
    prospect_data: dict | None = None,
) -> int:
    """Log an outreach attempt. Returns the row ID."""
    now = datetime.now(_TZ).isoformat(timespec="seconds")
    status = "sent" if sendgrid_status in range(200, 300) else "failed"

    conn = _get_db()
    try:
        cursor = conn.execute(
            """INSERT INTO outreach
               (business_name, email, niche, city, subject, score, demo_url,
                status, sendgrid_status, error, prospect_data, sent_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                business_name, email, niche, city, subject, score, demo_url,
                status, sendgrid_status, error,
                json.dumps(prospect_data or {}),
                now,
            ),
        )
        conn.commit()
        row_id = cursor.lastrowid
        log.info("Logged outreach #%d to %s (%s)", row_id, business_name, status)
        return row_id
    except sqlite3.IntegrityError:
        log.info("Duplicate outreach to %s skipped", email)
        return 0
    finally:
        conn.close()


def get_outreach_stats() -> dict:
    """Return outreach stats for reporting."""
    conn = _get_db()
    total = conn.execute("SELECT COUNT(*) FROM outreach").fetchone()[0]
    sent = conn.execute("SELECT COUNT(*) FROM outreach WHERE status='sent'").fetchone()[0]
    failed = conn.execute("SELECT COUNT(*) FROM outreach WHERE status='failed'").fetchone()[0]
    replied = conn.execute("SELECT COUNT(*) FROM outreach WHERE reply_at != ''").fetchone()[0]
    conn.close()
    return {"total": total, "sent": sent, "failed": failed, "replied": replied}

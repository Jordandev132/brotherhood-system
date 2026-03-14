"""Leads Pipeline Dashboard routes: /api/leads/*"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, jsonify

log = logging.getLogger(__name__)
leads_bp = Blueprint("leads", __name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
OUTREACH_QUEUE = DATA_DIR / "outreach_queue.json"
OUTREACH_SEQ = DATA_DIR / "outreach_sequences.json"

ET = timezone(timedelta(hours=-5))

NICHE_COLORS = {
    "dental": "#3b82f6",
    "dental practice": "#3b82f6",
    "real estate": "#10b981",
    "realty": "#10b981",
    "commercial real estate": "#7c3aed",
    "hvac": "#f59e0b",
    "legal": "#ef4444",
    "law": "#ef4444",
    "med spa": "#ec4899",
    "medspa": "#ec4899",
    "periodontics": "#3b82f6",
}

# Simple TTL cache to avoid re-reading JSON every 10s
_cache: dict = {}


def _niche_color(niche: str) -> str:
    if not niche:
        return "#64748b"
    n = niche.lower().strip()
    for key, color in NICHE_COLORS.items():
        if key in n:
            return color
    return "#64748b"


def _load_json_cached(path: Path, ttl: int = 30):
    """Load JSON with stat-based TTL cache."""
    now = time.monotonic()
    entry = _cache.get(path)
    if entry:
        try:
            mtime = path.stat().st_mtime if path.exists() else 0
        except OSError:
            mtime = 0
        if now - entry["ts"] < ttl and mtime == entry["mtime"]:
            return entry["data"]
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        _cache[path] = {"data": data, "ts": now, "mtime": path.stat().st_mtime}
        return data
    except Exception:
        return None


@leads_bp.route("/api/leads/pipeline")
def api_leads_pipeline():
    """Full pipeline data for the Leads Dashboard."""
    now = time.time()

    queue = _load_json_cached(OUTREACH_QUEUE) or []
    sequences = _load_json_cached(OUTREACH_SEQ) or []

    # Single pass over queue for all counters + lead table
    stage_counts: dict[str, int] = {}
    gate1_count = 0
    gate2_count = 0
    sent_today = 0
    leads_table = []

    today_start = datetime.now(ET).replace(hour=0, minute=0, second=0, microsecond=0)

    for l in queue:
        s = l.get("status", "unknown")
        stage_counts[s] = stage_counts.get(s, 0) + 1

        if s == "approved":
            gate1_count += 1
            if l.get("email"):
                gate2_count += 1
        elif s == "sent":
            da = l.get("decided_at") or l.get("queued_at", "")
            if da and isinstance(da, str):
                try:
                    dt = datetime.fromisoformat(da.replace("Z", "+00:00"))
                    if dt >= today_start:
                        sent_today += 1
                except Exception:
                    pass

        prospect = l.get("prospect_data", {}) or {}
        leads_table.append({
            "id": l.get("id", ""),
            "business_name": l.get("business_name", ""),
            "niche": l.get("niche", ""),
            "niche_color": _niche_color(l.get("niche", "")),
            "city": prospect.get("city", ""),
            "state": prospect.get("state", ""),
            "score": l.get("score", 0),
            "contact_name": l.get("contact_name", ""),
            "email": l.get("email", ""),
            "stage": s,
            "demo_url": l.get("demo_url", ""),
            "queued_at": l.get("queued_at", ""),
            "decided_at": l.get("decided_at", ""),
        })

    # Build batches from sequences grouped by niche
    batches: dict[str, dict] = {}
    for seq in sequences:
        niche = seq.get("niche", "unknown")
        batch_key = niche
        if batch_key not in batches:
            batches[batch_key] = {
                "name": niche.title(),
                "niche": niche,
                "niche_color": _niche_color(niche),
                "leads": [],
                "sent": 0,
                "opened": 0,
                "clicked": 0,
                "replied": 0,
                "no_response": 0,
                "status": "ACTIVE",
                "created_at": seq.get("created_at", ""),
            }
        b = batches[batch_key]
        b["leads"].append(seq)
        b["sent"] += 1
        st = seq.get("status", "")
        if st == "replied":
            b["replied"] += 1
        elif st == "clicked":
            b["clicked"] += 1
        elif st == "opened":
            b["opened"] += 1
        else:
            b["no_response"] += 1

    batch_list = sorted(batches.values(), key=lambda x: x.get("created_at", ""), reverse=True)

    return jsonify({
        "counters": {
            "gate1_waiting": gate1_count,
            "gate2_waiting": gate2_count,
            "sent_today": sent_today,
            "total_pipeline": len(queue),
            "total_sent": stage_counts.get("sent", 0),
            "total_declined": stage_counts.get("declined", 0),
        },
        "stage_counts": stage_counts,
        "batches": batch_list,
        "leads": leads_table,
        "sequences_count": len(sequences),
        "sequences_paused": sum(1 for s in sequences if s.get("status") == "paused"),
        "updated": now,
    })

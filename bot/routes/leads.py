"""Leads Pipeline Dashboard routes: /api/leads/*"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from flask import Blueprint, jsonify

log = logging.getLogger(__name__)
leads_bp = Blueprint("leads", __name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
OUTREACH_QUEUE = DATA_DIR / "outreach_queue.json"
OUTREACH_SEQ = DATA_DIR / "outreach_sequences.json"
VIPER_LEADS = DATA_DIR / "viper_leads.json"
OUTREACH_LOG = DATA_DIR / "outreach_log.db"

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


def _niche_color(niche: str) -> str:
    if not niche:
        return "#64748b"
    n = niche.lower().strip()
    for key, color in NICHE_COLORS.items():
        if key in n:
            return color
    return "#64748b"


def _load_json(path: Path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return None
    return None


@leads_bp.route("/api/leads/pipeline")
def api_leads_pipeline():
    """Full pipeline data for the Leads Dashboard."""
    now = time.time()

    queue = _load_json(OUTREACH_QUEUE) or []
    sequences = _load_json(OUTREACH_SEQ) or []

    # Stage counts
    stage_counts = {}
    for lead in queue:
        s = lead.get("status", "unknown")
        stage_counts[s] = stage_counts.get(s, 0) + 1

    # Gate 1: scored 50+ waiting for BID (approved but not yet sent)
    gate1 = [l for l in queue if l.get("status") == "approved"]
    # Gate 2: ready to send (have email, waiting for GO)
    gate2 = [l for l in queue if l.get("status") == "approved" and l.get("email")]
    # Sent today
    today_start = now - (now % 86400)
    sent_today = 0
    for l in queue:
        if l.get("status") == "sent":
            da = l.get("decided_at") or l.get("queued_at", "")
            if da:
                try:
                    from datetime import datetime
                    if isinstance(da, str):
                        dt = datetime.fromisoformat(da.replace("Z", "+00:00"))
                        if dt.timestamp() >= today_start:
                            sent_today += 1
                except Exception:
                    pass

    # Build batches from sequences grouped by niche+city
    batches = {}
    for seq in sequences:
        niche = seq.get("niche", "unknown")
        biz = seq.get("business_name", "")
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

    # Full lead table
    leads_table = []
    for l in queue:
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
            "stage": l.get("status", "unknown"),
            "demo_url": l.get("demo_url", ""),
            "queued_at": l.get("queued_at", ""),
            "decided_at": l.get("decided_at", ""),
        })

    return jsonify({
        "counters": {
            "gate1_waiting": len(gate1),
            "gate2_waiting": len(gate2),
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

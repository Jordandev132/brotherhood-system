"""Finances API — Brotherhood financial tracking endpoints."""
from __future__ import annotations

import sys
from pathlib import Path

from flask import Blueprint, jsonify

# shared/ is not a package — add to path
sys.path.insert(0, str(Path.home() / "shared"))

finances_bp = Blueprint("finances", __name__)


def _get_module():
    """Lazy import to avoid circular issues."""
    import finances as fin
    return fin


@finances_bp.route("/api/finances")
def api_finances():
    """Full finances data + live monthly summary."""
    fin = _get_module()
    data = fin._load()
    summary = fin.get_monthly_summary()
    alerts = fin.get_alerts()
    renewals = fin.get_upcoming_renewals()
    return jsonify({
        "subscriptions": data.get("subscriptions", []),
        "api_costs": data.get("api_costs", []),
        "one_time_costs": data.get("one_time_costs", []),
        "revenue": data.get("revenue", []),
        "summary": summary,
        "alerts": alerts,
        "upcoming_renewals": renewals,
        "updated_at": data.get("updated_at"),
    })


@finances_bp.route("/api/finances/summary")
def api_finances_summary():
    """Current month: costs, revenue, net, by_project."""
    fin = _get_module()
    return jsonify(fin.get_monthly_summary())


@finances_bp.route("/api/finances/alerts")
def api_finances_alerts():
    """Upcoming renewals and cost alerts."""
    fin = _get_module()
    return jsonify({
        "alerts": fin.get_alerts(),
        "upcoming_renewals": fin.get_upcoming_renewals(),
    })

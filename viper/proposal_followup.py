"""Proposal follow-up email sequence engine.

SEPARATE from cold outreach sequences. This handles prospects who received
a Thor-generated proposal but haven't responded.

5-step sequence:
  Day 2  — Confirm receipt
  Day 5  — Industry insight (niche-specific, no pitch)
  Day 9  — Social proof (niche-specific case study)
  Day 14 — Urgency (proposal expiry)
  Day 21 — Break-up (graceful close)

Each email: plain text, conversational, under 60 words, from Jordan.
Auto-starts when Thor generates and sends a proposal.
Auto-cancels on reply detection.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

ET = timezone(timedelta(hours=-5))

_SEQUENCES_FILE = Path.home() / "polymarket-bot" / "data" / "proposal_sequences.json"

_CAN_SPAM_FOOTER = (
    "\n\n---\n"
    "DarkCode AI | darkcodeai.carrd.co\n"
    "Reply \"unsubscribe\" to stop hearing from me."
)

# ── Niche-specific content ──────────────────────────────────────────

_NICHE_ALIASES = {
    "dentist": "dental",
    "dental practice": "dental",
    "dental office": "dental",
    "real estate": "real_estate",
    "real estate agency": "real_estate",
    "realtor": "real_estate",
    "realty": "real_estate",
    "hvac": "hvac",
    "hvac company": "hvac",
    "heating": "hvac",
    "lawyer": "legal",
    "law firm": "legal",
    "attorney": "legal",
    "legal": "legal",
    "med spa": "med_spa",
    "medspa": "med_spa",
    "medical spa": "med_spa",
}

_INSIGHTS = {
    "dental": "67% of dental patients who can't book online will call a competitor instead. AI chatbots handle booking 24/7 — no missed appointments, no lost revenue.",
    "real_estate": "Real estate leads go cold in under 5 minutes. An AI assistant responds instantly, even at 2 AM — so you never lose a buyer to a faster agent.",
    "hvac": "HVAC emergency calls after hours are worth 3x a regular service call. AI catches every one — no voicemail, no lost revenue.",
    "legal": "78% of potential legal clients contact multiple firms. The first firm that responds wins the case. AI makes you first, every time.",
    "med_spa": "Med spa clients book impulsively — if your booking isn't instant, they scroll to the next one. AI captures that impulse 24/7.",
}

_SOCIAL_PROOF = {
    "dental": "A dental practice in NH added our AI assistant and captured 23 more appointments in the first month — that's $34,500 in lifetime value.",
    "real_estate": "A real estate team using our chatbot saw 40% more scheduled showings from their website traffic within the first 3 weeks.",
    "hvac": "An HVAC company went from missing 12 after-hours calls per week to catching every single one. Their after-hours revenue jumped 200%.",
    "legal": "A law firm's client intake rate jumped 35% after adding 24/7 AI-powered screening. They're now the first to respond to every inquiry.",
    "med_spa": "A med spa doubled their online bookings within 3 weeks of adding an AI booking assistant. Zero extra staff hours.",
}

_DEFAULT_INSIGHT = "Businesses that respond to inquiries within 5 minutes are 21x more likely to close the deal. AI makes that possible 24/7."
_DEFAULT_PROOF = "A business we worked with saw a 40% increase in captured leads within the first month of adding our AI assistant."


def _normalize_niche(niche: str) -> str:
    n = (niche or "").lower().strip()
    return _NICHE_ALIASES.get(n, n)


# ── Templates ───────────────────────────────────────────────────────

def _build_steps(niche: str, contact_name: str, business_name: str, proposal_amount: str) -> list[dict]:
    nk = _normalize_niche(niche)
    first = contact_name.split()[0] if contact_name else ""
    greeting = f"Hi {first}" if first else "Hi there"
    insight = _INSIGHTS.get(nk, _DEFAULT_INSIGHT)
    proof = _SOCIAL_PROOF.get(nk, _DEFAULT_PROOF)

    return [
        {
            "step": 1,
            "day": 2,
            "type": "confirm",
            "subject": f"Quick follow-up — {business_name} proposal",
            "body": (
                f"{greeting},\n\n"
                f"Just confirming you received the proposal I sent over for {business_name}. "
                f"Any questions I can answer?\n\n"
                f"Happy to hop on a quick call if that's easier.\n\n"
                f"— Jordan"
            ),
        },
        {
            "step": 2,
            "day": 5,
            "type": "insight",
            "subject": f"Thought you'd find this interesting",
            "body": (
                f"{greeting},\n\n"
                f"{insight}\n\n"
                f"Just thought it was relevant given what we discussed. No pitch — just sharing.\n\n"
                f"— Jordan"
            ),
        },
        {
            "step": 3,
            "day": 9,
            "type": "proof",
            "subject": f"Quick result I wanted to share",
            "body": (
                f"{greeting},\n\n"
                f"{proof}\n\n"
                f"Happy to walk you through how it would work for {business_name} specifically.\n\n"
                f"— Jordan"
            ),
        },
        {
            "step": 4,
            "day": 14,
            "type": "urgency",
            "subject": f"Proposal update — {business_name}",
            "body": (
                f"{greeting},\n\n"
                f"The proposal I sent for {business_name} ({proposal_amount}) "
                f"is valid for another 7 days.\n\n"
                f"Want to hop on a quick call before then? "
                f"I can answer any questions in 15 minutes.\n\n"
                f"— Jordan"
            ),
        },
        {
            "step": 5,
            "day": 21,
            "type": "breakup",
            "subject": f"Closing the loop — {business_name}",
            "body": (
                f"{greeting},\n\n"
                f"Seems like the timing might not be right, and I totally understand.\n\n"
                f"I'll keep your demo live for another week in case you want to revisit. "
                f"Here if anything changes.\n\n"
                f"All the best,\nJordan"
            ),
        },
    ]


# ── Persistence ─────────────────────────────────────────────────────

def _load() -> list[dict]:
    if _SEQUENCES_FILE.exists():
        try:
            return json.loads(_SEQUENCES_FILE.read_text())
        except Exception:
            return []
    return []


def _save(sequences: list[dict]) -> None:
    _SEQUENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SEQUENCES_FILE.write_text(json.dumps(sequences, indent=2, ensure_ascii=False))


# ── Public API ──────────────────────────────────────────────────────

def create_proposal_sequence(
    lead_id: str,
    business_name: str,
    contact_name: str,
    niche: str,
    email: str,
    proposal_amount: str,
) -> str:
    """Create a 5-step proposal follow-up sequence.

    Returns the sequence ID.
    """
    sequences = _load()

    # Don't create duplicate for same lead
    for s in sequences:
        if s.get("lead_id") == lead_id and s.get("status") == "active":
            log.info("Proposal sequence already exists for lead %s", lead_id)
            return s["id"]

    now = datetime.now(ET)
    seq_id = uuid.uuid4().hex[:8]
    steps = _build_steps(niche, contact_name, business_name, proposal_amount)

    for step in steps:
        step["due_at"] = (now + timedelta(days=step["day"])).isoformat()
        step["sent_at"] = None
        step["approved"] = False

    sequence = {
        "id": seq_id,
        "lead_id": lead_id,
        "business_name": business_name,
        "contact_name": contact_name,
        "niche": niche,
        "email": email,
        "proposal_amount": proposal_amount,
        "created_at": now.isoformat(),
        "status": "active",
        "steps": steps,
    }

    sequences.append(sequence)
    _save(sequences)
    log.info("Created proposal follow-up sequence %s for %s", seq_id, business_name)
    return seq_id


def get_pending_followups() -> list[dict]:
    """Get all steps that are due today or earlier and haven't been sent."""
    now = datetime.now(ET)
    sequences = _load()
    pending = []

    for seq in sequences:
        if seq.get("status") != "active":
            continue
        for step in seq.get("steps", []):
            if step.get("sent_at"):
                continue
            due = datetime.fromisoformat(step["due_at"])
            if due <= now:
                pending.append({
                    "seq_id": seq["id"],
                    "lead_id": seq["lead_id"],
                    "business_name": seq["business_name"],
                    "contact_name": seq["contact_name"],
                    "email": seq["email"],
                    "niche": seq["niche"],
                    "proposal_amount": seq["proposal_amount"],
                    "step_number": step["step"],
                    "step_type": step["type"],
                    "subject": step["subject"],
                    "body": step["body"] + _CAN_SPAM_FOOTER,
                    "due_at": step["due_at"],
                })
                break  # Only one step at a time per sequence

    return pending


def mark_step_sent(sequence_id: str, step_number: int) -> bool:
    """Mark a step as sent."""
    sequences = _load()
    for seq in sequences:
        if seq["id"] != sequence_id:
            continue
        for step in seq["steps"]:
            if step["step"] == step_number:
                step["sent_at"] = datetime.now(ET).isoformat()
                _save(sequences)
                log.info("Marked step %d sent for sequence %s", step_number, sequence_id)

                # If last step, mark sequence complete
                if step_number == 5:
                    seq["status"] = "completed"
                    _save(sequences)
                return True
    return False


def cancel_sequence(sequence_id: str, reason: str = "") -> bool:
    """Cancel a sequence (e.g., prospect replied)."""
    sequences = _load()
    for seq in sequences:
        if seq["id"] == sequence_id:
            seq["status"] = "cancelled"
            seq["cancelled_at"] = datetime.now(ET).isoformat()
            seq["cancel_reason"] = reason
            _save(sequences)
            log.info("Cancelled proposal sequence %s: %s", sequence_id, reason)
            return True
    return False


def cancel_by_lead_id(lead_id: str, reason: str = "prospect_replied") -> int:
    """Cancel all active sequences for a lead. Returns count cancelled."""
    sequences = _load()
    count = 0
    for seq in sequences:
        if seq.get("lead_id") == lead_id and seq.get("status") == "active":
            seq["status"] = "cancelled"
            seq["cancelled_at"] = datetime.now(ET).isoformat()
            seq["cancel_reason"] = reason
            count += 1
    if count:
        _save(sequences)
        log.info("Cancelled %d proposal sequences for lead %s", count, lead_id)
    return count


def get_active_sequences() -> list[dict]:
    """Get all non-cancelled, non-completed sequences."""
    return [s for s in _load() if s.get("status") == "active"]


def get_sequence_stats() -> dict:
    """Summary stats for all proposal sequences."""
    sequences = _load()
    return {
        "total": len(sequences),
        "active": sum(1 for s in sequences if s.get("status") == "active"),
        "completed": sum(1 for s in sequences if s.get("status") == "completed"),
        "cancelled": sum(1 for s in sequences if s.get("status") == "cancelled"),
    }

"""Demo Builder — generates custom chatbot demo HTML for each prospect.

Reads the generic niche template from ~/chatbot-demos/, scrapes the
prospect's website for real business data, then produces a fully
customized demo page with accurate QA_DATA, team info, hours, etc.

Called by the Gate 1 YES callback to build a demo before Gate 2.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

REPO_DIR = Path.home() / "chatbot-demos"

# Template slugs by niche
_TEMPLATE_MAP = {
    "dental": "dental-demo",
    "real_estate": "realestate-demo",
}

# Placeholder names/phones in generic templates
_DENTAL_PLACEHOLDERS = {
    "name": "Demo Dental Practice",
    "phone": "555-123-4567",
    "tagline": "Your Neighborhood Dental Office",
}

_REALESTATE_PLACEHOLDERS = {
    "name": "Demo Realty Group",
    "phone": "(555) 987-6543",
    "tagline": "Your Trusted Real Estate Partner",
}


def build_demo_html(
    business_name: str,
    niche: str,
    website: str,
    prospect_data: dict,
) -> str:
    """Build a custom chatbot demo HTML page.

    1. Scrape the prospect's website for detailed business info
    2. Read the generic niche template
    3. Customize with real business data
    4. Return the full HTML string

    Args:
        business_name: The business name (e.g. "Belmont Periodontics")
        niche: The niche key (e.g. "dental", "real_estate")
        website: The business website URL
        prospect_data: Dict from LocalProspect.to_dict()

    Returns:
        The customized HTML string ready to deploy.
    """
    # 1. Scrape for real business data
    scraped = _scrape_for_demo(website)

    # 2. Read the generic template
    template_slug = _TEMPLATE_MAP.get(niche, "dental-demo")
    template_path = REPO_DIR / template_slug / "index.html"
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    template = template_path.read_text()

    # 3. Gather all available data (scraped > prospect_data > defaults)
    phone = prospect_data.get("phone", "") or (scraped.phone if scraped else "") or ""
    address = (scraped.address if scraped else "") or ""
    email_addr = prospect_data.get("email", "") or (scraped.email if scraped else "") or ""
    team = (scraped.team_members if scraped else []) or []
    hours = (scraped.hours if scraped else "") or ""
    services = (scraped.services if scraped else []) or []
    insurance = (scraped.insurance_plans if scraped else []) or []
    tagline = (scraped.tagline if scraped else "") or (scraped.description if scraped else "") or ""
    brand_color = (scraped.brand_color if scraped else "") or ""

    # 4. Apply customizations based on niche
    if niche == "real_estate":
        html = _customize_realestate(template, business_name, phone, address,
                                     email_addr, team, hours, tagline, brand_color)
    else:
        # Default to dental
        html = _customize_dental(template, business_name, phone, address,
                                 email_addr, team, hours, services, insurance,
                                 tagline, brand_color)

    log.info("[DEMO_BUILDER] Built demo for %s (niche=%s, team=%d, services=%d)",
             business_name, niche, len(team), len(services))
    return html


def _scrape_for_demo(website: str):
    """Scrape the business website for demo-relevant data."""
    if not website:
        return None
    try:
        from viper.demos.scraper import scrape_business
        return scrape_business(website)
    except Exception as e:
        log.warning("[DEMO_BUILDER] Scrape failed for %s: %s", website, e)
        return None


def _js_escape(s: str) -> str:
    """Escape a string for safe embedding in JavaScript."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'").replace("\n", "\\n")


def _customize_dental(
    template: str,
    name: str,
    phone: str,
    address: str,
    email: str,
    team: list[str],
    hours: str,
    services: list[str],
    insurance: list[str],
    tagline: str,
    brand_color: str,
) -> str:
    """Customize the generic dental template with real business data."""
    old = _DENTAL_PLACEHOLDERS
    html = template

    # ── HTML replacements ──
    html = re.sub(r"<title>.*?</title>",
                  f"<title>{_html_escape(name)} - AI Assistant Demo</title>", html)
    html = html.replace(f"<h1>{old['name']}</h1>", f"<h1>{_html_escape(name)}</h1>")
    html = html.replace(f"<p>{old['tagline']}</p>",
                        f"<p>{_html_escape(tagline or 'Your Trusted Dental Care Provider')}</p>")
    html = html.replace(f"<h4>{old['name']}</h4>", f"<h4>{_html_escape(name)}</h4>")

    # Brand color
    if brand_color and brand_color != "#2563eb":
        html = re.sub(r"--brand:\s*#[0-9a-fA-F]{6};", f"--brand: {brand_color};", html)

    # ── JavaScript variable replacements ──
    html = re.sub(r'var BUSINESS_NAME = ".*?";',
                  f'var BUSINESS_NAME = "{_js_escape(name)}";', html)
    html = re.sub(r'var PHONE = ".*?";',
                  f'var PHONE = "{_js_escape(phone or old["phone"])}";', html)

    # Replace DOCTOR_DATA if we have team members
    if team:
        doctor_js = _build_doctor_data_js(team)
        html = re.sub(r"var DOCTOR_DATA = \[.*?\];", f"var DOCTOR_DATA = {doctor_js};",
                      html, flags=re.DOTALL)

    # ── QA_DATA customization ──
    html = _customize_qa_data(html, old["name"], name, old["phone"], phone or old["phone"],
                              team=team, hours=hours, services=services,
                              insurance=insurance, address=address, email=email,
                              niche="dental")

    # ── QUICK_ACTIONS customization ──
    quick = [
        {"label": "Book Appointment", "q": "How do I book an appointment?"},
        {"label": "Insurance", "q": "Do you accept my insurance?"},
        {"label": "Services", "q": "What services do you offer?"},
        {"label": "Emergency", "q": "Do you handle dental emergencies?"},
    ]
    html = re.sub(r"var QUICK_ACTIONS = \[.*?\];",
                  f"var QUICK_ACTIONS = {json.dumps(quick)};",
                  html, flags=re.DOTALL)

    # ── Bulk phone replacement for any remaining references ──
    if phone and phone != old["phone"]:
        html = html.replace(old["phone"], phone)

    return html


def _customize_realestate(
    template: str,
    name: str,
    phone: str,
    address: str,
    email: str,
    team: list[str],
    hours: str,
    tagline: str,
    brand_color: str,
) -> str:
    """Customize the generic real estate template with real business data."""
    old = _REALESTATE_PLACEHOLDERS
    html = template

    # ── HTML replacements ──
    html = re.sub(r"<title>.*?</title>",
                  f"<title>{_html_escape(name)} - AI Assistant Demo</title>", html)
    html = html.replace(f"<h1>{old['name']}</h1>", f"<h1>{_html_escape(name)}</h1>")
    html = html.replace(f'<div class="tagline">{old["tagline"]}</div>',
                        f'<div class="tagline">{_html_escape(tagline or "Your Trusted Real Estate Partner")}</div>')
    html = html.replace(f"<h4>{old['name']}</h4>", f"<h4>{_html_escape(name)}</h4>")

    # ── JavaScript variable replacements ──
    html = re.sub(r'var BUSINESS_NAME = ".*?";',
                  f'var BUSINESS_NAME = "{_js_escape(name)}";', html)
    html = re.sub(r'var PHONE = ".*?";',
                  f'var PHONE = "{_js_escape(phone or old["phone"])}";', html)

    # Replace AGENT_DATA if we have team members
    if team:
        agent_js = _build_agent_data_js(team)
        html = re.sub(r"var AGENT_DATA = \[.*?\];", f"var AGENT_DATA = {agent_js};",
                      html, flags=re.DOTALL)

    # ── QA_DATA customization ──
    html = _customize_qa_data(html, old["name"], name, old["phone"], phone or old["phone"],
                              team=team, hours=hours, address=address, email=email,
                              niche="real_estate")

    # ── Bulk phone/name replacement for any remaining references ──
    if phone and phone != old["phone"]:
        html = html.replace(old["phone"], phone)
    html = html.replace(old["name"], name)

    return html


def _customize_qa_data(
    html: str,
    old_name: str,
    new_name: str,
    old_phone: str,
    new_phone: str,
    team: list[str] | None = None,
    hours: str = "",
    services: list[str] | None = None,
    insurance: list[str] | None = None,
    address: str = "",
    email: str = "",
    niche: str = "dental",
) -> str:
    """Parse QA_DATA from the template HTML, customize entries, and replace."""
    # Extract the QA_DATA JSON array from the template
    m = re.search(r"var QA_DATA = (\[.*?\]);", html, re.DOTALL)
    if not m:
        log.warning("[DEMO_BUILDER] Could not find QA_DATA in template")
        return html

    try:
        qa = json.loads(m.group(1))
    except json.JSONDecodeError:
        log.warning("[DEMO_BUILDER] Could not parse QA_DATA JSON")
        return html

    # 1. Replace name and phone in ALL entries
    for entry in qa:
        entry["a"] = entry["a"].replace(old_name, new_name).replace(old_phone, new_phone)

    # 2. Update hours entry if we have real hours
    if hours:
        for entry in qa:
            if entry.get("cat") == "hours":
                entry["a"] = (f"We're open {hours}.\n\n"
                              f"Call us at {new_phone} if you need to confirm availability.")
                break

    # 3. Update insurance entry if we have real insurance plans
    if insurance:
        plans_text = ", ".join(insurance[:10])
        for entry in qa:
            if entry.get("cat") == "insurance" and "accept" in entry.get("q", "").lower():
                entry["a"] = (f"We accept a wide range of dental insurance, including:\n\n"
                              f"{plans_text}.\n\n"
                              f"Not sure if yours is covered? Call us at {new_phone} "
                              f"and we'll verify your benefits for free.")
                break

    # 4. Update services entry if we have real services
    if services:
        svc_text = ", ".join(services[:12])
        for entry in qa:
            if entry.get("cat") == "services" and "offer" in entry.get("q", "").lower():
                entry["a"] = (f"At {new_name}, we offer {svc_text}. "
                              f"We're here for all your needs!\n\n"
                              f"Call {new_phone} to schedule a consultation.")
                break

    # 5. Update location entry if we have real address
    if address:
        for entry in qa:
            if entry.get("cat") == "location":
                entry["a"] = (f"We're located at {address}.\n\n"
                              f"Call us at {new_phone} for directions.")
                break

    # 6. Update email entry
    if email:
        for entry in qa:
            if entry.get("cat") == "contact" and "email" in entry.get("q", "").lower():
                entry["a"] = f"You can email us at {email}, or call {new_phone}."
                break

    # 7. Rebuild team/doctor entries if we have real team data
    if team:
        # Remove generic team/doctor entries
        qa = [e for e in qa if e.get("cat") not in ("team", "doctor", "agent")]

        if niche == "dental":
            qa.extend(_build_dental_team_qa(team, new_name, new_phone))
        elif niche == "real_estate":
            qa.extend(_build_realestate_team_qa(team, new_name, new_phone))

    # Serialize back and replace in HTML
    qa_json = json.dumps(qa, ensure_ascii=False)
    html = re.sub(r"var QA_DATA = \[.*?\];", f"var QA_DATA = {qa_json};",
                  html, flags=re.DOTALL)
    return html


def _build_dental_team_qa(team: list[str], name: str, phone: str) -> list[dict]:
    """Generate QA entries for dental team members."""
    entries = []

    # Team overview
    if len(team) == 1:
        team_text = f"Our doctor is {team[0]}."
    else:
        team_list = "\n".join(f"- {t}" for t in team)
        team_text = f"We have {len(team)} doctors on our team:\n\n{team_list}"

    entries.append({
        "q": "Who are your dentists?",
        "a": f"{team_text}\n\nCall {phone} to schedule with any of our doctors.",
        "kw": ["dentist", "doctor", "who", "team", "staff", "provider", "dr",
               "doctors", "how many", "meet the team"],
        "cat": "team",
    })

    # Individual doctor entries
    for member in team:
        parts = member.split()
        # Extract last name for keyword matching
        last_name = ""
        first_name = ""
        if len(parts) >= 2:
            # Handle "Dr. Firstname Lastname" or "Firstname Lastname, DDS"
            clean_parts = [p.rstrip(",") for p in parts if p not in ("Dr.", "Dr", "DMD", "DDS", "MD")]
            if clean_parts:
                first_name = clean_parts[0].lower()
                last_name = clean_parts[-1].lower() if len(clean_parts) > 1 else ""

        kw = [last_name, first_name] if last_name else [first_name]
        kw = [k for k in kw if k]  # Remove empty

        entries.append({
            "q": f"Tell me about {member}",
            "a": f"{member} is part of our team at {name}. "
                 f"Call {phone} to schedule an appointment.",
            "kw": kw + [f"dr {last_name}"] if last_name else kw,
            "cat": "doctor",
        })

    return entries


def _build_realestate_team_qa(team: list[str], name: str, phone: str) -> list[dict]:
    """Generate QA entries for real estate team members."""
    entries = []

    if len(team) == 1:
        team_text = f"Our lead agent is {team[0]}."
    else:
        team_list = "\n".join(f"- {t}" for t in team)
        team_text = f"We have {len(team)} experienced agents on our team:\n\n{team_list}"

    entries.append({
        "q": "Who are your agents?",
        "a": f"{team_text}\n\nCall {phone} to connect with the right agent for your needs!",
        "kw": ["agents", "agent", "team", "staff", "who works", "realtors", "realtor",
               "meet the team", "your team"],
        "cat": "team",
    })

    for member in team:
        parts = member.split()
        last_name = parts[-1].lower().rstrip(",") if len(parts) >= 2 else parts[0].lower()
        first_name = parts[0].lower()

        entries.append({
            "q": f"Tell me about {member}",
            "a": f"{member} is part of our team at {name}. "
                 f"Call {phone} to connect with {parts[0]}.",
            "kw": [last_name, first_name],
            "cat": "agent",
        })

    return entries


def _build_doctor_data_js(team: list[str]) -> str:
    """Build the DOCTOR_DATA JavaScript array from team member names."""
    docs = []
    for member in team:
        parts = member.split()
        clean = [p.rstrip(",") for p in parts if p not in ("DMD", "DDS", "MD", "PhD")]
        last_name = clean[-1].lower() if len(clean) >= 2 else clean[0].lower() if clean else ""
        specialty = "General Dentist"

        docs.append(f'{{name: "{_js_escape(member)}", '
                    f'lastName: "{last_name}", '
                    f'specialty: "{specialty}"}}')

    return "[" + ", ".join(docs) + "]"


def _build_agent_data_js(team: list[str]) -> str:
    """Build the AGENT_DATA JavaScript array from team member names."""
    agents = []
    for member in team:
        parts = member.split()
        last_name = parts[-1].lower().rstrip(",") if len(parts) >= 2 else parts[0].lower()

        agents.append(f'{{name: "{_js_escape(member)}", '
                      f'lastName: "{last_name}", '
                      f'specialty: "Real Estate Agent"}}')

    return "[" + ", ".join(agents) + "]"


def _html_escape(s: str) -> str:
    """Basic HTML escaping."""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))

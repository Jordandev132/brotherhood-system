"""SendGrid email sender for cold outreach.

Free tier: 100 emails/day. Requires SENDGRID_API_KEY in .env.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


def _load_config() -> tuple[str, str, str]:
    """Load SendGrid config from env or .env file.

    Returns (api_key, from_email, from_name).
    """
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    from_email = os.environ.get("SENDGRID_FROM_EMAIL", "")
    from_name = os.environ.get("SENDGRID_FROM_NAME", "DarkCode AI")

    if not api_key or not from_email:
        env_path = Path.home() / "polymarket-bot" / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("SENDGRID_API_KEY=") and not api_key:
                    api_key = line.split("=", 1)[1].strip()
                elif line.startswith("SENDGRID_FROM_EMAIL=") and not from_email:
                    from_email = line.split("=", 1)[1].strip()
                elif line.startswith("SENDGRID_FROM_NAME="):
                    from_name = line.split("=", 1)[1].strip()

    return api_key, from_email, from_name


def send_email(
    to_email: str,
    subject: str,
    body: str,
    to_name: str = "",
) -> dict:
    """Send a single email via SendGrid.

    Returns dict with 'success', 'status_code', 'error' keys.
    """
    api_key, from_email, from_name = _load_config()

    if not api_key:
        return {
            "success": False,
            "status_code": 0,
            "error": "SENDGRID_API_KEY not configured. Add to .env file.",
        }
    if not from_email:
        return {
            "success": False,
            "status_code": 0,
            "error": "SENDGRID_FROM_EMAIL not configured. Add to .env file.",
        }

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email, To, Content

        message = Mail(
            from_email=Email(from_email, from_name),
            to_emails=To(to_email, to_name),
            subject=subject,
            plain_text_content=Content("text/plain", body),
        )

        sg = SendGridAPIClient(api_key)
        response = sg.send(message)

        success = 200 <= response.status_code < 300
        if success:
            log.info("Email sent to %s (status %d)", to_email, response.status_code)
        else:
            log.warning("SendGrid returned %d for %s", response.status_code, to_email)

        return {
            "success": success,
            "status_code": response.status_code,
            "error": "" if success else f"HTTP {response.status_code}",
        }

    except Exception as e:
        log.error("SendGrid error for %s: %s", to_email, e)
        return {
            "success": False,
            "status_code": 0,
            "error": str(e),
        }

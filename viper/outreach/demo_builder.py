"""Demo Builder — builds custom chatbot demo HTML by calling Thor's skill directly.

Bypasses the Thor task queue (which doesn't handle demo_build natively) and
calls the demo_builder skill in ~/thor/skills/demo_builder.py directly.
This is synchronous, fast (~1s), and doesn't require Thor to be running.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_SKILL_PATH = Path.home() / "thor" / "skills" / "demo_builder.py"

def _load_skill():
    """Load Thor's demo_builder skill module."""
    spec = importlib.util.spec_from_file_location("thor_demo_builder", str(_SKILL_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_demo_html(
    business_name: str,
    niche: str,
    website: str,
    prospect_data: dict,
) -> str:
    """Build a custom chatbot demo HTML page.

    Calls Thor's demo_builder skill directly (no task queue, no LLM required).
    The skill scrapes the business website and builds the customized HTML.

    Returns:
        The customized HTML string ready to deploy.

    Raises:
        RuntimeError: if the skill fails to build the HTML.
    """
    log.info("[DEMO_BUILDER] Building demo for %s (niche=%s, site=%s)",
             business_name, niche, website)
    mod = _load_skill()
    html = mod.build_demo_html(
        business_name=business_name,
        niche=niche,
        website=website,
        prospect_data=prospect_data,
    )
    if not html:
        raise RuntimeError(f"[DEMO_BUILDER] Skill returned empty HTML for {business_name}")
    log.info("[DEMO_BUILDER] Demo built for %s (%d bytes)", business_name, len(html))
    return html


def run_quality_gate(html: str, niche: str = "auto") -> tuple[bool, list[str]]:
    """Run 7-question quality gate on the built HTML."""
    mod = _load_skill()
    return mod.run_quality_gate(html, niche)

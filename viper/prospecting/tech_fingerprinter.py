"""Tech stack fingerprinter — detect CMS, chat widgets, frameworks, hosting.

Uses python-Wappalyzer for static HTML analysis. Falls back to DIY
pattern matching if Wappalyzer detects <3 technologies.

Cost: $0 (open source library + regex).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, asdict

log = logging.getLogger(__name__)

# ── Extended chat widget signatures (30+) ──────────────────────────────
# Extends the 14 in chatbot_detector.py with additional platforms.
_CHAT_SIGNATURES: list[tuple[str, list[str]]] = [
    ("Intercom", ["intercom", "widget.intercom.io", "intercomSettings"]),
    ("Drift", ["drift.com", "driftt.com", "drift-widget"]),
    ("Tawk.to", ["tawk.to", "embed.tawk.to"]),
    ("Tidio", ["tidio", "tidioChatCode", "code.tidio.co"]),
    ("LiveChat", ["livechatinc.com", "cdn.livechatinc.com", "__lc_inited"]),
    ("Zendesk Chat", ["zopim", "zendesk.com/embeddable", "zdassets.com"]),
    ("Freshchat", ["freshchat", "wchat.freshchat.com"]),
    ("Crisp", ["crisp.chat", "client.crisp.chat"]),
    ("HubSpot Chat", ["hubspot.com/conversations", "js.hs-scripts.com", "hbspt"]),
    ("Olark", ["olark", "static.olark.com"]),
    ("Chatwoot", ["chatwoot", "app.chatwoot.com"]),
    ("Botpress", ["botpress", "cdn.botpress.cloud"]),
    ("ManyChat", ["manychat", "mcwidget"]),
    ("Landbot", ["landbot", "cdn.landbot.io"]),
    # Extended signatures (V3)
    ("LivePerson", ["liveperson", "lpTag", "lptag"]),
    ("Gorgias", ["gorgias", "gorgias-chat"]),
    ("Kommunicate", ["kommunicate", "widget.kommunicate.io"]),
    ("Userlike", ["userlike", "userlikedata"]),
    ("SmartSupp", ["smartsupp", "smartsuppchat"]),
    ("JivoChat", ["jivosite", "jivo-chat"]),
    ("LiveAgent", ["liveagent", "live-agent-chat"]),
    ("Chatra", ["chatra", "call.chatra.io"]),
    ("Podium", ["podium", "connect.podium.com"]),
    ("Birdeye", ["birdeye", "birdeye.com/widget"]),
    ("Acquire", ["acquire.io", "acquire-chat"]),
    ("Zoho SalesIQ", ["zoho.com/salesiq", "salesiq", "zsalesiq"]),
    ("Kayako", ["kayako", "kayako.com/messenger"]),
    ("Pure Chat", ["purechat", "app.purechat.com"]),
    ("ClickDesk", ["clickdesk", "cdn.clickdesk.com"]),
    ("Reamaze", ["reamaze", "cdn.reamaze.com"]),
    ("Gladly", ["gladly", "cdn.gladly.com"]),
    ("Verloop", ["verloop", "verloop.io"]),
]

# ── CMS detection patterns ─────────────────────────────────────────────
_CMS_SIGNATURES: list[tuple[str, list[str]]] = [
    ("WordPress", ["wp-content", "wp-includes", "wp-json"]),
    ("Squarespace", ["squarespace.com", "static1.squarespace.com"]),
    ("Wix", ["wix.com", "parastorage.com", "_wix"]),
    ("Shopify", ["cdn.shopify.com", "myshopify.com", "Shopify.theme"]),
    ("Webflow", ["webflow.com", "assets.website-files.com"]),
    ("Weebly", ["weebly.com", "editmysite.com"]),
    ("GoDaddy", ["godaddy.com", "secureserver.net"]),
    ("Joomla", ["joomla", "/components/com_"]),
    ("Drupal", ["drupal", "sites/default/files"]),
    ("Ghost", ["ghost.io", "ghost-url"]),
    ("HubSpot CMS", ["hs-scripts.com", "hubspot.net/hub/"]),
]

# ── Ecommerce detection ────────────────────────────────────────────────
_ECOMMERCE_SIGNATURES: list[tuple[str, list[str]]] = [
    ("Shopify", ["cdn.shopify.com", "myshopify.com"]),
    ("WooCommerce", ["woocommerce", "wc-cart"]),
    ("BigCommerce", ["bigcommerce.com", "cdn11.bigcommerce.com"]),
    ("Magento", ["magento", "mage/cookies"]),
    ("PrestaShop", ["prestashop", "presta"]),
    ("Squarespace Commerce", ["squarespace.com/commerce"]),
]

# ── Hosting / CDN detection ────────────────────────────────────────────
_HOSTING_SIGNATURES: list[tuple[str, list[str]]] = [
    ("Cloudflare", ["cloudflare", "cf-ray"]),
    ("AWS", ["amazonaws.com", "cloudfront.net"]),
    ("Netlify", ["netlify", "netlify.app"]),
    ("Vercel", ["vercel", "vercel.app", "now.sh"]),
    ("Google Cloud", ["googleapis.com", "gstatic.com"]),
    ("Heroku", ["herokuapp.com"]),
    ("GoDaddy Hosting", ["secureserver.net"]),
    ("Bluehost", ["bluehost.com"]),
    ("DigitalOcean", ["digitaloceanspaces.com"]),
]

# ── Framework detection ────────────────────────────────────────────────
_FRAMEWORK_SIGNATURES: list[tuple[str, list[str]]] = [
    ("React", ["react", "__NEXT_DATA__", "reactroot"]),
    ("Angular", ["ng-app", "ng-controller", "angular.js"]),
    ("Vue.js", ["vue.js", "__vue__", "vuejs"]),
    ("jQuery", ["jquery", "jquery.min.js"]),
    ("Bootstrap", ["bootstrap.min.css", "bootstrap.min.js"]),
    ("Tailwind CSS", ["tailwindcss", "tailwind.css"]),
    ("Next.js", ["__NEXT_DATA__", "_next/static"]),
    ("Gatsby", ["gatsby", "gatsby-image"]),
]


@dataclass
class TechStackResult:
    """Technology stack fingerprint for a website."""
    technologies: dict = field(default_factory=dict)  # {category: [tech_names]}
    chat_widgets: list[str] = field(default_factory=list)
    cms: str = ""
    ecommerce: str = ""
    hosting: str = ""
    frameworks: list[str] = field(default_factory=list)
    total_detected: int = 0
    method: str = "diy"  # "wappalyzer" or "diy"

    def to_dict(self) -> dict:
        return asdict(self)


def _detect_from_signatures(
    html_lower: str,
    signatures: list[tuple[str, list[str]]],
) -> list[str]:
    """Match HTML against signature lists. Returns matched names."""
    matched: list[str] = []
    for name, markers in signatures:
        for marker in markers:
            if marker.lower() in html_lower:
                if name not in matched:
                    matched.append(name)
                break
    return matched


def _diy_fingerprint(html: str) -> TechStackResult:
    """DIY fingerprinting using regex pattern matching.

    Extends the 14 chatbot signatures from chatbot_detector.py to 30+.
    Also detects CMS, ecommerce, hosting, and frameworks.
    """
    result = TechStackResult(method="diy")
    html_lower = html.lower()

    # Chat widgets
    result.chat_widgets = _detect_from_signatures(html_lower, _CHAT_SIGNATURES)

    # CMS
    cms_matches = _detect_from_signatures(html_lower, _CMS_SIGNATURES)
    if cms_matches:
        result.cms = cms_matches[0]

    # Ecommerce
    ecom_matches = _detect_from_signatures(html_lower, _ECOMMERCE_SIGNATURES)
    if ecom_matches:
        result.ecommerce = ecom_matches[0]

    # Hosting / CDN
    hosting_matches = _detect_from_signatures(html_lower, _HOSTING_SIGNATURES)
    if hosting_matches:
        result.hosting = hosting_matches[0]

    # Frameworks
    result.frameworks = _detect_from_signatures(html_lower, _FRAMEWORK_SIGNATURES)

    # Build technologies dict
    techs: dict[str, list[str]] = {}
    if result.chat_widgets:
        techs["chat"] = result.chat_widgets
    if result.cms:
        techs["cms"] = [result.cms]
    if result.ecommerce:
        techs["ecommerce"] = [result.ecommerce]
    if result.hosting:
        techs["hosting"] = [result.hosting]
    if result.frameworks:
        techs["frameworks"] = result.frameworks
    if hosting_matches:
        techs["hosting"] = hosting_matches

    result.technologies = techs
    result.total_detected = sum(len(v) for v in techs.values())

    return result


def _wappalyzer_fingerprint(url: str, html: str) -> TechStackResult | None:
    """Wappalyzer-based fingerprinting. Returns None if not available."""
    try:
        from Wappalyzer import Wappalyzer, WebPage
    except ImportError:
        log.debug("python-Wappalyzer not installed, using DIY only")
        return None

    try:
        wappalyzer = Wappalyzer.latest()
        webpage = WebPage.new_from_response_text(url, html)
        detected = wappalyzer.analyze_with_categories(webpage)

        result = TechStackResult(method="wappalyzer")
        techs: dict[str, list[str]] = {}

        for tech_name, categories in detected.items():
            for cat in categories.get("categories", []):
                cat_name = cat.lower()
                if cat_name not in techs:
                    techs[cat_name] = []
                techs[cat_name].append(tech_name)

        result.technologies = techs
        result.total_detected = sum(len(v) for v in techs.values())

        # Extract specific fields
        for name in techs.get("live chat", []) + techs.get("chatbots", []):
            if name not in result.chat_widgets:
                result.chat_widgets.append(name)

        cms_list = techs.get("cms", [])
        if cms_list:
            result.cms = cms_list[0]

        ecom_list = techs.get("ecommerce", [])
        if ecom_list:
            result.ecommerce = ecom_list[0]

        hosting_list = techs.get("hosting", []) + techs.get("paas", []) + techs.get("cdn", [])
        if hosting_list:
            result.hosting = hosting_list[0]

        result.frameworks = techs.get("javascript frameworks", [])

        return result

    except Exception as e:
        log.debug("Wappalyzer failed for %s: %s", url[:60], e)
        return None


def fingerprint_tech_stack(url: str, html: str = "") -> TechStackResult:
    """Fingerprint a website's tech stack.

    Strategy:
    1. Try Wappalyzer first (most comprehensive)
    2. If Wappalyzer finds <3 techs, augment with DIY patterns
    3. If Wappalyzer unavailable, use DIY only

    Args:
        url: Website URL.
        html: Raw HTML (if already fetched). If empty, Wappalyzer fetches it.

    Returns:
        TechStackResult with detected technologies.
    """
    if not html and not url:
        return TechStackResult()

    # Try Wappalyzer
    wap_result = None
    if html:
        wap_result = _wappalyzer_fingerprint(url, html)

    # If Wappalyzer found enough, return it
    if wap_result and wap_result.total_detected >= 3:
        log.info("[TECH] Wappalyzer detected %d techs for %s", wap_result.total_detected, url[:60])
        return wap_result

    # DIY fingerprinting (standalone or augmenting Wappalyzer)
    if html:
        diy_result = _diy_fingerprint(html)
    else:
        return wap_result or TechStackResult()

    # If no Wappalyzer, return DIY
    if not wap_result:
        log.info("[TECH] DIY detected %d techs for %s", diy_result.total_detected, url[:60])
        return diy_result

    # Merge: Wappalyzer + DIY extras
    merged = wap_result
    for cat, names in diy_result.technologies.items():
        if cat not in merged.technologies:
            merged.technologies[cat] = names
        else:
            for n in names:
                if n not in merged.technologies[cat]:
                    merged.technologies[cat].append(n)

    # Merge chat widgets
    for w in diy_result.chat_widgets:
        if w not in merged.chat_widgets:
            merged.chat_widgets.append(w)

    if not merged.cms and diy_result.cms:
        merged.cms = diy_result.cms
    if not merged.ecommerce and diy_result.ecommerce:
        merged.ecommerce = diy_result.ecommerce
    if not merged.hosting and diy_result.hosting:
        merged.hosting = diy_result.hosting
    for fw in diy_result.frameworks:
        if fw not in merged.frameworks:
            merged.frameworks.append(fw)

    merged.total_detected = sum(len(v) for v in merged.technologies.values())
    log.info("[TECH] Merged: %d techs for %s", merged.total_detected, url[:60])
    return merged

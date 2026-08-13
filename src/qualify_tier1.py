"""Stage B: free qualification tier using the `website` field Google Maps
already gave us in Stage A. A lightweight HEAD request (not a full page
load) confirms the URL actually resolves before we reject on it.
"""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger("pipeline.tier1")

TIER1_REJECT = "reject_has_website"
TIER1_PASS = "pass"
TIER1_REJECT_CLOSED = "reject_closed"


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    return url


def website_resolves(url: str, timeout_seconds: float) -> bool:
    try:
        resp = requests.head(_normalize_url(url), timeout=timeout_seconds, allow_redirects=True)
        return resp.status_code < 400
    except requests.RequestException:
        return False


def qualify_tier1(lead: dict, timeout_seconds: float, treat_unresolvable_as_qualified: bool) -> str:
    """Returns one of TIER1_REJECT / TIER1_PASS / TIER1_REJECT_CLOSED."""
    if lead.get("permanently_closed"):
        return TIER1_REJECT_CLOSED

    website = lead.get("website")
    if not website:
        return TIER1_PASS

    resolves = website_resolves(website, timeout_seconds)
    if resolves:
        return TIER1_REJECT

    # Website field present but dead/unresolvable: config decides whether
    # that counts as "doesn't really have a working site" (pass to tier 2)
    # or as a reject (they at least attempted a site).
    logger.info("tier1_unresolvable_website business=%s website=%s", lead.get("business_name"), website)
    return TIER1_PASS if treat_unresolvable_as_qualified else TIER1_REJECT

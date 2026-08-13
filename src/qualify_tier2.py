"""Stage C: cheap qualification tier for leads that passed Tier 1 (no
resolvable website on the Maps listing itself). Runs one live search API
query per lead and checks whether a plausibly-matching site turns up --
this is a real search call, not an LLM guess, since an LLM without a live
tool call cannot verify current information.

Supports Serper.dev and Searlo; both have generous free tiers suitable for
the pilot. Quota usage is tracked in the `tier2_quota` DB table (keyed by
provider + calendar month) so the pipeline can pause this stage gracefully
-- and only this stage -- once the free quota is exhausted, per spec.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from urllib.parse import urlparse

import requests

from src.dedup import name_similarity, normalize_name

logger = logging.getLogger("pipeline.tier2")

TIER2_PASS = "pass"
TIER2_REJECT = "reject_found_site"
TIER2_PENDING_QUOTA = "pending_quota_exhausted"


class Tier2QuotaExhausted(Exception):
    pass


def _current_period() -> str:
    return time.strftime("%Y-%m")


def check_and_reserve_quota(conn: sqlite3.Connection, provider: str, monthly_limit: int) -> None:
    period = _current_period()
    row = conn.execute(
        "SELECT queries_used FROM tier2_quota WHERE provider=? AND period=?", (provider, period)
    ).fetchone()
    used = row["queries_used"] if row else 0
    if used >= monthly_limit:
        raise Tier2QuotaExhausted(f"{provider} free quota ({monthly_limit}/mo) exhausted for {period}")

    conn.execute(
        """INSERT INTO tier2_quota (provider, period, queries_used, queries_limit) VALUES (?,?,1,?)
           ON CONFLICT(provider, period) DO UPDATE SET queries_used = queries_used + 1""",
        (provider, period, monthly_limit),
    )
    conn.commit()


def quota_status(conn: sqlite3.Connection, provider: str, monthly_limit: int) -> dict:
    period = _current_period()
    row = conn.execute(
        "SELECT queries_used FROM tier2_quota WHERE provider=? AND period=?", (provider, period)
    ).fetchone()
    used = row["queries_used"] if row else 0
    return {"provider": provider, "period": period, "used": used, "limit": monthly_limit, "remaining": max(0, monthly_limit - used)}


def _search_serper(query: str, api_key: str, timeout: float) -> list[dict]:
    resp = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return [{"title": r.get("title", ""), "url": r.get("link", "")} for r in data.get("organic", [])]


def _search_searlo(query: str, api_key: str, timeout: float) -> list[dict]:
    resp = requests.get(
        "https://api.searlo.tech/api/v1/search/web",
        headers={"x-api-key": api_key},
        params={"q": query},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return [{"title": r.get("title", ""), "url": r.get("url", "")} for r in data.get("results", [])]


_PROVIDERS = {"serper": _search_serper, "searlo": _search_searlo}


def _domain_matches_business(business_name: str, result_title: str, result_url: str, threshold: float) -> bool:
    norm_name = normalize_name(business_name)
    if not norm_name:
        return False

    if name_similarity(norm_name, normalize_name(result_title)) >= threshold:
        return True

    try:
        domain = urlparse(result_url).netloc.lower()
    except Exception:
        return False
    domain = domain.replace("www.", "").split(".")[0]
    return name_similarity(norm_name.replace(" ", ""), domain) >= threshold


def qualify_tier2(
    lead: dict,
    city: str,
    conn: sqlite3.Connection,
    provider: str,
    api_key: str,
    monthly_limit: int,
    results_to_check: int,
    fuzzy_threshold: float,
    timeout: float,
) -> str:
    """Returns TIER2_PASS or TIER2_REJECT. Raises Tier2QuotaExhausted (caller
    should catch this and mark the lead TIER2_PENDING_QUOTA instead of
    crashing the run).
    """
    if provider not in _PROVIDERS:
        raise ValueError(f"unknown tier2 provider: {provider}")

    check_and_reserve_quota(conn, provider, monthly_limit)

    query = f'"{lead["business_name"]}" {city} Nigeria'
    try:
        results = _PROVIDERS[provider](query, api_key, timeout)
    except requests.RequestException as exc:
        logger.warning("tier2_search_failed business=%s err=%s", lead.get("business_name"), exc)
        # A failed search call is not evidence of an existing site; treat as pass
        # rather than silently rejecting a qualified lead on an API hiccup.
        return TIER2_PASS

    for result in results[:results_to_check]:
        if _domain_matches_business(lead["business_name"], result["title"], result["url"], fuzzy_threshold):
            logger.info("tier2_reject business=%s matched=%s", lead["business_name"], result["url"])
            return TIER2_REJECT

    return TIER2_PASS

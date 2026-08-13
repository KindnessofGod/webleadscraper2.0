"""Stage A (alternative source): Google Places API (New) Text Search.

Why this exists alongside the Playwright scraper: Google Maps' web UI
actively blocks automated browsers coming from commercial proxy ranges --
not with a CAPTCHA page, but by silently never responding, which is
indistinguishable from a network hang. That was reproducible across two
proxy providers and five separate residential exit IPs while plain curl
through the *same* proxy and headless Chromium *without* a proxy both
succeeded, i.e. it is the (browser + proxy-range) combination Google
refuses, and no amount of fingerprint tuning fixes it.

The Places API returns the same fields the scraper was extracting from the
DOM -- crucially `websiteUri`, which is the Tier 1 qualification signal --
as structured JSON, with no proxy, no browser, and no bot-detection fight.
Everything downstream (Tier 1/2 qualification, scoring, dedup, export) is
unchanged; only where the raw leads come from differs.

Cost: billed per request, not per GB, with a monthly free allowance. One
request returns up to 20 places and each grid cell needs only a handful of
requests, so a pilot fits comfortably in the free tier -- but confirm the
current rate and free quota in the Google Cloud console before scaling, and
keep `places_api.max_requests_per_run` set as the hard stop.
"""
from __future__ import annotations

import logging
from typing import Iterator, Optional

import requests

from src.grid import GridCell
from src.scraper import ScrapedLead

logger = logging.getLogger("pipeline.places")

SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
MAX_PAGE_SIZE = 20

# Only request the fields we actually use -- Places API bills by the most
# expensive field tier requested, so asking for extras costs real money.
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.websiteUri",
        "places.nationalPhoneNumber",
        "places.rating",
        "places.userRatingCount",
        "places.businessStatus",
        "places.primaryTypeDisplayName",
        "places.location",
        "places.googleMapsUri",
        "nextPageToken",
    ]
)


class PlacesAPIError(Exception):
    pass


class PlacesQuotaExhausted(PlacesAPIError):
    pass


def _request_page(
    api_key: str,
    text_query: str,
    lat: float,
    lon: float,
    radius_m: float,
    timeout: int,
    page_token: Optional[str] = None,
) -> tuple[dict, int]:
    """One Text Search call. Returns (parsed_json, response_size_bytes)."""
    body: dict = {
        "textQuery": text_query,
        "pageSize": MAX_PAGE_SIZE,
        "locationBias": {
            "circle": {"center": {"latitude": lat, "longitude": lon}, "radius": radius_m}
        },
    }
    if page_token:
        body["pageToken"] = page_token

    resp = requests.post(
        SEARCH_TEXT_URL,
        json=body,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        },
        timeout=timeout,
    )
    size = len(resp.content)

    if resp.status_code == 429:
        raise PlacesQuotaExhausted(f"Places API rate/quota limit hit: {resp.text[:300]}")
    if resp.status_code in (401, 403):
        raise PlacesAPIError(
            f"Places API rejected the key ({resp.status_code}). Check the key is correct, that "
            f"'Places API (New)' is enabled for the project, and that billing is active. "
            f"Response: {resp.text[:300]}"
        )
    if resp.status_code != 200:
        raise PlacesAPIError(f"Places API HTTP {resp.status_code}: {resp.text[:300]}")

    return resp.json(), size


def _to_lead(place: dict, cell: GridCell) -> Optional[ScrapedLead]:
    name = (place.get("displayName") or {}).get("text", "").strip()
    if not name:
        return None

    location = place.get("location") or {}
    return ScrapedLead(
        business_name=name,
        category_raw=(place.get("primaryTypeDisplayName") or {}).get("text"),
        address=place.get("formattedAddress"),
        phone_raw=place.get("nationalPhoneNumber"),
        website=place.get("websiteUri"),
        maps_url=place.get("googleMapsUri"),
        place_id=place.get("id"),
        lat=location.get("latitude", cell.lat),
        lon=location.get("longitude", cell.lon),
        rating=place.get("rating"),
        review_count=place.get("userRatingCount"),
        permanently_closed=place.get("businessStatus") == "CLOSED_PERMANENTLY",
    )


def search_cell(
    api_key: str,
    cell: GridCell,
    query: str,
    radius_m: float,
    max_pages: int,
    timeout: int,
) -> tuple[list[ScrapedLead], int, int]:
    """All results for one grid cell + category, following pagination.

    Returns (leads, bytes_used, requests_made). Each page is a separate
    billable request, hence returning the count for the cost ledger.
    """
    leads: list[ScrapedLead] = []
    total_bytes = 0
    requests_made = 0
    page_token: Optional[str] = None

    for _ in range(max_pages):
        payload, size = _request_page(api_key, query, cell.lat, cell.lon, radius_m, timeout, page_token)
        total_bytes += size
        requests_made += 1

        for place in payload.get("places", []):
            lead = _to_lead(place, cell)
            if lead:
                leads.append(lead)

        page_token = payload.get("nextPageToken")
        if not page_token:
            break

    return leads, total_bytes, requests_made

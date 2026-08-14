"""Load an Apify Google Maps export as Stage A input.

Apify's Google Maps actors do the raw-listing collection better and cheaper
than we can -- they maintain anti-bot infrastructure full time, and Google
silently black-holes automated browsers from commercial proxy ranges (see
src/places_api.py for that story). So rather than compete with them, we
treat their export as a Stage A source and spend our effort on the part
they don't do: qualifying which of those businesses actually lack a
website, tagging, deduping, and scoring.

Accepts the three formats Apify's "Export results" button produces --
JSON, JSONL, and CSV -- and is deliberately tolerant about field names,
because the half-dozen popular Maps actors each name things slightly
differently (`title` vs `name`, `totalScore` vs `rating`, ...).

Usage: python scripts/import_apify.py --file dataset.json --city Lagos
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Optional

from src.scraper import ScrapedLead

# Field aliases across the popular Apify Maps actors. First match wins.
# CSV exports flatten nested objects with "/" (location/lat); JSON exports
# keep them nested, which _get() resolves via dotted paths.
ALIASES: dict[str, tuple[str, ...]] = {
    "business_name": ("title", "name", "businessName", "placeName"),
    "category_raw": ("categoryName", "category", "primaryCategory", "type"),
    "address": ("address", "fullAddress", "formattedAddress", "streetAddress"),
    "phone_raw": ("phone", "phoneUnformatted", "phoneNumber", "telephone"),
    "website": ("website", "webSite", "url_website", "site"),
    "maps_url": ("url", "mapsUrl", "googleMapsUrl", "placeUrl"),
    "place_id": ("placeId", "place_id", "cid", "fid"),
    "lat": ("location/lat", "location.lat", "latitude", "lat"),
    "lon": ("location/lng", "location.lng", "longitude", "lng", "lon"),
    "rating": ("totalScore", "rating", "stars", "averageRating"),
    "review_count": ("reviewsCount", "userRatingCount", "reviews", "numberOfReviews"),
    "permanently_closed": ("permanentlyClosed", "isPermanentlyClosed", "closed"),
}

CITY_KEYS = ("city", "location/city", "address/city", "municipality")
QUERY_KEYS = ("searchString", "searchQuery", "query", "keyword", "categoryName")

# Apify writes these when a field is absent; treat them as missing, not as
# a literal website named "null".
_EMPTY = {"", "null", "none", "n/a", "-", "undefined"}


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in _EMPTY)


def _resolve(row: dict, key: str) -> Any:
    """Look up `key`, treating it as a literal column first and only then as
    a path. CSV exports carry the flattened key verbatim ("location/lat"),
    while JSON exports nest it -- both must resolve.
    """
    if key in row:
        return row[key]
    value: Any = row
    for part in key.replace("/", ".").split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _get(row: dict, keys: Iterable[str]) -> Any:
    """First non-empty value among `keys`, resolving dotted/slashed paths."""
    for key in keys:
        value = _resolve(row, key)
        if not _is_empty(value):
            return value
    return None


def _text(row: dict, field: str) -> Optional[str]:
    value = _get(row, ALIASES[field])
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float(row: dict, field: str) -> Optional[float]:
    value = _get(row, ALIASES[field])
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int(row: dict, field: str) -> Optional[int]:
    value = _float(row, field)
    return int(value) if value is not None else None


def _bool(row: dict, field: str) -> bool:
    value = _get(row, ALIASES[field])
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes"}


def row_to_lead(row: dict) -> Optional[ScrapedLead]:
    """Map one Apify record onto our lead model, or None if unusable.

    A record with no business name is not a lead -- Apify occasionally
    emits placeholder/error rows in a dataset, and they would otherwise
    violate the leads.business_name NOT NULL constraint.
    """
    name = _text(row, "business_name")
    if not name:
        return None
    return ScrapedLead(
        business_name=name,
        category_raw=_text(row, "category_raw"),
        address=_text(row, "address"),
        phone_raw=_text(row, "phone_raw"),
        website=_text(row, "website"),
        maps_url=_text(row, "maps_url"),
        place_id=_text(row, "place_id"),
        lat=_float(row, "lat"),
        lon=_float(row, "lon"),
        rating=_float(row, "rating"),
        review_count=_int(row, "review_count"),
        permanently_closed=_bool(row, "permanently_closed"),
    )


def row_city(row: dict) -> Optional[str]:
    value = _get(row, CITY_KEYS)
    return str(value).strip() or None if value is not None else None


def row_query(row: dict) -> Optional[str]:
    value = _get(row, QUERY_KEYS)
    return str(value).strip() or None if value is not None else None


def load_records(path: Path) -> list[dict]:
    """Read an Apify export. Handles .json, .jsonl/.ndjson and .csv."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    if suffix in {".jsonl", ".ndjson"}:
        with open(path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    if suffix == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Apify exports a bare array; some wrappers nest it under "items".
        if isinstance(data, dict):
            data = data.get("items", data.get("results", []))
        if not isinstance(data, list):
            raise ValueError(f"{path.name}: expected a JSON array of records")
        return data
    raise ValueError(f"{path.name}: unsupported format {suffix!r} (use .json, .jsonl or .csv)")

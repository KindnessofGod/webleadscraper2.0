#!/usr/bin/env python3
"""Verify the Places API key works before running the pipeline.

Makes exactly ONE Places API request and prints what came back, so a bad
key / disabled API / billing problem surfaces immediately instead of
halfway through a run.

Usage: python scripts/check_places_api.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import places_api
from src.config import load_config
from src.grid import GridCell

CELL = GridCell(id="probe", zone="victoria_island", lat=6.4225, lon=3.4055, row=0, col=0)


def main() -> int:
    cfg = load_config()
    if not cfg.places_api_key:
        print("FAIL: PLACES_API_KEY is empty in .env")
        return 1

    print(f"Key loaded (ends ...{cfg.places_api_key[-6:]}). Sending 1 request: 'clinic in Victoria Island, Lagos'\n")
    try:
        leads, size, n = places_api.search_cell(
            cfg.places_api_key, CELL, "clinic in Victoria Island, Lagos",
            radius_m=1500, max_pages=1, timeout=15,
        )
    except places_api.PlacesAPIError as exc:
        print(f"FAIL: {exc}")
        return 1

    print(f"OK -- {n} request, {size} bytes, {len(leads)} places returned.\n")
    websiteless = [lead for lead in leads if not lead.website]
    for lead in leads[:10]:
        mark = "NO SITE <-- lead" if not lead.website else lead.website
        print(f"  {lead.business_name[:40]:42} {lead.phone_raw or 'no phone':18} {mark}")

    print(f"\n{len(websiteless)}/{len(leads)} have no website (these are your Tier 1 candidates).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

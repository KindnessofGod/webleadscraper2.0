#!/usr/bin/env python3
"""Import an Apify Google Maps export as Stage A input, then qualify it.

Apify collects raw Maps listings better and cheaper than we can, so this
replaces Stage A entirely -- no Places API key, no proxy, no browser. Point
it at the file Apify's "Export results" button gave you:

    python scripts/import_apify.py --file dataset.json --city Lagos

It prints a run_id. Feed that to the rest of the pipeline (Stages B-F --
website qualification, niche tagging, dedup, scoring), which is the part
Apify does not do:

    python scripts/run_batch.py --city Lagos --categories imported \\
        --skip-scrape --resume-run-id <run_id>
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db
from src.apify_import import load_records, row_city, row_query, row_to_lead
from src.config import load_config
from src.dedup import normalize_name
from src.logging_setup import setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", required=True, help="Apify export: .json, .jsonl or .csv")
    parser.add_argument("--city", required=True, help="fallback city when a record doesn't carry one")
    parser.add_argument("--category", default=None, help="fallback category when a record doesn't carry one")
    parser.add_argument("--run-id", default=None, help="append to an existing run instead of starting a new one")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"FAIL: {path} not found")
        return 1

    setup_logging()
    cfg = load_config()
    conn = db.connect(cfg.db_path)
    run_id = args.run_id or db.new_run_id()

    records = load_records(path)
    print(f"Read {len(records)} records from {path.name}")

    if not args.run_id:
        db.start_run(conn, run_id, args.city, [args.category or "imported"], json.dumps(cfg.settings))

    seen_place_ids: set[str] = set()
    imported = skipped_unusable = skipped_duplicate = websiteless = 0

    for record in records:
        lead = row_to_lead(record)
        if lead is None:
            skipped_unusable += 1
            continue
        # Apify datasets repeat the same place across overlapping search
        # strings. Exact place_id repeats are cheap to drop here; Stage E
        # still catches the fuzzy near-duplicates this misses.
        if lead.place_id:
            if lead.place_id in seen_place_ids:
                skipped_duplicate += 1
                continue
            seen_place_ids.add(lead.place_id)

        row = {
            "run_id": run_id,
            "place_id": lead.place_id,
            "business_name": lead.business_name,
            "normalized_name": normalize_name(lead.business_name),
            "category_raw": lead.category_raw,
            "address": lead.address,
            "phone_raw": lead.phone_raw,
            "website": lead.website,
            "maps_url": lead.maps_url,
            "lat": lead.lat,
            "lon": lead.lon,
            "rating": lead.rating,
            "review_count": lead.review_count,
            "permanently_closed": int(lead.permanently_closed),
            "source_query": row_query(record) or args.category or "imported",
            "grid_cell_id": "apify_import",
            "city": row_city(record) or args.city,
            "scraped_at": time.time(),
        }
        db.insert_lead(conn, row)
        imported += 1
        if not lead.website:
            websiteless += 1

    db.finish_run(conn, run_id, "completed")
    conn.close()

    print(f"\nImported     {imported}")
    print(f"  no website {websiteless}  <- Tier 1 candidates before verification")
    if skipped_duplicate:
        print(f"Skipped dup  {skipped_duplicate}  (same place_id seen earlier in the file)")
    if skipped_unusable:
        print(f"Skipped bad  {skipped_unusable}  (no business name)")

    print(f"\nrun_id={run_id}")
    print("\nNext -- qualify, tag, dedup and score these leads:")
    print(f"  python scripts/run_batch.py --city {args.city!r} --categories imported "
          f"--skip-scrape --resume-run-id {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

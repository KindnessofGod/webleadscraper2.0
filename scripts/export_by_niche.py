#!/usr/bin/env python3
"""Stage E output: export qualified, deduplicated leads to CSV -- one
master file plus one file per niche.

Usage:
    python scripts/export_by_niche.py [--run-id ID] [--out-dir output]

Qualified = tier1 pass, tier2 pass or pending-quota (not yet checked because
the free search quota ran out -- still a candidate, just unverified), valid
phone number, and not flagged as a duplicate of an earlier row.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.db import get_conn

FIELDS = [
    "id", "business_name", "phone_normalized", "address", "category_raw", "niche",
    "score_tier", "score_value", "website", "maps_url", "rating", "review_count",
    "tier2_status", "source_query", "grid_cell_id", "city", "run_id", "scraped_at",
    "dedup_review",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-id", default=None, help="restrict export to one run; omit to export across all runs")
    parser.add_argument("--out-dir", default="output")
    args = parser.parse_args()

    cfg = load_config()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    query = """
        SELECT * FROM leads
        WHERE tier1_status='pass'
          AND tier2_status IN ('pass','pending_quota_exhausted')
          AND phone_valid=1
          AND is_duplicate=0
    """
    params: tuple = ()
    if args.run_id:
        query += " AND run_id=?"
        params = (args.run_id,)

    with get_conn(cfg.db_path) as conn:
        rows = [dict(r) for r in conn.execute(query, params).fetchall()]

    master_path = out_dir / "master.csv"
    with open(master_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    by_niche: dict[str, list[dict]] = {}
    for row in rows:
        by_niche.setdefault(row.get("niche") or "other", []).append(row)

    for niche, niche_rows in by_niche.items():
        path = out_dir / f"{niche}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(niche_rows)

    print(f"Exported {len(rows)} qualified leads.")
    print(f"  master: {master_path}")
    for niche, niche_rows in sorted(by_niche.items(), key=lambda kv: -len(kv[1])):
        print(f"  {niche}: {len(niche_rows)} -> {out_dir / (niche + '.csv')}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""General-purpose batch runner: scrape -> qualify -> dedup -> summary.

Usage:
    python scripts/run_batch.py --city Lagos --categories clinic "law firm" \\
        [--pilot-only] [--max-leads 500] [--resume-run-id abc123def456]

Resumable: pass --resume-run-id (printed at the end of a previous run, or
looked up via `SELECT run_id FROM runs` in the DB) to continue a run that
was interrupted or paused on the cost ceiling -- already-`done` grid cells
are skipped automatically.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.logging_setup import setup_logging
from src.pipeline import Pipeline


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", required=True)
    parser.add_argument("--categories", nargs="+", required=True)
    parser.add_argument("--pilot-only", action="store_true", help="restrict to grid zones flagged pilot: true")
    parser.add_argument("--max-leads", type=int, default=None)
    parser.add_argument("--resume-run-id", default=None)
    parser.add_argument("--skip-scrape", action="store_true", help="only run qualification/dedup on already-scraped leads")
    args = parser.parse_args()

    setup_logging()
    cfg = load_config()
    pipeline = Pipeline(cfg, run_id=args.resume_run_id)

    print(f"run_id={pipeline.run_id}  (pass --resume-run-id {pipeline.run_id} to continue this run later)")

    try:
        if not args.skip_scrape:
            await pipeline.run_scrape_stage(args.city, args.categories, args.pilot_only, args.max_leads)
        pipeline.run_qualification_stage(args.city)
        pipeline.run_dedup_stage()
        summary = pipeline.run_summary()
        print(json.dumps(summary, indent=2))
    finally:
        pipeline.close()


if __name__ == "__main__":
    asyncio.run(main())

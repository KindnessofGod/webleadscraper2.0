#!/usr/bin/env python3
"""Pilot run scoped to Section 4 of the spec: 200-500 raw leads, one
category, Lagos, 2-3 grid cells. Prints a pass/fail report against the
pilot's required checks at the end.

Usage:
    python scripts/run_pilot.py [--category clinic] [--resume-run-id ID]

Do not scale past a pilot with a FAIL verdict -- fix the underlying issue
(selectors, proxy config, pacing) and re-run first.
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

CITY = "Lagos"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--category", default=None, help="defaults to the first pilot_categories entry in config/categories.yaml")
    parser.add_argument("--resume-run-id", default=None)
    args = parser.parse_args()

    setup_logging()
    cfg = load_config()

    category = args.category or cfg.categories["pilot_categories"][0]["query"]
    target_min = cfg.get("pilot", "target_leads_min", default=200)
    target_max = cfg.get("pilot", "target_leads_max", default=500)
    max_error_rate = cfg.get("pilot", "max_error_rate", default=0.15)
    bandwidth_ceiling_mb = cfg.get("pilot", "bandwidth_ceiling_mb", default=1024)

    pipeline = Pipeline(cfg, run_id=args.resume_run_id)
    print(f"PILOT RUN  run_id={pipeline.run_id}  city={CITY}  category={category}")
    print(f"(pilot zones only, capped at {target_max} leads -- resume with --resume-run-id {pipeline.run_id} if interrupted)\n")

    try:
        await pipeline.run_scrape_stage(CITY, [category], pilot_only=True, max_leads=target_max)
        pipeline.run_qualification_stage(CITY)
        pipeline.run_dedup_stage()
        summary = pipeline.run_summary()
    finally:
        pipeline.close()

    total_leads_scraped = summary["tier1_pass"] + summary["tier1_reject"]
    error_rate = summary["error_rate"]
    bandwidth_mb = summary["cumulative_mb"]
    cost_usd = summary["cumulative_cost_usd"]

    checks = [
        (
            f"Raw leads in target range [{target_min}, {target_max}]",
            target_min <= total_leads_scraped <= target_max * 1.1,  # small overshoot tolerance
            f"scraped {total_leads_scraped} leads",
        ),
        (
            f"Error rate under {max_error_rate:.0%}",
            error_rate <= max_error_rate,
            f"error_rate={error_rate:.2%} ({summary['scrape_error']} errors + {summary['scrape_captcha']} captchas / {summary['total_requests']} requests)",
        ),
        (
            f"Bandwidth well under {bandwidth_ceiling_mb} MB",
            bandwidth_mb <= bandwidth_ceiling_mb,
            f"{bandwidth_mb} MB consumed",
        ),
        (
            "Qualification pipeline produced plausible pass/reject split",
            summary["tier1_pass"] > 0 and summary["tier1_reject"] >= 0,
            f"tier1: {summary['tier1_pass']} pass / {summary['tier1_reject']} reject; "
            f"tier2: {summary['tier2_pass']} pass / {summary['tier2_reject']} reject / {summary['tier2_pending_quota']} pending-quota",
        ),
    ]

    print("=" * 70)
    print("PILOT REPORT (Section 4 checklist)")
    print("=" * 70)
    all_auto_pass = True
    for label, passed, detail in checks:
        status = "PASS" if passed else "FAIL"
        all_auto_pass = all_auto_pass and passed
        print(f"[{status}] {label}\n       {detail}")

    print(f"\nEstimated spend so far: ${cost_usd:.4f}")
    print(f"Qualified leads ready for output: {summary['qualified_final']}")

    print("\nMANUAL checks still required before scaling (Section 4, items 2 and 4):")
    print("  - Spot-check 10-15 'qualified' leads: search their names yourself and confirm")
    print("    they genuinely have no website. Run: python scripts/export_by_niche.py --run-id "
          f"{pipeline.run_id} then sample rows from output/master.csv.")
    print("  - Compare cumulative_cost_usd above against your actual DataImpulse dashboard balance")
    print("    (run: python scripts/check_cost.py) to confirm the estimate tracks real spend.")

    print("\n" + ("OVERALL: AUTOMATED CHECKS PASSED -- complete the two manual checks above before scaling."
                   if all_auto_pass else "OVERALL: FAIL -- do not scale. Fix the failing item(s) above and re-run the pilot."))

    print(f"\nrun_id: {pipeline.run_id}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

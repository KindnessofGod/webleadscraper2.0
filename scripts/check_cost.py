#!/usr/bin/env python3
"""Print current cumulative proxy spend and Tier 2 search-API quota usage.
Run this anytime; it only reads the DB, no network calls, no cost.

Usage: python scripts/check_cost.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.db import get_conn
from src.qualify_tier2 import quota_status


def main() -> None:
    cfg = load_config()
    ceiling = cfg.get("cost", "global_ceiling_usd", default=4.5)

    with get_conn(cfg.db_path) as conn:
        row = conn.execute(
            "SELECT cumulative_bytes, cumulative_cost_usd, timestamp FROM cost_ledger ORDER BY id DESC LIMIT 1"
        ).fetchone()

        print("=== Proxy bandwidth / spend ===")
        if row:
            mb = row["cumulative_bytes"] / (1024 ** 2)
            fraction = row["cumulative_cost_usd"] / ceiling if ceiling else 0
            print(f"  Cumulative bandwidth : {mb:.2f} MB")
            print(f"  Estimated spend      : ${row['cumulative_cost_usd']:.4f}")
            print(f"  Configured ceiling   : ${ceiling:.2f}  ({fraction:.1%} used)")
            if row["cumulative_cost_usd"] >= ceiling:
                print("  *** CEILING REACHED -- pipeline will refuse to start new runs. ***")
        else:
            print("  No spend recorded yet.")

        print("\n  Reminder: cross-check this against your real DataImpulse dashboard balance")
        print("  before scaling (Section 4, pilot check #4).")

        print("\n=== Tier 2 search API quota ===")
        status = quota_status(conn, cfg.tier2_provider, cfg.get("tier2", "free_quota_monthly", default=2500))
        print(f"  Provider : {status['provider']}")
        print(f"  Period   : {status['period']}")
        print(f"  Used     : {status['used']} / {status['limit']}  ({status['remaining']} remaining)")

        print("\n=== Runs ===")
        for run in conn.execute("SELECT run_id, city, categories, status, started_at, finished_at FROM runs ORDER BY started_at DESC LIMIT 10"):
            print(f"  {run['run_id']}  {run['city']:10s} {run['categories']:30s} {run['status']}")


if __name__ == "__main__":
    main()

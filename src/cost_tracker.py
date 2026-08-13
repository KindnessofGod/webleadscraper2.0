"""Bandwidth/cost tracking with a hard spend ceiling.

This is the architectural guardrail called out in the spec: every batch of
proxy bandwidth used gets logged to cost_ledger with a running cumulative
total, and CostCeilingExceeded is raised (not just logged) the moment the
configured ceiling is hit -- callers MUST stop the run, they cannot ignore it.
"""
from __future__ import annotations

import logging
import sqlite3
import time

from src import db

logger = logging.getLogger("pipeline.cost")


class CostCeilingExceeded(Exception):
    def __init__(self, cumulative_cost_usd: float, ceiling_usd: float):
        self.cumulative_cost_usd = cumulative_cost_usd
        self.ceiling_usd = ceiling_usd
        super().__init__(
            f"Cost ceiling hit: ${cumulative_cost_usd:.4f} spent >= ${ceiling_usd:.2f} ceiling. Pipeline paused."
        )


class CostTracker:
    def __init__(self, conn: sqlite3.Connection, run_id: str, price_usd_per_gb: float, ceiling_usd: float, warn_at_fraction: float = 0.75):
        self.conn = conn
        self.run_id = run_id
        self.price_per_byte = price_usd_per_gb / (1024 ** 3)
        self.ceiling_usd = ceiling_usd
        self.warn_at_fraction = warn_at_fraction
        self._warned = False
        row = conn.execute(
            "SELECT COALESCE(MAX(cumulative_bytes),0) b, COALESCE(MAX(cumulative_cost_usd),0) c FROM cost_ledger"
        ).fetchone()
        self.cumulative_bytes: int = row["b"]
        self.cumulative_cost_usd: float = row["c"]

    def check_ceiling(self) -> None:
        if self.cumulative_cost_usd >= self.ceiling_usd:
            raise CostCeilingExceeded(self.cumulative_cost_usd, self.ceiling_usd)

    def record(self, bytes_used: int, batch_id: str, note: str = "") -> None:
        """Record bandwidth consumed by a batch, then re-check the ceiling.

        The ceiling check happens *after* recording so the ledger reflects
        the true spend even on the batch that trips it, but the exception
        still propagates so the caller stops before the next batch starts.
        """
        cost = bytes_used * self.price_per_byte
        self.cumulative_bytes += bytes_used
        self.cumulative_cost_usd += cost
        self.conn.execute(
            """INSERT INTO cost_ledger
               (timestamp, run_id, batch_id, bytes_used, estimated_cost_usd, cumulative_bytes, cumulative_cost_usd, note)
               VALUES (?,?,?,?,?,?,?,?)""",
            (time.time(), self.run_id, batch_id, bytes_used, cost, self.cumulative_bytes, self.cumulative_cost_usd, note),
        )
        self.conn.commit()
        logger.info(
            "cost_ledger batch=%s bytes=%d cost=$%.4f cumulative=$%.4f/%.2f",
            batch_id, bytes_used, cost, self.cumulative_cost_usd, self.ceiling_usd,
        )

        if not self._warned and self.cumulative_cost_usd >= self.ceiling_usd * self.warn_at_fraction:
            self._warned = True
            logger.warning(
                "cost_warning cumulative=$%.4f has crossed %.0f%% of ceiling $%.2f",
                self.cumulative_cost_usd, self.warn_at_fraction * 100, self.ceiling_usd,
            )

        self.check_ceiling()

    def status(self) -> dict:
        return {
            "cumulative_bytes": self.cumulative_bytes,
            "cumulative_mb": round(self.cumulative_bytes / (1024 ** 2), 3),
            "cumulative_cost_usd": round(self.cumulative_cost_usd, 4),
            "ceiling_usd": self.ceiling_usd,
            "fraction_used": round(self.cumulative_cost_usd / self.ceiling_usd, 4) if self.ceiling_usd else None,
        }

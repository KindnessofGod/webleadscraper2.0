"""Orchestrates Stage A (scrape) through Stage E (dedup + niche tagging),
resumable via the `checkpoints` table and hard-stopped by the cost ceiling.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import asdict
from typing import Optional

from playwright.async_api import async_playwright

from src import db, places_api
from src.config import Config
from src.cost_tracker import CostCeilingExceeded, CostTracker
from src.dedup import dedup_leads, normalize_name
from src.grid import GridCell, cells_for_grid_config
from src.niche import normalize_niche
from src.phone import is_valid_nigerian_phone, normalize_phone
from src.qualify_tier1 import TIER1_PASS, qualify_tier1
from src.qualify_tier2 import TIER2_PENDING_QUOTA, Tier2QuotaExhausted, qualify_tier2
from src.scoring import score_lead, score_tier
from src.scraper import launch_browser, scrape_grid_cell_with_retry

logger = logging.getLogger("pipeline.orchestrator")


class Pipeline:
    def __init__(self, cfg: Config, run_id: Optional[str] = None):
        self.cfg = cfg
        self.conn = db.connect(cfg.db_path)
        self.run_id = run_id or db.new_run_id()
        self._resuming = run_id is not None

    # ---------------------------------------------------------- Stage A ---
    async def run_scrape_stage(self, city: str, categories: list[str], pilot_only: bool, max_leads: Optional[int] = None) -> None:
        if self.cfg.source_provider == "places_api":
            self._run_places_stage(city, categories, pilot_only, max_leads)
            return
        if self.cfg.source_provider != "maps_scrape":
            raise ValueError(
                f"unknown SOURCE_PROVIDER: {self.cfg.source_provider!r} (expected 'places_api' or 'maps_scrape')"
            )
        await self._run_browser_scrape_stage(city, categories, pilot_only, max_leads)

    def _persist_leads(self, leads: list, city: str, category: str, cell_id: str) -> int:
        for lead in leads:
            row = asdict(lead)
            row.update(
                run_id=self.run_id, source_query=category, grid_cell_id=cell_id, city=city,
                scraped_at=time.time(), normalized_name=normalize_name(lead.business_name),
                permanently_closed=int(lead.permanently_closed),
            )
            db.insert_lead(self.conn, row)
        return len(leads)

    def _run_places_stage(self, city: str, categories: list[str], pilot_only: bool, max_leads: Optional[int]) -> None:
        """Stage A via Google's Places API -- no browser, no proxy. One
        request per page of up to 20 results per grid cell per category.
        """
        if not self.cfg.places_api_key:
            raise ValueError("PLACES_API_KEY is empty -- set it in .env (see README 'Google Places API setup')")

        grid_cfg = self.cfg.grid_config(city)
        cells = cells_for_grid_config(grid_cfg, pilot_only=pilot_only)
        logger.info(
            "places_stage_start run=%s city=%s categories=%s cells=%d pilot_only=%s",
            self.run_id, city, categories, len(cells), pilot_only,
        )

        if not self._resuming:
            db.start_run(self.conn, self.run_id, city, categories, json.dumps(self.cfg.settings))

        radius_m = self.cfg.get("places_api", "search_radius_meters", default=1500)
        max_pages = self.cfg.get("places_api", "max_pages_per_cell", default=3)
        timeout = self.cfg.get("places_api", "request_timeout_seconds", default=15)
        max_requests = self.cfg.get("places_api", "max_requests_per_run", default=500)

        # Places API bills per request, not per GB, so the dollar ceiling is
        # enforced by max_requests below; the ledger still records real
        # response bytes so the run's footprint stays visible.
        cost = CostTracker(
            self.conn, self.run_id, price_usd_per_gb=0.0,
            ceiling_usd=self.cfg.get("cost", "global_ceiling_usd", default=4.5),
            warn_at_fraction=self.cfg.get("cost", "warn_at_fraction", default=0.75),
        )

        leads_captured = 0
        requests_made = 0

        for category in categories:
            pending = db.pending_cells(self.conn, self.run_id, category, [c.id for c in cells])
            pending_cells = [c for c in cells if c.id in pending]
            logger.info("category_start run=%s category=%s pending_cells=%d", self.run_id, category, len(pending_cells))

            for cell in pending_cells:
                if requests_made >= max_requests:
                    logger.error(
                        "places_request_ceiling_hit run=%s requests=%d >= %d -- pausing run",
                        self.run_id, requests_made, max_requests,
                    )
                    db.finish_run(self.conn, self.run_id, "paused_request_ceiling")
                    return

                db.upsert_checkpoint(self.conn, self.run_id, city, category, cell.id, "in_progress")
                query = f"{category} in {cell.zone}, {city}"
                try:
                    leads, bytes_used, n_requests = places_api.search_cell(
                        self.cfg.places_api_key, cell, query, radius_m, max_pages, timeout
                    )
                    outcome = "pass" if leads else "empty"
                    error_detail = None
                except places_api.PlacesQuotaExhausted as exc:
                    logger.error("places_quota_exhausted run=%s %s -- pausing run", self.run_id, exc)
                    db.upsert_checkpoint(self.conn, self.run_id, city, category, cell.id, "error", 0, "quota_exhausted")
                    db.finish_run(self.conn, self.run_id, "paused_quota_exhausted")
                    return
                except places_api.PlacesAPIError as exc:
                    logger.error("places_request_failed run=%s cell=%s err=%s", self.run_id, cell.id, exc)
                    db.upsert_checkpoint(self.conn, self.run_id, city, category, cell.id, "error", 0, str(exc))
                    db.log_request(
                        self.conn, run_id=self.run_id, stage="places", grid_cell_id=cell.id, query=query,
                        proxy_session_id=None, http_status=None, retry_count=0,
                        outcome="error", error_detail=str(exc), bytes_used=0,
                    )
                    continue

                requests_made += n_requests
                db.log_request(
                    self.conn, run_id=self.run_id, stage="places", grid_cell_id=cell.id, query=query,
                    proxy_session_id=None, http_status=200, retry_count=0,
                    outcome=outcome, error_detail=error_detail, bytes_used=bytes_used,
                )
                cost.record(bytes_used, batch_id=cell.id, note=f"{category}/{cell.id} ({n_requests} req)")

                leads_captured += self._persist_leads(leads, city, category, cell.id)
                db.upsert_checkpoint(self.conn, self.run_id, city, category, cell.id, "done", len(leads))
                logger.info(
                    "cell_done run=%s category=%s cell=%s leads=%d requests=%d/%d",
                    self.run_id, category, cell.id, len(leads), requests_made, max_requests,
                )

                if max_leads and leads_captured >= max_leads:
                    logger.info("max_leads_reached run=%s leads=%d", self.run_id, leads_captured)
                    db.finish_run(self.conn, self.run_id, "completed")
                    logger.info("places_stage_end run=%s leads_captured=%d requests=%d", self.run_id, leads_captured, requests_made)
                    return

        db.finish_run(self.conn, self.run_id, "completed")
        logger.info("places_stage_end run=%s leads_captured=%d requests=%d", self.run_id, leads_captured, requests_made)

    async def _run_browser_scrape_stage(self, city: str, categories: list[str], pilot_only: bool, max_leads: Optional[int] = None) -> None:
        grid_cfg = self.cfg.grid_config(city)
        cells = cells_for_grid_config(grid_cfg, pilot_only=pilot_only)
        zoom = grid_cfg.get("zoom", 15)
        logger.info("scrape_stage_start run=%s city=%s categories=%s cells=%d pilot_only=%s", self.run_id, city, categories, len(cells), pilot_only)

        if not self._resuming:
            db.start_run(self.conn, self.run_id, city, categories, json.dumps(self.cfg.settings))

        is_free_tier = self.cfg.proxy_provider == "webshare"
        cost = CostTracker(
            self.conn, self.run_id,
            price_usd_per_gb=0.0 if is_free_tier else self.cfg.get("cost", "price_usd_per_gb", default=1.0),
            ceiling_usd=self.cfg.get("cost", "global_ceiling_usd", default=4.5),
            warn_at_fraction=self.cfg.get("cost", "warn_at_fraction", default=0.75),
            bandwidth_ceiling_bytes=(
                int(self.cfg.get("cost", "webshare_free_tier_mb", default=950) * 1024 * 1024) if is_free_tier else None
            ),
        )
        cost.check_ceiling()  # refuse to even start a run that's already over budget

        concurrency = self.cfg.get("proxy", "concurrent_sessions", default=8)
        pool = self.cfg.build_proxy_pool(
            concurrent_sessions=concurrency,
            sticky_minutes=self.cfg.get("proxy", "session_sticky_minutes", default=10),
            country=self.cfg.get("proxy", "country", default="ng"),
        )
        logger.info(
            "proxy_provider_active run=%s provider=%s slots=%d",
            self.run_id, self.cfg.proxy_provider,
            len(pool.static_proxies) if self.cfg.proxy_provider == "webshare" else concurrency,
        )

        delay_min = self.cfg.get("pacing", "delay_min_seconds", default=2)
        delay_max = self.cfg.get("pacing", "delay_max_seconds", default=8)
        max_retries = self.cfg.get("pacing", "max_retries", default=3)
        backoff_base = self.cfg.get("pacing", "retry_backoff_base_seconds", default=3)
        captcha_cooldown = self.cfg.get("pacing", "captcha_cooldown_minutes", default=15)

        semaphore = asyncio.Semaphore(concurrency)
        leads_captured = 0
        stop = False

        async with async_playwright() as pw:
            browser = await launch_browser(pw)
            try:
                for category in categories:
                    if stop:
                        break
                    pending = db.pending_cells(self.conn, self.run_id, category, [c.id for c in cells])
                    pending_cells = [c for c in cells if c.id in pending]
                    logger.info("category_start run=%s category=%s pending_cells=%d", self.run_id, category, len(pending_cells))

                    async def run_one(cell: GridCell, slot: int):
                        async with semaphore:
                            db.upsert_checkpoint(self.conn, self.run_id, city, category, cell.id, "in_progress")
                            result, session = await scrape_grid_cell_with_retry(
                                browser, cell, category, pool, slot, zoom, delay_min, delay_max, max_retries, backoff_base
                            )
                            return cell, session, slot, result

                    tasks = [asyncio.ensure_future(run_one(cell, i % concurrency)) for i, cell in enumerate(pending_cells)]
                    for coro in asyncio.as_completed(tasks):
                        cell, session, slot, result = await coro

                        db.log_request(
                            self.conn, run_id=self.run_id, stage="scrape", grid_cell_id=cell.id, query=category,
                            proxy_session_id=session.session_id, http_status=result.http_status,
                            retry_count=result.retry_count, outcome=result.outcome, error_detail=result.error_detail,
                            bytes_used=result.bytes_used,
                        )

                        try:
                            cost.record(result.bytes_used, batch_id=cell.id, note=f"{category}/{cell.id}")
                        except CostCeilingExceeded as exc:
                            logger.error("cost_ceiling_hit run=%s %s", self.run_id, exc)
                            db.upsert_checkpoint(self.conn, self.run_id, city, category, cell.id, "done", len(result.leads))
                            db.finish_run(self.conn, self.run_id, "paused_cost_ceiling")
                            stop = True
                            for t in tasks:
                                if not t.done():
                                    t.cancel()
                            break

                        if result.outcome == "captcha":
                            pool.cooldown(slot, captcha_cooldown)
                            db.upsert_checkpoint(self.conn, self.run_id, city, category, cell.id, "error", 0, "captcha_detected")
                            logger.warning("captcha_cooldown run=%s cell=%s slot=%d minutes=%d", self.run_id, cell.id, slot, captcha_cooldown)
                            continue

                        if result.outcome == "error":
                            db.upsert_checkpoint(self.conn, self.run_id, city, category, cell.id, "error", 0, result.error_detail)
                            continue

                        leads_captured += self._persist_leads(result.leads, city, category, cell.id)

                        db.upsert_checkpoint(self.conn, self.run_id, city, category, cell.id, "done", len(result.leads))
                        logger.info(
                            "cell_done run=%s category=%s cell=%s outcome=%s leads=%d cost_status=%s",
                            self.run_id, category, cell.id, result.outcome, len(result.leads), cost.status(),
                        )

                        if max_leads and leads_captured >= max_leads:
                            logger.info("max_leads_reached run=%s leads=%d", self.run_id, leads_captured)
                            stop = True
                            for t in tasks:
                                if not t.done():
                                    t.cancel()
                            break

                    if stop:
                        break
            finally:
                await browser.close()

        if not stop:
            db.finish_run(self.conn, self.run_id, "completed")
        logger.info("scrape_stage_end run=%s leads_captured=%d cost_status=%s", self.run_id, leads_captured, cost.status())

    # ------------------------------------------------------- Stage B/C/D ---
    def run_qualification_stage(self, city: str) -> None:
        niche_map = self.cfg.categories.get("niche_map", {})
        niche_weights = self.cfg.categories.get("niche_weights", {})
        category_defaults = {c["query"]: c["default_niche"] for c in self.cfg.categories.get("pilot_categories", [])}

        rows = self.conn.execute(
            "SELECT * FROM leads WHERE run_id=? AND tier1_status IS NULL", (self.run_id,)
        ).fetchall()
        logger.info("tier1_stage_start run=%s pending=%d", self.run_id, len(rows))

        timeout = self.cfg.get("tier1", "head_request_timeout_seconds", default=6)
        treat_unresolvable = self.cfg.get("tier1", "treat_unresolvable_as_qualified", default=True)

        tier1_pass = tier1_reject = 0
        for row in rows:
            lead = dict(row)
            status = qualify_tier1(lead, timeout, treat_unresolvable)
            phone_norm = normalize_phone(lead.get("phone_raw"))
            phone_valid = is_valid_nigerian_phone(lead.get("phone_raw"))
            default_niche = category_defaults.get(lead.get("source_query"), "other")
            niche = normalize_niche(lead.get("category_raw"), niche_map, default_niche)
            value = score_lead(niche, niche_weights, lead.get("rating"), lead.get("review_count"))
            tier = score_tier(value, self.cfg.get("scoring", "hot_threshold", default=70), self.cfg.get("scoring", "warm_threshold", default=40))

            self.conn.execute(
                """UPDATE leads SET tier1_status=?, phone_normalized=?, phone_valid=?, niche=?,
                   score_value=?, score_tier=? WHERE id=?""",
                (status, phone_norm, int(phone_valid), niche, value, tier, lead["id"]),
            )
            tier1_pass += status == TIER1_PASS
            tier1_reject += status != TIER1_PASS
        self.conn.commit()
        logger.info("tier1_stage_end run=%s pass=%d reject=%d", self.run_id, tier1_pass, tier1_reject)

        self._run_tier2(city)

    def _run_tier2(self, city: str) -> None:
        provider = self.cfg.tier2_provider
        monthly_limit = self.cfg.get("tier2", "free_quota_monthly", default=2500)
        results_to_check = self.cfg.get("tier2", "results_to_check", default=8)
        fuzzy_threshold = self.cfg.get("tier2", "fuzzy_match_threshold", default=0.55)
        timeout = self.cfg.get("tier2", "request_timeout_seconds", default=8)

        rows = self.conn.execute(
            "SELECT * FROM leads WHERE run_id=? AND tier1_status=? AND tier2_status IS NULL",
            (self.run_id, TIER1_PASS),
        ).fetchall()
        logger.info("tier2_stage_start run=%s pending=%d provider=%s", self.run_id, len(rows), provider)

        tier2_pass = tier2_reject = tier2_pending = 0
        quota_exhausted = False
        for row in rows:
            lead = dict(row)
            if quota_exhausted:
                status = TIER2_PENDING_QUOTA
                tier2_pending += 1
            else:
                try:
                    status = qualify_tier2(
                        lead, city, self.conn, provider, self.cfg.tier2_api_key,
                        monthly_limit, results_to_check, fuzzy_threshold, timeout,
                    )
                    if status == "pass":
                        tier2_pass += 1
                    else:
                        tier2_reject += 1
                except Tier2QuotaExhausted as exc:
                    logger.warning("tier2_quota_exhausted run=%s %s -- remaining leads stay pending", self.run_id, exc)
                    quota_exhausted = True
                    status = TIER2_PENDING_QUOTA
                    tier2_pending += 1

            self.conn.execute(
                "UPDATE leads SET tier2_status=?, tier2_checked_at=? WHERE id=?",
                (status, time.time(), lead["id"]),
            )
        self.conn.commit()
        logger.info("tier2_stage_end run=%s pass=%d reject=%d pending_quota=%d", self.run_id, tier2_pass, tier2_reject, tier2_pending)

    # ----------------------------------------------------------- Stage E ---
    def run_dedup_stage(self) -> None:
        name_threshold = self.cfg.get("dedup", "fuzzy_name_threshold", default=0.85)
        review_threshold = self.cfg.get("dedup", "fuzzy_name_review_threshold", default=0.70)

        rows = self.conn.execute("SELECT id, business_name, normalized_name, phone_normalized, city FROM leads").fetchall()
        leads = [dict(r) for r in rows]
        logger.info("dedup_stage_start total_leads=%d", len(leads))
        deduped = dedup_leads(leads, name_threshold, review_threshold)

        for lead in deduped:
            self.conn.execute(
                "UPDATE leads SET dedup_group_id=?, is_duplicate=?, dedup_review=? WHERE id=?",
                (lead["dedup_group_id"], lead["is_duplicate"], lead.get("dedup_review", 0), lead["id"]),
            )
        self.conn.commit()

        dup_count = sum(1 for lead in deduped if lead["is_duplicate"])
        review_count = sum(1 for lead in deduped if lead.get("dedup_review"))
        logger.info("dedup_stage_end duplicates=%d borderline_flagged=%d", dup_count, review_count)

    # --------------------------------------------------------- Summary  ---
    def run_summary(self) -> dict:
        stats = {}
        for outcome in ("pass", "reject", "error", "captcha", "empty"):
            row = self.conn.execute(
                "SELECT COUNT(*) c FROM requests_log WHERE run_id=? AND outcome=?", (self.run_id, outcome)
            ).fetchone()
            stats[f"scrape_{outcome}"] = row["c"]

        total = self.conn.execute("SELECT COUNT(*) c FROM requests_log WHERE run_id=?", (self.run_id,)).fetchone()["c"]
        errors = stats["scrape_error"] + stats["scrape_captcha"]
        stats["total_requests"] = total
        stats["error_rate"] = round(errors / total, 4) if total else 0.0

        for label, sql in [
            ("tier1_pass", "tier1_status='pass'"),
            ("tier1_reject", "tier1_status IN ('reject_has_website','reject_closed')"),
            ("tier2_pass", "tier2_status='pass'"),
            ("tier2_reject", "tier2_status='reject_found_site'"),
            ("tier2_pending_quota", "tier2_status='pending_quota_exhausted'"),
            ("qualified_final", "tier1_status='pass' AND tier2_status IN ('pass','pending_quota_exhausted') AND phone_valid=1 AND is_duplicate=0"),
        ]:
            row = self.conn.execute(f"SELECT COUNT(*) c FROM leads WHERE run_id=? AND {sql}", (self.run_id,)).fetchone()
            stats[label] = row["c"]

        cost_row = self.conn.execute(
            "SELECT cumulative_bytes, cumulative_cost_usd FROM cost_ledger ORDER BY id DESC LIMIT 1"
        ).fetchone()
        stats["cumulative_bytes"] = cost_row["cumulative_bytes"] if cost_row else 0
        stats["cumulative_mb"] = round(stats["cumulative_bytes"] / (1024 ** 2), 3)
        stats["cumulative_cost_usd"] = round(cost_row["cumulative_cost_usd"], 4) if cost_row else 0.0

        return stats

    def close(self) -> None:
        self.conn.close()

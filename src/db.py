"""SQLite schema + helpers. One file is the whole system of record: leads,
per-request logs, checkpoints (for resume), cost ledger, run summaries and
tier-2 quota usage. SQLite is used deliberately -- zero infra cost, single
file, resumable, good enough for tens of thousands of rows.
"""
from __future__ import annotations

import contextlib
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    finished_at REAL,
    city TEXT NOT NULL,
    categories TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',   -- running | completed | paused_cost_ceiling | error
    config_snapshot TEXT
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    city TEXT NOT NULL,
    category TEXT NOT NULL,
    grid_cell_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | in_progress | done | error
    result_count INTEGER DEFAULT 0,
    error_detail TEXT,
    updated_at REAL,
    UNIQUE(run_id, category, grid_cell_id)
);

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    place_id TEXT,
    business_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    category_raw TEXT,
    niche TEXT,
    address TEXT,
    phone_raw TEXT,
    phone_normalized TEXT,
    phone_valid INTEGER DEFAULT 0,
    website TEXT,
    maps_url TEXT,
    lat REAL,
    lon REAL,
    rating REAL,
    review_count INTEGER,
    permanently_closed INTEGER DEFAULT 0,
    tier1_status TEXT,          -- reject_has_website | pass | reject_closed | reject_no_phone
    tier2_status TEXT,          -- not_run | pass | reject_found_site | pending_quota_exhausted
    tier2_checked_at REAL,
    score_tier TEXT,            -- hot | warm | cold
    score_value REAL,
    source_query TEXT,
    grid_cell_id TEXT,
    city TEXT,
    scraped_at REAL,
    is_duplicate INTEGER DEFAULT 0,
    dedup_group_id TEXT,
    dedup_review INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone_normalized);
CREATE INDEX IF NOT EXISTS idx_leads_name ON leads(normalized_name);
CREATE INDEX IF NOT EXISTS idx_leads_run ON leads(run_id);

CREATE TABLE IF NOT EXISTS requests_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    run_id TEXT,
    stage TEXT NOT NULL,              -- scrape | tier1 | tier2
    grid_cell_id TEXT,
    query TEXT,
    proxy_session_id TEXT,
    http_status INTEGER,
    retry_count INTEGER DEFAULT 0,
    outcome TEXT NOT NULL,            -- pass | reject | error | captcha | empty
    error_detail TEXT,
    duration_ms INTEGER,
    bytes_used INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_reqlog_run ON requests_log(run_id);

CREATE TABLE IF NOT EXISTS cost_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    run_id TEXT,
    batch_id TEXT,
    bytes_used INTEGER NOT NULL,
    estimated_cost_usd REAL NOT NULL,
    cumulative_bytes INTEGER NOT NULL,
    cumulative_cost_usd REAL NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS tier2_quota (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    period TEXT NOT NULL,          -- e.g. '2026-08' (calendar month)
    queries_used INTEGER NOT NULL DEFAULT 0,
    queries_limit INTEGER NOT NULL,
    UNIQUE(provider, period)
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


@contextlib.contextmanager
def get_conn(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def start_run(conn: sqlite3.Connection, run_id: str, city: str, categories: list[str], config_snapshot: str) -> None:
    conn.execute(
        "INSERT INTO runs (run_id, started_at, city, categories, status, config_snapshot) VALUES (?,?,?,?,?,?)",
        (run_id, time.time(), city, ",".join(categories), "running", config_snapshot),
    )
    conn.commit()


def finish_run(conn: sqlite3.Connection, run_id: str, status: str) -> None:
    conn.execute(
        "UPDATE runs SET finished_at=?, status=? WHERE run_id=?",
        (time.time(), status, run_id),
    )
    conn.commit()


def upsert_checkpoint(
    conn: sqlite3.Connection,
    run_id: str,
    city: str,
    category: str,
    grid_cell_id: str,
    status: str,
    result_count: int = 0,
    error_detail: Optional[str] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO checkpoints (run_id, city, category, grid_cell_id, status, result_count, error_detail, updated_at)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(run_id, category, grid_cell_id) DO UPDATE SET
            status=excluded.status,
            result_count=excluded.result_count,
            error_detail=excluded.error_detail,
            updated_at=excluded.updated_at
        """,
        (run_id, city, category, grid_cell_id, status, result_count, error_detail, time.time()),
    )
    conn.commit()


def pending_cells(conn: sqlite3.Connection, run_id: str, category: str, all_cell_ids: list[str]) -> list[str]:
    """Cells not yet marked 'done' for this run+category -- what resume picks up."""
    done = {
        row["grid_cell_id"]
        for row in conn.execute(
            "SELECT grid_cell_id FROM checkpoints WHERE run_id=? AND category=? AND status='done'",
            (run_id, category),
        )
    }
    return [c for c in all_cell_ids if c not in done]


def insert_lead(conn: sqlite3.Connection, lead: dict[str, Any]) -> int:
    cols = ", ".join(lead.keys())
    placeholders = ", ".join(["?"] * len(lead))
    cur = conn.execute(f"INSERT INTO leads ({cols}) VALUES ({placeholders})", tuple(lead.values()))
    conn.commit()
    return cur.lastrowid


def log_request(conn: sqlite3.Connection, **fields: Any) -> None:
    fields.setdefault("timestamp", time.time())
    cols = ", ".join(fields.keys())
    placeholders = ", ".join(["?"] * len(fields))
    conn.execute(f"INSERT INTO requests_log ({cols}) VALUES ({placeholders})", tuple(fields.values()))
    conn.commit()

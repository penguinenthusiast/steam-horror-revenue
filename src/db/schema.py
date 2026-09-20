"""SQLite schema and connection helpers."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS games (
    appid INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    developers TEXT,
    publishers TEXT,
    release_date TEXT,
    is_free INTEGER NOT NULL DEFAULT 0,
    tier TEXT NOT NULL DEFAULT 'mid',
    tags TEXT,
    genres TEXT,
    header_image TEXT,
    steam_url TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    appid INTEGER NOT NULL,
    snapshot_date TEXT NOT NULL,
    price_initial REAL,
    price_final REAL,
    discount INTEGER,
    positive INTEGER,
    negative INTEGER,
    owners_min INTEGER,
    owners_max INTEGER,
    owners_est REAL,
    owners_source TEXT,
    ccu INTEGER,
    est_revenue REAL,
    est_revenue_low REAL,
    est_revenue_high REAL,
    include_in_revenue INTEGER NOT NULL DEFAULT 1,
    model_version TEXT NOT NULL,
    PRIMARY KEY (appid, snapshot_date),
    FOREIGN KEY (appid) REFERENCES games(appid)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_date ON snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_games_tier ON games(tier);
CREATE INDEX IF NOT EXISTS idx_games_release ON games(release_date);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    games_upserted INTEGER DEFAULT 0,
    snapshots_upserted INTEGER DEFAULT 0,
    errors TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


@contextmanager
def db_session(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def latest_snapshot_date(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT MAX(snapshot_date) AS d FROM snapshots").fetchone()
    return row["d"] if row and row["d"] else None


def latest_successful_ingest(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM ingest_runs
        WHERE status = 'success'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

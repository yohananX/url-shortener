"""SQLite helpers: connection factory and schema initialization.

The database file lives next to this module and is created automatically
on first run, so there is no migration step to remember.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).with_name("links.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code         TEXT    NOT NULL UNIQUE,
    original_url TEXT    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    clicks       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_links_created_at ON links (id DESC);
"""


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Open a connection with ``Row`` objects and foreign keys enabled."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str | Path = DEFAULT_DB) -> None:
    """Create the schema if it does not exist yet (idempotent)."""
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()

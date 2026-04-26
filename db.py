"""SQLite helpers for tracking previously alerted listings."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

DB_PATH: str = "catbot.db"


def setup_db() -> None:
    """Create the listings table when it does not exist."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_listings (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                first_seen TIMESTAMP NOT NULL
            )
            """
        )
        conn.commit()


def is_new(listing_id: str) -> bool:
    """Return True when a listing has not been seen before."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT 1 FROM seen_listings WHERE id = ? LIMIT 1",
            (listing_id,),
        )
        return cursor.fetchone() is None


def mark_seen(listing_id: str, source: str) -> None:
    """Record a listing as seen using a UTC timestamp."""
    first_seen = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO seen_listings (id, source, first_seen)
            VALUES (?, ?, ?)
            """,
            (listing_id, source, first_seen),
        )
        conn.commit()

"""SQLite storage for scans and observations.

Two tables:
  - scans: one row per sweep (timestamp, host, location, optional latency).
  - observations: one row per access point seen in a sweep, with identifying
    fields anonymized.

The database runs in WAL mode so the read-only API can query it concurrently
with the capture loop without "database is locked" errors.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional

from capture.anonymize import hash_value
from capture.models import AccessPointObservation

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    scan_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT NOT NULL,
    host       TEXT NOT NULL,
    location   TEXT NOT NULL,
    latency_ms REAL
);

CREATE TABLE IF NOT EXISTS observations (
    obs_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id       INTEGER NOT NULL REFERENCES scans(scan_id),
    bssid_hash    TEXT,
    ssid_hash     TEXT,
    channel       INTEGER,
    band          TEXT,
    rssi          INTEGER,
    channel_width TEXT,
    security      TEXT
);

CREATE INDEX IF NOT EXISTS idx_observations_scan ON observations(scan_id);
CREATE INDEX IF NOT EXISTS idx_observations_channel ON observations(channel);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Open the database, enabling WAL mode for concurrent reads."""
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA foreign_keys=ON;")
    logger.debug("Opened database at %s (WAL mode)", db_path)
    return connection


def init_schema(connection: sqlite3.Connection) -> None:
    """Create tables and indexes if they do not exist."""
    connection.executescript(_SCHEMA)
    connection.commit()
    logger.info("Database schema ready")


def insert_scan(
    connection: sqlite3.Connection,
    host: str,
    location: str,
    latency_ms: Optional[float] = None,
) -> int:
    """Insert a scan row and return its scan_id."""
    timestamp = datetime.now(timezone.utc).isoformat()
    cursor = connection.execute(
        "INSERT INTO scans (timestamp, host, location, latency_ms) VALUES (?, ?, ?, ?)",
        (timestamp, host, location, latency_ms),
    )
    connection.commit()
    return int(cursor.lastrowid)


def insert_observations(
    connection: sqlite3.Connection,
    scan_id: int,
    observations: List[AccessPointObservation],
    salt: str,
) -> int:
    """Insert observations for a scan, anonymizing identifying fields."""
    rows = [
        (
            scan_id,
            hash_value(observation.bssid, salt),
            hash_value(observation.ssid, salt),
            observation.channel,
            observation.band,
            observation.rssi,
            observation.channel_width,
            observation.security,
        )
        for observation in observations
    ]
    connection.executemany(
        """
        INSERT INTO observations
            (scan_id, bssid_hash, ssid_hash, channel, band, rssi, channel_width, security)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    connection.commit()
    logger.debug("Inserted %d observations for scan %d", len(rows), scan_id)
    return len(rows)

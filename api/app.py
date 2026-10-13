"""Read-only Flask API + static frontend server.

Serves the `web/` directory and a handful of JSON endpoints that aggregate the
SQLite database written by the capture loop. Read-only: it never modifies data.

Usage:
    python api/app.py --db-path data/channel_tuner.sqlite --port 5000
"""

import argparse
import logging
import os
import sqlite3
from typing import Any, Dict, List

from flask import Flask, jsonify, request

try:  # when run as a script (api/ on sys.path)
    from scoring import compute_channel_score, interference_timeline, network_timeline
except ModuleNotFoundError:  # when imported as a package (repo root on sys.path)
    from api.scoring import (
        compute_channel_score,
        interference_timeline,
        network_timeline,
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("channel_tuner.api")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(PROJECT_ROOT, "web")
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "data", "channel_tuner.sqlite")

app = Flask(__name__, static_folder=WEB_DIR, static_url_path="")


def get_db_path() -> str:
    """Return the configured database path."""
    return app.config.get("DB_PATH", DEFAULT_DB_PATH)


def query(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Run a read-only query and return a list of dict rows."""
    connection = sqlite3.connect(get_db_path())
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def latest_scan_id(location: str) -> int:
    """Return the most recent scan_id for a location, or 0 if none."""
    rows = query(
        "SELECT scan_id FROM scans WHERE location = ? ORDER BY timestamp DESC LIMIT 1",
        (location,),
    )
    return rows[0]["scan_id"] if rows else 0


@app.route("/")
def index():
    """Serve the dashboard entry point."""
    return app.send_static_file("index.html")


@app.route("/api/locations")
def api_locations():
    """List distinct measurement locations."""
    rows = query("SELECT DISTINCT location FROM scans ORDER BY location")
    return jsonify([row["location"] for row in rows])


@app.route("/api/channel-occupancy")
def api_channel_occupancy():
    """Per-channel occupancy for the latest scan at a location.

    Returns, for each channel, the number of access points and their average
    signal. This is the data behind the main bar chart.
    """
    location = request.args.get("location", "default")
    scan_id = latest_scan_id(location)
    rows = query(
        """
        SELECT channel,
               band,
               COUNT(*)      AS ap_count,
               AVG(rssi)     AS avg_rssi
        FROM observations
        WHERE scan_id = ? AND channel IS NOT NULL
        GROUP BY channel, band
        ORDER BY channel
        """,
        (scan_id,),
    )
    return jsonify({"location": location, "scan_id": scan_id, "channels": rows})


@app.route("/api/channel-score")
def api_channel_score():
    """Congestion score and recommended 2.4 GHz channel for the latest scan."""
    location = request.args.get("location", "default")
    scan_id = latest_scan_id(location)
    rows = query(
        "SELECT channel, rssi FROM observations WHERE scan_id = ?", (scan_id,)
    )
    result = compute_channel_score(rows)
    result["location"] = location
    result["scan_id"] = scan_id
    return jsonify(result)


@app.route("/api/interference-timeline")
def api_interference_timeline():
    """Interference per candidate channel over time, for a location."""
    location = request.args.get("location", "default")
    rows = query(
        """
        SELECT s.scan_id AS scan_id, s.timestamp AS timestamp, o.channel AS channel,
               o.rssi AS rssi
        FROM scans s
        LEFT JOIN observations o ON o.scan_id = s.scan_id
        WHERE s.location = ?
        ORDER BY s.timestamp
        """,
        (location,),
    )
    result = interference_timeline(rows)
    result["location"] = location
    return jsonify(result)


@app.route("/api/network-timeline")
def api_network_timeline():
    """Signal per network over time, for the most frequently seen networks."""
    location = request.args.get("location", "default")
    rows = query(
        """
        SELECT s.scan_id AS scan_id, s.timestamp AS timestamp,
               o.bssid_hash AS bssid_hash, o.ssid AS ssid, o.rssi AS rssi
        FROM scans s
        LEFT JOIN observations o ON o.scan_id = s.scan_id
        WHERE s.location = ?
        ORDER BY s.timestamp
        """,
        (location,),
    )
    result = network_timeline(rows)
    result["location"] = location
    return jsonify(result)


@app.route("/api/timeline")
def api_timeline():
    """Access point count per scan over time, for a location (line chart)."""
    location = request.args.get("location", "default")
    rows = query(
        """
        SELECT s.timestamp            AS timestamp,
               COUNT(o.obs_id)        AS ap_count
        FROM scans s
        LEFT JOIN observations o ON o.scan_id = s.scan_id
        WHERE s.location = ?
        GROUP BY s.scan_id
        ORDER BY s.timestamp
        """,
        (location,),
    )
    return jsonify({"location": location, "points": rows})


@app.route("/api/summary")
def api_summary():
    """High-level counters for the dashboard header."""
    scans = query("SELECT COUNT(*) AS n FROM scans")[0]["n"]
    observations = query("SELECT COUNT(*) AS n FROM observations")[0]["n"]
    networks = query("SELECT COUNT(DISTINCT bssid_hash) AS n FROM observations")[0]["n"]
    return jsonify(
        {"scans": scans, "observations": observations, "unique_networks": networks}
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="channel-tuner read-only API.")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="SQLite path.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", type=int, default=5000, help="Bind port.")
    return parser.parse_args()


def main() -> None:
    """Configure and start the Flask development server."""
    args = parse_args()
    app.config["DB_PATH"] = args.db_path
    logger.info("Serving frontend from %s", WEB_DIR)
    logger.info("Reading database from %s", args.db_path)
    logger.info("Open http://%s:%d", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=True)


if __name__ == "__main__":
    main()

"""Zero-dependency server: stdlib http.server, no Flask.

Serves the web/ dashboard and the same read-only JSON endpoints as api/app.py,
using only the Python standard library. This is the macOS-friendly variant for
machines where pip packages (Flask) cannot be installed.

Usage:
    python3 api/server.py --db-path data/channel_tuner.sqlite --port 5000
"""

import argparse
import json
import logging
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

try:  # when run as a script (api/ on sys.path)
    from scoring import compute_channel_score
except ModuleNotFoundError:  # when imported as a package (repo root on sys.path)
    from api.scoring import compute_channel_score

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("channel_tuner.server")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(PROJECT_ROOT, "web")
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "data", "channel_tuner.sqlite")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}

# Set in main(); the request handler reads it.
DB_PATH = DEFAULT_DB_PATH


def query(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Run a read-only query and return a list of dict rows."""
    connection = sqlite3.connect(DB_PATH)
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


def summary() -> Dict[str, Any]:
    """High-level counters for the dashboard header."""
    scans = query("SELECT COUNT(*) AS n FROM scans")[0]["n"]
    observations = query("SELECT COUNT(*) AS n FROM observations")[0]["n"]
    networks = query("SELECT COUNT(DISTINCT bssid_hash) AS n FROM observations")[0]["n"]
    return {"scans": scans, "observations": observations, "unique_networks": networks}


def locations() -> List[str]:
    """List distinct measurement locations."""
    rows = query("SELECT DISTINCT location FROM scans ORDER BY location")
    return [row["location"] for row in rows]


def channel_occupancy(location: str) -> Dict[str, Any]:
    """Per-channel occupancy for the latest scan at a location."""
    scan_id = latest_scan_id(location)
    rows = query(
        """
        SELECT channel, band, COUNT(*) AS ap_count, AVG(rssi) AS avg_rssi
        FROM observations
        WHERE scan_id = ? AND channel IS NOT NULL
        GROUP BY channel, band
        ORDER BY channel
        """,
        (scan_id,),
    )
    return {"location": location, "scan_id": scan_id, "channels": rows}


def channel_score(location: str) -> Dict[str, Any]:
    """Congestion score and recommended 2.4 GHz channel for the latest scan."""
    scan_id = latest_scan_id(location)
    rows = query("SELECT channel, rssi FROM observations WHERE scan_id = ?", (scan_id,))
    result = compute_channel_score(rows)
    result["location"] = location
    result["scan_id"] = scan_id
    return result


def timeline(location: str) -> Dict[str, Any]:
    """Access point count per scan over time, for a location."""
    rows = query(
        """
        SELECT s.timestamp AS timestamp, COUNT(o.obs_id) AS ap_count
        FROM scans s
        LEFT JOIN observations o ON o.scan_id = s.scan_id
        WHERE s.location = ?
        GROUP BY s.scan_id
        ORDER BY s.timestamp
        """,
        (location,),
    )
    return {"location": location, "points": rows}


class Handler(BaseHTTPRequestHandler):
    """Routes /api/* to JSON endpoints and everything else to static files."""

    def log_message(self, format: str, *args: Any) -> None:  # quieter logging
        logger.info("%s - %s", self.address_string(), format % args)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, rel_path: str) -> None:
        if rel_path in ("", "/"):
            rel_path = "index.html"
        full_path = os.path.normpath(os.path.join(WEB_DIR, rel_path.lstrip("/")))
        if not full_path.startswith(WEB_DIR) or not os.path.isfile(full_path):
            self._send_json({"error": "not found"}, status=404)
            return
        extension = os.path.splitext(full_path)[1]
        content_type = CONTENT_TYPES.get(extension, "application/octet-stream")
        with open(full_path, "rb") as static_file:
            body = static_file.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        location = params.get("location", ["default"])[0]

        routes = {
            "/api/summary": summary,
            "/api/locations": locations,
            "/api/channel-occupancy": lambda: channel_occupancy(location),
            "/api/channel-score": lambda: channel_score(location),
            "/api/timeline": lambda: timeline(location),
        }
        if parsed.path in routes:
            try:
                self._send_json(routes[parsed.path]())
            except Exception:
                logger.exception("Error handling %s", parsed.path)
                self._send_json({"error": "internal error"}, status=500)
            return
        self._send_file(parsed.path)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="channel-tuner stdlib server.")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="SQLite path.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", type=int, default=5000, help="Bind port.")
    return parser.parse_args()


def main() -> None:
    """Configure globals and run the stdlib HTTP server."""
    global DB_PATH
    args = parse_args()
    DB_PATH = args.db_path
    logger.info("Serving frontend from %s", WEB_DIR)
    logger.info("Reading database from %s", DB_PATH)
    logger.info("Open http://%s:%d", args.host, args.port)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

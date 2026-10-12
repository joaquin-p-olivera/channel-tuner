"""Capture loop entry point.

Runs an endless loop: scan nearby access points, store them, sleep, repeat.

Usage:
    python -m capture.run_capture --location buceo-desk --interval 60
"""

import argparse
import logging
import os
import time

from capture import config
from capture.anonymize import load_or_create_salt
from capture.scanner import scan
from capture.storage import connect, init_schema, insert_observations, insert_scan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("channel_tuner.capture")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Capture nearby Wi-Fi access points.")
    parser.add_argument(
        "--location",
        default=config.DEFAULT_LOCATION,
        help="Label for the physical measurement point (keep the machine still).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=config.DEFAULT_INTERVAL_SECONDS,
        help="Seconds between scans.",
    )
    parser.add_argument(
        "--db-path",
        default=config.DB_PATH,
        help="Path to the SQLite database file.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan and exit (useful for testing).",
    )
    return parser.parse_args()


def run_single_scan(connection, host: str, location: str, salt: str) -> int:
    """Perform one scan and persist its results. Returns the observation count."""
    observations = scan()
    scan_id = insert_scan(connection, host=host, location=location)
    count = insert_observations(connection, scan_id, observations, salt)
    logger.info("Scan %d at '%s': stored %d access points", scan_id, location, count)
    return count


def main() -> None:
    """Set up storage and run the capture loop."""
    args = parse_args()
    os.makedirs(os.path.dirname(args.db_path) or ".", exist_ok=True)

    salt = load_or_create_salt(config.SALT_PATH)
    connection = connect(args.db_path)
    init_schema(connection)

    host = os.uname().nodename if hasattr(os, "uname") else "unknown-host"
    logger.info(
        "Starting capture: host='%s' location='%s' interval=%ds db='%s'",
        host,
        args.location,
        args.interval,
        args.db_path,
    )

    try:
        while True:
            try:
                run_single_scan(connection, host, args.location, salt)
            except Exception:  # keep the loop alive on transient scan errors
                logger.exception("Scan failed; will retry next interval")
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("Capture stopped by user")
    finally:
        connection.close()


if __name__ == "__main__":
    main()

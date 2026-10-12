"""Default configuration for the capture loop.

Values can be overridden on the command line (see run_capture.py).
"""

import os

# Directory where the SQLite database and salt live. Kept out of the repo.
DATA_DIR = os.environ.get("CHANNEL_TUNER_DATA_DIR", "data")

DB_PATH = os.path.join(DATA_DIR, "channel_tuner.sqlite")
SALT_PATH = os.path.join(DATA_DIR, ".salt")

# Seconds between scans. 60 is fine for early testing; raise to 120-180 for
# long unattended runs.
DEFAULT_INTERVAL_SECONDS = 60

# Physical measurement point. RSSI and congestion are only comparable within the
# same location, so label each campaign and keep the machine still while it runs.
DEFAULT_LOCATION = "default"

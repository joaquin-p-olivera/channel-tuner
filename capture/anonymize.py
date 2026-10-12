"""Anonymization helpers.

Identifying fields (BSSID, SSID) are never stored in clear text. They are hashed
with a per-installation salt so the stored values are stable across runs (which
lets us track a network over time) but cannot be trivially reversed into a real
MAC address or network name.
"""

import hashlib
import logging
import os
import secrets
from typing import Optional

logger = logging.getLogger(__name__)

HASH_LENGTH = 16  # number of hex chars kept from the digest


def load_or_create_salt(salt_path: str) -> str:
    """Return the installation salt, creating and persisting one if needed."""
    if os.path.exists(salt_path):
        with open(salt_path, "r", encoding="utf-8") as salt_file:
            salt = salt_file.read().strip()
        logger.debug("Loaded existing salt from %s", salt_path)
        return salt

    salt = secrets.token_hex(16)
    with open(salt_path, "w", encoding="utf-8") as salt_file:
        salt_file.write(salt)
    logger.info("Created new anonymization salt at %s", salt_path)
    return salt


def hash_value(value: Optional[str], salt: str) -> Optional[str]:
    """Hash a single identifying value with the salt. Returns None for None."""
    if value is None:
        return None
    digest = hashlib.sha256((salt + value).encode("utf-8")).hexdigest()
    return digest[:HASH_LENGTH]

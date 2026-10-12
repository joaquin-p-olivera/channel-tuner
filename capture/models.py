"""Shared data structures for the capture layer."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class AccessPointObservation:
    """A single access point as seen in one scan sweep.

    Values are raw (not yet anonymized). The storage layer is responsible for
    hashing the identifying fields (bssid, ssid) before writing them to disk.
    """

    bssid: Optional[str]
    ssid: Optional[str]
    channel: Optional[int]
    band: Optional[str]
    rssi: Optional[int]
    channel_width: Optional[str]
    security: Optional[str]

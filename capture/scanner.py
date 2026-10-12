"""Wi-Fi scanning backends.

The public entry point is `scan()`, which returns a list of
AccessPointObservation. The actual radio work is done by the operating system;
we only call the native tool/framework and parse its output:

- macOS: CoreWLAN (via pyobjc). Requires Location Services permission for the
  terminal/app, otherwise BSSIDs come back empty.
- Linux: `nmcli` (NetworkManager). SIGNAL is reported as a 0-100 quality value,
  not dBm; this is noted as a TODO to reconcile with the macOS dBm scale.

Only passively broadcast beacon data is read. Nothing is transmitted.
"""

import logging
import platform
import re
import subprocess
from typing import List, Optional

from capture.models import AccessPointObservation

logger = logging.getLogger(__name__)


def _band_from_frequency(freq_mhz: Optional[int]) -> Optional[str]:
    """Map a center frequency in MHz to a human-readable band label."""
    if freq_mhz is None:
        return None
    if 2400 <= freq_mhz < 2500:
        return "2.4GHz"
    if 4900 <= freq_mhz < 5900:
        return "5GHz"
    if 5925 <= freq_mhz <= 7125:
        return "6GHz"
    return None


def _split_nmcli_terse(line: str) -> List[str]:
    """Split an `nmcli -t` line on unescaped colons (nmcli escapes ':' as '\\:')."""
    fields = re.split(r"(?<!\\):", line)
    return [field.replace("\\:", ":") for field in fields]


def _scan_linux() -> List[AccessPointObservation]:
    """Scan using nmcli on Linux."""
    fields = "SSID,BSSID,CHAN,FREQ,SIGNAL,SECURITY"
    command = ["nmcli", "-t", "-f", fields, "device", "wifi", "list", "--rescan", "yes"]
    logger.debug("Running scan command: %s", " ".join(command))
    output = subprocess.check_output(command, text=True)

    observations: List[AccessPointObservation] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = _split_nmcli_terse(line)
        if len(parts) < 6:
            logger.warning("Skipping unparseable nmcli line: %r", line)
            continue
        ssid, bssid, chan, freq, signal, security = parts[:6]
        freq_mhz = _safe_int(freq.replace(" MHz", "").strip())
        observations.append(
            AccessPointObservation(
                bssid=bssid or None,
                ssid=ssid or None,
                channel=_safe_int(chan),
                band=_band_from_frequency(freq_mhz),
                # TODO: nmcli SIGNAL is a 0-100 quality value, not dBm. Reconcile
                # with the macOS dBm scale before computing cross-OS congestion.
                rssi=_safe_int(signal),
                channel_width=None,
                security=security or None,
            )
        )
    return observations


def _translate_channel_width(width_code: Optional[int]) -> Optional[str]:
    """Translate a CoreWLAN CWChannelWidth enum value to a label."""
    mapping = {0: None, 1: "20MHz", 2: "40MHz", 3: "80MHz", 4: "160MHz"}
    return mapping.get(width_code)


def _translate_band(band_code: Optional[int]) -> Optional[str]:
    """Translate a CoreWLAN CWChannelBand enum value to a label."""
    mapping = {1: "2.4GHz", 2: "5GHz", 3: "6GHz"}
    return mapping.get(band_code)


def _scan_macos() -> List[AccessPointObservation]:
    """Scan using the CoreWLAN framework on macOS."""
    from CoreWLAN import CWWiFiClient  # imported lazily; macOS only

    client = CWWiFiClient.sharedWiFiClient()
    interface = client.interface()
    networks, error = interface.scanForNetworksWithName_error_(None, None)
    if error is not None:
        raise RuntimeError(f"CoreWLAN scan failed: {error}")

    observations: List[AccessPointObservation] = []
    for network in networks:
        channel = network.wlanChannel()
        channel_number = channel.channelNumber() if channel is not None else None
        width = _translate_channel_width(channel.channelWidth()) if channel else None
        band = _translate_band(channel.channelBand()) if channel else None
        bssid = network.bssid()
        if not bssid:
            logger.warning(
                "Empty BSSID returned; Location Services permission is likely missing."
            )
        observations.append(
            AccessPointObservation(
                bssid=bssid or None,
                ssid=network.ssid() or None,
                channel=channel_number,
                band=band,
                rssi=network.rssiValue(),
                channel_width=width,
                security=None,  # TODO: derive from network security attributes
            )
        )
    return observations


def _safe_int(value: str) -> Optional[int]:
    """Parse an int, returning None on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def scan() -> List[AccessPointObservation]:
    """Scan nearby access points using the backend for the current OS."""
    system = platform.system()
    logger.debug("Detected operating system: %s", system)
    if system == "Darwin":
        return _scan_macos()
    if system == "Linux":
        return _scan_linux()
    raise NotImplementedError(f"No scan backend implemented for OS: {system}")

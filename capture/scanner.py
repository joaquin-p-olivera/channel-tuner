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

import json
import logging
import platform
import re
import subprocess
from typing import List, Optional, Tuple

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


def _parse_macos_channel(text: Optional[str]) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """Parse a system_profiler channel string like '6 (2GHz, 20MHz)'."""
    if not text:
        return (None, None, None)
    channel = None
    channel_match = re.match(r"\s*(\d+)", text)
    if channel_match:
        channel = int(channel_match.group(1))
    band = None
    band_match = re.search(r"(\d(?:\.\d)?GHz)", text)
    if band_match:
        raw = band_match.group(1)
        band = "2.4GHz" if raw in ("2GHz", "2.4GHz") else raw
    width = None
    width_match = re.search(r"(\d+MHz)", text)
    if width_match:
        width = width_match.group(1)
    return (channel, band, width)


def _parse_macos_signal(text: Optional[str]) -> Optional[int]:
    """Parse the dBm value from a string like '-55 dBm / -90 dBm'."""
    if not text:
        return None
    signal_match = re.search(r"(-?\d+)\s*dBm", text)
    return int(signal_match.group(1)) if signal_match else None


_MACOS_SECURITY_LABELS = {
    "none": "Open",
    "open": "Open",
    "wep": "WEP",
    "wpa_personal": "WPA",
    "wpa2_personal": "WPA2",
    "wpa2_personal_mixed": "WPA/WPA2",
    "wpa3_personal": "WPA3",
    "wpa3_transition": "WPA2/WPA3",
    "wpa2_wpa3_personal": "WPA2/WPA3",
    "wpa2_enterprise": "WPA2-Enterprise",
    "wpa3_enterprise": "WPA3-Enterprise",
}


def _clean_macos_security(raw: Optional[str]) -> Optional[str]:
    """Turn 'spairport_security_mode_wpa2_personal' into a friendly label."""
    if not raw:
        return None
    key = raw.replace("spairport_security_mode_", "").replace("pairport_security_mode_", "")
    return _MACOS_SECURITY_LABELS.get(key, key)


def _scan_macos_system_profiler() -> List[AccessPointObservation]:
    """Scan using the built-in `system_profiler` command (no pip dependency).

    This backend needs nothing installed, which is useful on managed machines
    where pyobjc cannot be installed. Note: system_profiler does not expose
    BSSIDs for neighbouring networks, so unique-network counts are unavailable
    here; channel, band and signal are. Location permission may still be
    required on recent macOS versions.
    """
    command = ["system_profiler", "SPAirPortDataType", "-json"]
    logger.debug("Running scan command: %s", " ".join(command))
    output = subprocess.check_output(command, text=True)
    data = json.loads(output)

    observations: List[AccessPointObservation] = []
    for section in data.get("SPAirPortDataType", []):
        for interface in section.get("spairport_airport_interfaces", []):
            networks = list(interface.get("spairport_airport_other_local_wireless_networks", []))
            current = interface.get("spairport_current_network_information")
            if isinstance(current, dict):
                networks.append(current)
            for network in networks:
                channel, band, width = _parse_macos_channel(
                    network.get("spairport_network_channel")
                )
                if channel is None:
                    # Skip entries without a usable channel (e.g. the connected
                    # network sometimes reports its details under other keys).
                    logger.debug(
                        "Skipping network without a channel: %s", network.get("_name")
                    )
                    continue
                # Recent macOS redacts the SSID in system_profiler output
                # (literal "<redacted>"); treat that as no name rather than
                # storing it, which would make every network hash alike.
                ssid = network.get("_name")
                if ssid in (None, "", "<redacted>"):
                    ssid = None
                observations.append(
                    AccessPointObservation(
                        bssid=None,  # system_profiler does not expose BSSIDs
                        ssid=ssid,
                        channel=channel,
                        band=band,
                        rssi=_parse_macos_signal(network.get("spairport_signal_noise")),
                        channel_width=width,
                        security=_clean_macos_security(network.get("spairport_security_mode")),
                    )
                )
    if not observations:
        logger.warning(
            "system_profiler returned no networks; Location permission may be required."
        )
    return observations


def _scan_macos() -> List[AccessPointObservation]:
    """Scan on macOS, preferring CoreWLAN and falling back to system_profiler."""
    try:
        import CoreWLAN  # noqa: F401  # imported lazily; macOS + pyobjc only
    except ImportError:
        logger.info(
            "CoreWLAN not available; using the no-dependency system_profiler backend."
        )
        return _scan_macos_system_profiler()
    return _scan_macos_corewlan()


def _scan_macos_corewlan() -> List[AccessPointObservation]:
    """Scan using the CoreWLAN framework on macOS (needs pyobjc)."""
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

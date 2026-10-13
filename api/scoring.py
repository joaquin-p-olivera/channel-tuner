"""Congestion scoring for the 2.4 GHz candidate channels (1, 6, 11).

The "which channel should my router use" question is a 2.4 GHz problem, because
there only channels 1, 6 and 11 do not overlap. For each candidate we estimate
the aggregate interference it would face, accounting for the fact that nearby
access points on overlapping channels also interfere, weighted by how strong
they arrive (RSSI).

Pure functions only, so both the Flask and the stdlib server can import this.
"""

import math
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional

CANDIDATE_CHANNELS_24GHZ = (1, 6, 11)

# In 2.4 GHz a 20 MHz channel spans ~4 channel numbers each side, so access
# points within this many channels of a candidate still interfere with it.
OVERLAP_SPAN = 5


def _overlap_factor(channel_distance: int) -> float:
    """Linear overlap weight: 1.0 at the same channel, 0.0 at OVERLAP_SPAN away."""
    if channel_distance >= OVERLAP_SPAN:
        return 0.0
    return 1.0 - channel_distance / OVERLAP_SPAN


def _linear_power(rssi_dbm: float) -> float:
    """Convert an RSSI in dBm to a relative linear power (10^(dBm/10))."""
    return 10 ** (rssi_dbm / 10)


def _usable_24ghz_aps(observations: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only 2.4 GHz access points that have a channel and a signal."""
    aps = []
    for observation in observations:
        channel = observation.get("channel")
        rssi = observation.get("rssi")
        if channel is not None and 1 <= channel <= 14 and rssi is not None:
            aps.append({"channel": channel, "rssi": rssi})
    return aps


def _score_candidate(candidate: int, aps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate the interference a single candidate channel would face."""
    total_power = 0.0
    ap_count = 0
    for ap in aps:
        factor = _overlap_factor(abs(ap["channel"] - candidate))
        if factor > 0:
            total_power += _linear_power(ap["rssi"]) * factor
            ap_count += 1
    interference_dbm: Optional[float] = (
        round(10 * math.log10(total_power), 1) if total_power > 0 else None
    )
    return {
        "channel": candidate,
        "interference_dbm": interference_dbm,
        "ap_count": ap_count,
    }


def _recommendation_sort_key(candidate: Dict[str, Any]):
    """A clear channel (no interference) wins; otherwise the lowest dBm wins."""
    if candidate["interference_dbm"] is None:
        return (0, 0.0)
    return (1, candidate["interference_dbm"])


def compute_channel_score(observations: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Score the 2.4 GHz candidate channels and recommend the least congested.

    observations: an iterable of dicts with 'channel' and 'rssi'.
    Returns {"candidates": [...], "recommended": <channel>} where each candidate
    has its aggregate interference in dBm (None when the channel is clear) and
    the number of contributing access points.
    """
    aps = _usable_24ghz_aps(observations)
    candidates = [_score_candidate(channel, aps) for channel in CANDIDATE_CHANNELS_24GHZ]
    recommended = min(candidates, key=_recommendation_sort_key)["channel"]
    return {"candidates": candidates, "recommended": recommended}


def _group_rows_by_scan(rows: Iterable[Dict[str, Any]]) -> "OrderedDict":
    """Group flat (scan_id, timestamp, ...) rows into per-scan buckets, in order."""
    scans: "OrderedDict" = OrderedDict()
    for row in rows:
        scan_id = row["scan_id"]
        if scan_id not in scans:
            scans[scan_id] = {"timestamp": row["timestamp"], "rows": []}
        scans[scan_id]["rows"].append(row)
    return scans


def interference_timeline(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Interference per candidate channel over time.

    rows: flat dicts with 'scan_id', 'timestamp', 'channel', 'rssi'.
    Returns aligned 'timestamps' and one series per candidate channel, each a
    list of interference values in dBm (None where that channel is clear).
    """
    scans = _group_rows_by_scan(rows)
    timestamps: List[str] = []
    values: Dict[int, List[Optional[float]]] = {ch: [] for ch in CANDIDATE_CHANNELS_24GHZ}
    for scan in scans.values():
        timestamps.append(scan["timestamp"])
        score = compute_channel_score(scan["rows"])
        by_channel = {c["channel"]: c["interference_dbm"] for c in score["candidates"]}
        for channel in CANDIDATE_CHANNELS_24GHZ:
            values[channel].append(by_channel.get(channel))
    series = [{"channel": ch, "values": values[ch]} for ch in CANDIDATE_CHANNELS_24GHZ]
    return {"timestamps": timestamps, "series": series}


def network_timeline(rows: Iterable[Dict[str, Any]], limit: int = 8) -> Dict[str, Any]:
    """Signal (RSSI) per network over time, for the most frequently seen networks.

    rows: flat dicts with 'scan_id', 'timestamp', 'bssid_hash', 'ssid', 'rssi'.
    Returns aligned 'timestamps' and one series per network (labelled by SSID),
    each a list of RSSI values in dBm (None when that network was not seen).
    """
    scans = _group_rows_by_scan(rows)
    scan_ids = list(scans.keys())
    timestamps = [scans[scan_id]["timestamp"] for scan_id in scan_ids]

    networks: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        bssid = row.get("bssid_hash")
        rssi = row.get("rssi")
        if bssid is None or rssi is None:
            continue
        network = networks.setdefault(
            bssid, {"label": row.get("ssid") or bssid, "rssi_by_scan": {}, "count": 0}
        )
        network["rssi_by_scan"][row["scan_id"]] = rssi
        network["count"] += 1
        if row.get("ssid"):
            network["label"] = row["ssid"]

    top = sorted(networks.values(), key=lambda n: n["count"], reverse=True)[:limit]
    series = [
        {"label": network["label"], "values": [network["rssi_by_scan"].get(sid) for sid in scan_ids]}
        for network in top
    ]
    return {"timestamps": timestamps, "series": series}

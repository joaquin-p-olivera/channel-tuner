# channel-tuner

Passive analytics of Wi-Fi **channel congestion** over time, with an eye toward
picking (and eventually auto-tuning) the best channel for a router you control.

It listens passively to the Wi-Fi beacons that access points already broadcast,
records what it sees into a local SQLite database, and serves a small dashboard
to explore how congestion evolves by channel and by hour.

## Scope and ethics

- **Passive only.** Nothing is transmitted. It reads publicly broadcast beacon
  data (channel, signal, band), the same information any device sees when
  looking for networks.
- **BSSID anonymized.** The BSSID (MAC address) is hashed with a local salt;
  raw MAC addresses are never written to disk. The SSID (network name) is kept
  in clear so the dashboard is readable: the real name on Linux/CoreWLAN, or a
  per-scan `A`/`B`/`C` label on macOS, where system_profiler redacts it. Those
  labels are per-scan only — without a stable identifier the same network cannot
  be tracked across scans on that backend.
- **Acts only on your own routers.** Any future "apply best channel" step is
  limited to routers you have legitimate admin access to. It never touches
  anyone else's equipment.

## Architecture

Three decoupled layers. The JSON returned by the API is the contract between the
Python side and the browser; the frontend never touches SQLite directly.

```
channel-tuner/
├── capture/        # Python: scan nearby APs -> SQLite (runs in a loop)
│   ├── scanner.py      # OS-specific backends (macOS CoreWLAN / Linux nmcli)
│   ├── storage.py      # SQLite schema (WAL) + inserts
│   ├── anonymize.py    # salted hashing of identifying fields
│   └── run_capture.py  # capture loop entry point
├── api/
│   └── app.py          # Flask: read-only /api/* endpoints + serves web/
├── web/                # HTML/CSS/JS dashboard (Chart.js), reads /api/*
├── run_capture.sh      # start the capture loop
└── run_api.sh          # start the API + dashboard
```

### Data model

- `scans` — one row per sweep: `timestamp`, `host`, `location`, optional
  `latency_ms`.
- `observations` — one row per access point per sweep: `bssid_hash`, `ssid`,
  `channel`, `band`, `rssi`, `channel_width`, `security`.

`location` labels the physical measurement point. RSSI and congestion are only
comparable within the same location, so keep the machine still during a campaign
and change the label when you move it.

## Requirements

- Python 3.9+
- `Flask` (see `requirements.txt`)
- **macOS:** two backends, chosen automatically:
  - `pyobjc-framework-CoreWLAN` if installed (richer: includes BSSIDs).
    - otherwise the built-in `system_profiler` command, which needs **nothing
    installed** — useful on managed machines. Recent macOS exposes no BSSID and
    redacts the SSID here, so this backend yields **channel-level data only**
    (channel, band, width, signal, security); per-network identity and
    unique-network counts require the CoreWLAN or Linux backend.
  - Either way, Location Services permission for the terminal may be required.
- **Linux:** `nmcli` (NetworkManager), already present on most desktops.

## Usage

```bash
# 1. Install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Start capturing (every 60s, labelled location). Ctrl-C to stop.
./run_capture.sh --location buceo-desk --interval 60

# Single test scan (no loop):
./run_capture.sh --location buceo-desk --once

# 3. In another terminal, serve the dashboard + API
./run_api.sh --port 5000
# open http://127.0.0.1:5000
```

## Status

Early skeleton. Known TODOs:

- Normalize RSSI across backends (Linux `nmcli` reports a 0-100 quality value,
  macOS CoreWLAN reports dBm).
- Weighted congestion score per channel and a channel recommendation.
- Hour x channel heatmap endpoint and view.
- Optional latency logging (`ping`) to correlate congestion with performance.
- Optional "apply best channel" step for your own router.

#!/usr/bin/env bash
# Run the Wi-Fi capture loop. Arguments are passed through to run_capture.py,
# e.g. ./scripts/run_capture.sh --location buceo-desk --interval 60
set -euo pipefail

cd "$(dirname "$0")/.."

# Activate a local virtualenv if present.
if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python3 -m capture.run_capture "$@"

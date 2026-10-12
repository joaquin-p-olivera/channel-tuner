#!/usr/bin/env bash
# Run the read-only Flask API that serves the dashboard and the data endpoints.
# Arguments are passed through to api/app.py, e.g. ./scripts/run_api.sh --port 5000
set -euo pipefail

cd "$(dirname "$0")/.."

# Activate a local virtualenv if present.
if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python3 api/app.py "$@"

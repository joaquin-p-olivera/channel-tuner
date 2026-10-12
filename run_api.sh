#!/usr/bin/env bash
# Run the zero-dependency stdlib server (no Flask) that serves the dashboard and
# data endpoints. macos branch. e.g. ./run_api.sh --port 5000
set -euo pipefail

cd "$(dirname "$0")"

# Activate a local virtualenv if present.
if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python3 api/server.py "$@"

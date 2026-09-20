#!/usr/bin/env bash
# Daily ingest runner for cron / launchd / CI.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

mkdir -p data
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

# Prefer fresh SteamSpy pull daily; Store responses still cache under data/cache/store
python scripts/run_ingest.py --no-cache

echo "Ingest finished at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

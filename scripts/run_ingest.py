#!/usr/bin/env python3
"""Run a daily Steam Horror Revenue Index ingest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ingest.pipeline import run_ingest


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Steam horror cohort and estimate revenue")
    parser.add_argument("--snapshot-date", default=None, help="YYYY-MM-DD (default: today)")
    parser.add_argument("--no-cache", action="store_true", help="Bypass local API response cache")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after N cohort games are upserted (smoke test)",
    )
    args = parser.parse_args()

    result = run_ingest(
        snapshot_date=args.snapshot_date,
        use_cache=not args.no_cache,
        limit=args.limit,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") in {"success", "empty"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

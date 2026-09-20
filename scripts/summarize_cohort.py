#!/usr/bin/env python3
"""Summarize the latest cohort snapshot for README / reporting."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from src.config import get_config
from src.dashboard.queries import load_ingest_meta, load_latest_frame


def fmt_money(value: float) -> str:
    if value >= 1_000_000_000:
        return f"${value/1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value/1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value/1_000:.1f}K"
    return f"${value:,.0f}"


def main() -> int:
    cfg = get_config()
    db = cfg.paths.database_path()
    if not db.exists():
        print(json.dumps({"error": "database missing", "path": str(db)}))
        return 1

    df = load_latest_frame(db)
    meta = load_ingest_meta(db)
    if df.empty:
        print(json.dumps({"error": "no snapshots", "meta": meta}))
        return 1

    paid = df[df["include_in_revenue"] == 1].copy()
    total_rev = float(paid["est_revenue"].sum()) if not paid.empty else 0.0
    median_rev = float(paid["est_revenue"].median()) if not paid.empty else 0.0
    tier_counts = df["tier"].value_counts().to_dict()

    top_share = None
    if not paid.empty and total_rev > 0:
        ranked = paid.sort_values("est_revenue", ascending=False)
        top_n = max(1, int(len(ranked) * 0.10))
        top_share = float(ranked.head(top_n)["est_revenue"].sum() / total_rev * 100)

    top = (
        paid.sort_values("est_revenue", ascending=False)
        .head(15)[["name", "release_date", "tier", "price_initial", "owners_est", "est_revenue"]]
        .to_dict(orient="records")
        if not paid.empty
        else []
    )

    by_year = (
        df.dropna(subset=["release_date"])
        .assign(year=lambda x: x["release_date"].str.slice(0, 4))
        .groupby("year")
        .size()
        .to_dict()
    )

    summary = {
        "snapshot_date": meta.get("latest_snapshot_date"),
        "last_ingest_finished_at": meta.get("last_success_finished_at"),
        "games_in_cohort": int(len(df)),
        "paid_games": int(len(paid)),
        "f2p_or_unpriced": int(len(df) - len(paid)),
        "est_total_revenue": total_rev,
        "est_total_revenue_fmt": fmt_money(total_rev),
        "est_median_revenue": median_rev,
        "est_median_revenue_fmt": fmt_money(median_rev),
        "top_10pct_revenue_share_pct": top_share,
        "tier_mix": {k: int(v) for k, v in tier_counts.items()},
        "releases_by_year": by_year,
        "pct_on_sale": float((df["discount"].fillna(0) > 0).mean() * 100),
        "top_15_by_est_revenue": [
            {
                **row,
                "est_revenue_fmt": fmt_money(float(row["est_revenue"] or 0)),
                "owners_est": int(row["owners_est"] or 0),
            }
            for row in top
        ],
        "model_version": str(df["model_version"].iloc[0]),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

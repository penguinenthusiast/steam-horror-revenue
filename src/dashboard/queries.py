"""Read helpers for the Streamlit dashboard."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from src.db.schema import connect, latest_snapshot_date, latest_successful_ingest


def load_latest_frame(db_path: Any) -> pd.DataFrame:
    conn = connect(db_path)
    try:
        snap_date = latest_snapshot_date(conn)
        if not snap_date:
            return pd.DataFrame()

        query = """
            SELECT
                g.appid,
                g.name,
                g.developers,
                g.publishers,
                g.release_date,
                g.is_free,
                g.tier,
                g.tags,
                g.genres,
                g.header_image,
                g.steam_url,
                s.snapshot_date,
                s.price_initial,
                s.price_final,
                s.discount,
                s.positive,
                s.negative,
                (s.positive + s.negative) AS total_reviews,
                CASE
                    WHEN (s.positive + s.negative) > 0
                    THEN 100.0 * s.positive / (s.positive + s.negative)
                    ELSE NULL
                END AS review_score,
                s.owners_min,
                s.owners_max,
                s.owners_est,
                s.owners_source,
                s.ccu,
                s.est_revenue,
                s.est_revenue_low,
                s.est_revenue_high,
                s.include_in_revenue,
                s.model_version
            FROM games g
            JOIN snapshots s ON g.appid = s.appid
            WHERE s.snapshot_date = ?
        """
        df = pd.read_sql_query(query, conn, params=(snap_date,))

        prev = conn.execute(
            """
            SELECT MAX(snapshot_date) AS d FROM snapshots
            WHERE snapshot_date < ?
            """,
            (snap_date,),
        ).fetchone()
        prev_date = prev["d"] if prev and prev["d"] else None
        if prev_date and not df.empty:
            prev_df = pd.read_sql_query(
                """
                SELECT appid, est_revenue AS est_revenue_prev
                FROM snapshots WHERE snapshot_date = ?
                """,
                conn,
                params=(prev_date,),
            )
            df = df.merge(prev_df, on="appid", how="left")
            df["est_revenue_7d_delta"] = df["est_revenue"] - df["est_revenue_prev"]
        else:
            df["est_revenue_prev"] = pd.NA
            df["est_revenue_7d_delta"] = pd.NA

        return df
    finally:
        conn.close()


def load_snapshot_history(db_path: Any, appid: int) -> pd.DataFrame:
    conn = connect(db_path)
    try:
        return pd.read_sql_query(
            """
            SELECT snapshot_date, price_initial, price_final, discount,
                   positive, negative, owners_est, ccu, est_revenue,
                   est_revenue_low, est_revenue_high
            FROM snapshots
            WHERE appid = ?
            ORDER BY snapshot_date
            """,
            conn,
            params=(appid,),
        )
    finally:
        conn.close()


def load_cohort_revenue_trend(db_path: Any) -> pd.DataFrame:
    conn = connect(db_path)
    try:
        return pd.read_sql_query(
            """
            SELECT
                snapshot_date,
                COUNT(*) AS games,
                SUM(CASE WHEN include_in_revenue = 1 THEN est_revenue ELSE 0 END) AS est_revenue_total,
                AVG(CASE WHEN include_in_revenue = 1 THEN est_revenue END) AS est_revenue_avg,
                SUM(CASE WHEN include_in_revenue = 1 THEN 1 ELSE 0 END) AS paid_games
            FROM snapshots
            GROUP BY snapshot_date
            ORDER BY snapshot_date
            """,
            conn,
        )
    finally:
        conn.close()


def load_ingest_meta(db_path: Any) -> Dict[str, Any]:
    conn = connect(db_path)
    try:
        snap = latest_snapshot_date(conn)
        run = latest_successful_ingest(conn)
        return {
            "latest_snapshot_date": snap,
            "last_success_finished_at": run["finished_at"] if run else None,
            "last_success_games": run["games_upserted"] if run else None,
            "last_run_status": run["status"] if run else None,
        }
    finally:
        conn.close()


def filter_frame(
    df: pd.DataFrame,
    tiers: Optional[List[str]] = None,
    paid_only: bool = False,
    min_reviews: int = 0,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    release_min: Optional[str] = None,
    release_max: Optional[str] = None,
    subtag: Optional[str] = None,
) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if tiers:
        out = out[out["tier"].isin(tiers)]
    if paid_only:
        out = out[out["include_in_revenue"] == 1]
    if min_reviews:
        out = out[out["total_reviews"].fillna(0) >= min_reviews]
    if price_min is not None:
        out = out[out["price_initial"].fillna(0) >= price_min]
    if price_max is not None:
        out = out[out["price_initial"].fillna(0) <= price_max]
    if release_min:
        out = out[out["release_date"].fillna("") >= release_min]
    if release_max:
        out = out[out["release_date"].fillna("") <= release_max]
    if subtag:
        out = out[out["tags"].fillna("").str.contains(subtag, case=False, regex=False)]
    return out

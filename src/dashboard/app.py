"""Streamlit dashboard for the Steam Horror Revenue Index."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_config
from src.dashboard.queries import (
    filter_frame,
    load_cohort_revenue_trend,
    load_ingest_meta,
    load_latest_frame,
    load_snapshot_history,
)
from src.db.schema import init_db

st.set_page_config(
    page_title="Steam Horror Revenue Index",
    page_icon="🎃",
    layout="wide",
)


def fmt_money(value: float | None) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    abs_v = abs(value)
    if abs_v >= 1_000_000_000:
        return f"${value/1_000_000_000:.2f}B"
    if abs_v >= 1_000_000:
        return f"${value/1_000_000:.2f}M"
    if abs_v >= 1_000:
        return f"${value/1_000:.1f}K"
    return f"${value:,.0f}"


def fmt_int(value: float | None) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{int(value):,}"


def main() -> None:
    config = get_config()
    db_path = config.paths.database_path()
    init_db(db_path)

    st.title("Steam Horror Revenue Index")
    st.caption(
        "Estimated Steam revenue for horror-tagged games released on or after "
        f"{config.cohort.release_date_min}. Figures are modeled — not Valve financials."
    )

    page = st.sidebar.radio(
        "Navigate",
        ["Overview", "Leaderboard", "Trends", "Game detail", "Methodology"],
    )

    meta = load_ingest_meta(db_path)
    df = load_latest_frame(db_path)

    st.sidebar.markdown("---")
    st.sidebar.write(f"**Snapshot:** {meta.get('latest_snapshot_date') or 'none'}")
    st.sidebar.write(f"**Last ingest:** {meta.get('last_success_finished_at') or 'never'}")
    if not df.empty:
        st.sidebar.write(f"**Model:** {df['model_version'].iloc[0]}")

    if df.empty:
        st.warning(
            "No data yet. Run an ingest first:\n\n"
            "`python scripts/run_ingest.py`"
        )
        if page == "Methodology":
            render_methodology(config)
        return

    # Shared filters
    st.sidebar.markdown("### Filters")
    tier_options = ["indie", "mid", "aaa"]
    tiers = st.sidebar.multiselect("Tier", tier_options, default=tier_options)
    paid_only = st.sidebar.checkbox("Paid games only (revenue cohort)", value=False)
    min_reviews = st.sidebar.number_input("Min reviews", min_value=0, value=0, step=10)
    price_min, price_max = st.sidebar.slider("List price (USD)", 0.0, 80.0, (0.0, 80.0))
    release_min = st.sidebar.text_input("Release from (YYYY-MM-DD)", config.cohort.release_date_min)
    release_max = st.sidebar.text_input("Release to (YYYY-MM-DD)", "")
    subtag = st.sidebar.selectbox(
        "Subtag",
        ["(any)"] + list(config.cohort.subtags),
    )
    subtag_val = None if subtag == "(any)" else subtag

    filtered = filter_frame(
        df,
        tiers=tiers or None,
        paid_only=paid_only,
        min_reviews=int(min_reviews),
        price_min=price_min,
        price_max=price_max,
        release_min=release_min or None,
        release_max=release_max or None,
        subtag=subtag_val,
    )

    if page == "Overview":
        render_overview(filtered, config)
    elif page == "Leaderboard":
        render_leaderboard(filtered)
    elif page == "Trends":
        render_trends(db_path, filtered)
    elif page == "Game detail":
        render_game_detail(db_path, filtered)
    else:
        render_methodology(config)


def render_overview(df: pd.DataFrame, config) -> None:
    paid = df[df["include_in_revenue"] == 1]
    total_rev = float(paid["est_revenue"].sum()) if not paid.empty else 0.0
    median_rev = float(paid["est_revenue"].median()) if not paid.empty else 0.0
    on_sale = float((df["discount"].fillna(0) > 0).mean() * 100) if not df.empty else 0.0

    # New releases in last 7 days relative to max release in frame is weak;
    # use snapshot_date as "today" proxy vs release_date.
    snap = df["snapshot_date"].iloc[0]
    cutoff = (pd.to_datetime(snap) - pd.Timedelta(days=7)).date().isoformat()
    recent = df[df["release_date"].fillna("") >= cutoff]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Games in view", f"{len(df):,}")
    c2.metric("Est. total revenue", fmt_money(total_rev))
    c3.metric("Est. median revenue", fmt_money(median_rev))
    c4.metric("% on sale", f"{on_sale:.1f}%")
    c5.metric("New releases (7d)", f"{len(recent):,}")

    st.info(
        f"Default KPI uses lifetime-style estimate: "
        f"`owners_est × list_price × {config.model.net_revenue_factor}` "
        f"(model {config.model.version}). Free-to-play titles are counted in games "
        "but excluded from revenue totals."
    )

    left, right = st.columns(2)
    with left:
        tier_counts = df["tier"].value_counts().rename_axis("tier").reset_index(name="games")
        fig = px.bar(tier_counts, x="tier", y="games", title="Games by tier")
        st.plotly_chart(fig, use_container_width=True)
    with right:
        if not paid.empty:
            top = paid.nlargest(15, "est_revenue")[["name", "est_revenue"]]
            fig = px.bar(
                top.sort_values("est_revenue"),
                x="est_revenue",
                y="name",
                orientation="h",
                title="Top 15 by estimated revenue",
                labels={"est_revenue": "Est. revenue (USD)", "name": ""},
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.write("No paid games in current filter.")


def render_leaderboard(df: pd.DataFrame) -> None:
    st.subheader("Leaderboard")
    view = df.copy()
    view["reviews"] = view["total_reviews"]
    view["score"] = view["review_score"].round(1)
    cols = [
        "name",
        "release_date",
        "tier",
        "price_initial",
        "discount",
        "reviews",
        "score",
        "owners_est",
        "est_revenue",
        "est_revenue_7d_delta",
        "ccu",
        "steam_url",
    ]
    show = view[cols].sort_values("est_revenue", ascending=False, na_position="last")
    st.dataframe(
        show,
        use_container_width=True,
        hide_index=True,
        column_config={
            "steam_url": st.column_config.LinkColumn("Steam"),
            "price_initial": st.column_config.NumberColumn("List price", format="$%.2f"),
            "est_revenue": st.column_config.NumberColumn("Est. revenue", format="$%.0f"),
            "est_revenue_7d_delta": st.column_config.NumberColumn("Δ vs prior snap", format="$%.0f"),
            "owners_est": st.column_config.NumberColumn("Est. owners", format="%.0f"),
            "discount": st.column_config.NumberColumn("Discount %"),
        },
    )


def render_trends(db_path, df: pd.DataFrame) -> None:
    st.subheader("Trends")
    trend = load_cohort_revenue_trend(db_path)
    if len(trend) >= 2:
        fig = px.line(
            trend,
            x="snapshot_date",
            y="est_revenue_total",
            title="Cohort estimated revenue over snapshots",
            markers=True,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.write(
            "Revenue-over-time needs at least two daily snapshots. "
            "Monthly release volume below still works from the latest snapshot."
        )

    releases = df.dropna(subset=["release_date"]).copy()
    if not releases.empty:
        releases["release_month"] = releases["release_date"].str.slice(0, 7)
        monthly = (
            releases.groupby("release_month")
            .size()
            .reset_index(name="releases")
            .sort_values("release_month")
        )
        fig = px.bar(monthly, x="release_month", y="releases", title="Horror releases by month")
        st.plotly_chart(fig, use_container_width=True)

    paid = df[df["include_in_revenue"] == 1].copy()
    if not paid.empty:
        paid_sorted = paid.sort_values("est_revenue", ascending=False)
        total = paid_sorted["est_revenue"].sum()
        top_n = max(1, int(len(paid_sorted) * 0.10))
        share = paid_sorted.head(top_n)["est_revenue"].sum() / total * 100 if total else 0
        st.metric("Top 10% revenue share", f"{share:.1f}%")
        st.caption("Share of estimated revenue held by the top decile of paid games in the current filter.")


def render_game_detail(db_path, df: pd.DataFrame) -> None:
    st.subheader("Game detail")
    names = df.sort_values("est_revenue", ascending=False, na_position="last")["name"].tolist()
    if not names:
        st.write("No games match filters.")
        return
    choice = st.selectbox("Game", names)
    row = df[df["name"] == choice].iloc[0]

    left, right = st.columns([1, 2])
    with left:
        if row.get("header_image"):
            st.image(row["header_image"], use_container_width=True)
        st.markdown(f"**[{row['name']}]({row['steam_url']})**")
        st.write(f"Tier: `{row['tier']}`")
        st.write(f"Release: {row['release_date']}")
        st.write(f"Publishers: {row['publishers']}")
        st.write(f"Tags: {row['tags']}")
    with right:
        st.metric("Est. revenue", fmt_money(row["est_revenue"]))
        st.write(
            f"Confidence band: {fmt_money(row['est_revenue_low'])} — {fmt_money(row['est_revenue_high'])}"
        )
        st.write(
            f"Owners est.: {fmt_int(row['owners_est'])} "
            f"({row['owners_source']}; range {fmt_int(row['owners_min'])}–{fmt_int(row['owners_max'])})"
        )
        st.write(
            f"List price: {fmt_money(row['price_initial'])} · "
            f"Current: {fmt_money(row['price_final'])} · Discount: {int(row['discount'] or 0)}%"
        )
        if pd.notna(row["review_score"]):
            st.write(
                f"Reviews: {fmt_int(row['total_reviews'])} · "
                f"Score: {row['review_score']:.1f}%"
            )
        else:
            st.write(f"Reviews: {fmt_int(row['total_reviews'])}")

        paid = df[df["include_in_revenue"] == 1]["est_revenue"]
        if row["include_in_revenue"] == 1 and not paid.empty:
            median = paid.median()
            st.write(f"Cohort median est. revenue (current filters): {fmt_money(median)}")
            if pd.notna(row["est_revenue"]) and median:
                st.write(f"Multiple of median: {row['est_revenue'] / median:.2f}×")

    history = load_snapshot_history(db_path, int(row["appid"]))
    if len(history) >= 2:
        fig = px.line(
            history,
            x="snapshot_date",
            y="est_revenue",
            title="Estimated revenue history",
            markers=True,
        )
        st.plotly_chart(fig, use_container_width=True)
        fig2 = px.line(
            history,
            x="snapshot_date",
            y="owners_est",
            title="Estimated owners history",
            markers=True,
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.caption("Snapshot history will appear after multiple daily ingest runs.")


def render_methodology(config) -> None:
    st.subheader("Methodology")
    st.markdown(
        f"""
### Cohort
- Discovery: SteamSpy tag **{config.cohort.steamspy_tag}**
- Include Steam `type=game`, released on/after **{config.cohort.release_date_min}**, not coming soon
- Horror signal: Steam Store genre contains Horror **or** Horror ranks in the top
  **{config.cohort.horror_tag_max_rank}** SteamSpy tags with ≥{int(config.cohort.horror_tag_min_vote_ratio*100)}%
  of the top tag's votes (drops weakly/meme-tagged titles)
- Indie / Mid / AAA are **filters**, not exclusions

### Owner estimate
1. Prefer SteamSpy owners range midpoint: `(min + max) / 2`
2. Fallback review proxy: `(positive + negative) × {config.model.review_multiplier}`

### Revenue estimate (lifetime-style)
`est_revenue = owners_est × list_price_usd × {config.model.net_revenue_factor}`

- List price comes from Steam Store `price_overview.initial` (US)
- Free-to-play / unpriced games are **excluded from revenue totals**
- Uncertainty band uses SteamSpy min/max owners, or ±{int(config.model.review_proxy_uncertainty*100)}% on review proxy
- Model version: **{config.model.version}**

### Tier rules
- **AAA:** major publisher match **or** reviews ≥ {config.model.aaa_min_reviews:,}
- **Indie:** not major publisher **and** reviews &lt; {config.model.indie_max_reviews:,}
- **Mid:** everyone else

### Limitations
- Not Valve financials; ignores regional pricing, CD keys, refunds, wishlists, DLC, bundles, and platform deals
- SteamSpy ownership is itself estimated and updates about daily
- Review multipliers are heuristic (Boxleiter-style) and tunable in `config.yaml`

### Disclaimer
This project is for research and education. Estimates can be wrong by large margins for individual titles.
"""
    )


if __name__ == "__main__":
    main()

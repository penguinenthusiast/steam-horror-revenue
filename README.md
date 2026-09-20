# Steam Horror Revenue Index

Estimated Steam revenue analytics for **horror-tagged games released on or after 2020-01-01**.

This is **not** Valve financial data. Every revenue figure is a transparent model estimate built from public SteamSpy ownership ranges (or review proxies) and Steam Store list prices.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Smoke test (fast)
python scripts/run_ingest.py --limit 40

# Full cohort (slow: polite Store/SteamSpy rate limits; can take hours)
python scripts/run_ingest.py

# Dashboard
./scripts/run_dashboard.sh
# or: streamlit run src/dashboard/app.py
```

Optional: copy `.env.example` to `.env` and set `STEAM_WEB_API_KEY` if you later add live CCU enrichment.

## What was done (steps taken)

1. **Defined the question** — Estimate Steam revenue for a horror *cohort* of games released on or after 2020-01-01.
2. **Defined the cohort** — SteamSpy Horror-tagged games, released ≥ 2020-01-01, with a real “horror signal” (Store Horror genre or a strong top community tag).
3. **Built an ingest pipeline** — Pull SteamSpy + Steam Store → filter → estimate owners/revenue → save daily snapshots in SQLite.
4. **Built a Streamlit dashboard** — Overview KPIs, filters (including indie/mid/aaa), leaderboard, trends, game detail, methodology.
5. **Ran a full cohort ingest** — Scanned 10,896 SteamSpy candidates; kept 2,586 games. See [Findings](#findings-from-the-full-cohort-ingest).
6. **Opened the dashboard** — `./scripts/run_dashboard.sh` slices the cohort and inspects titles.

## How the code works (basic tour)

```
SteamSpy (Horror tag) ──┐
                        ├──► ingest pipeline ──► SQLite ──► Streamlit dashboard
Steam Store (prices)  ──┘
```

| Path | Role |
|------|------|
| [`config.yaml`](config.yaml) | Cohort dates, model knobs (`×40` reviews, `0.70` Steam cut), publisher blocklist, rate limits |
| [`scripts/run_ingest.py`](scripts/run_ingest.py) | CLI entrypoint for one ingest run |
| [`src/ingest/steamspy.py`](src/ingest/steamspy.py) | Fetch Horror tag list + per-app tag details; parse owners ranges |
| [`src/ingest/steam_store.py`](src/ingest/steam_store.py) | Fetch Store `appdetails` (price, release date, genres, publishers) |
| [`src/ingest/pipeline.py`](src/ingest/pipeline.py) | Orchestrates fetch → filter → estimate → upsert into the DB |
| [`src/model/estimates.py`](src/model/estimates.py) | Owners estimate, revenue formula, indie/mid/aaa tier, horror-signal check |
| [`src/db/schema.py`](src/db/schema.py) | SQLite tables: `games`, `snapshots`, `ingest_runs` |
| [`src/dashboard/app.py`](src/dashboard/app.py) | Streamlit UI |
| [`src/dashboard/queries.py`](src/dashboard/queries.py) | SQL/pandas helpers the dashboard reads |

**Revenue formula (paid games only):**  
`est_revenue ≈ owners_est × list_price_usd × 0.70`

- Prefer SteamSpy owners midpoint; else `(reviews × 40)`.
- Free-to-play titles stay in the cohort for counts but are **excluded from revenue totals**.

## Project layout

```
config.yaml           # cohort rules, model knobs, publisher blocklist
scripts/run_ingest.py # CLI entrypoint
scripts/daily_ingest.sh
scripts/run_dashboard.sh
src/ingest/           # SteamSpy + Store clients + pipeline
src/model/            # owners / revenue / tier logic
src/db/               # SQLite schema
src/dashboard/        # Streamlit app
data/                 # sqlite DB + API cache + ingest log (gitignored caches)
```

## Methodology (summary)

| Step | Rule |
|------|------|
| Cohort | SteamSpy Horror tag ∩ (Store Horror genre **or** strong top-3 Horror tag) ∩ release ≥ 2020-01-01 |
| Owners | SteamSpy range midpoint, else `reviews × 40` |
| Revenue | `owners × list_price × 0.70` (paid games only) |
| Indie | Not on major-publisher list and reviews &lt; 50k |
| AAA | Major publisher or reviews ≥ 100k |

See the dashboard **Methodology** page and [`config.yaml`](config.yaml) for tunables. Model version is stored on every snapshot (`model.version`).

## Findings from the full cohort ingest

**Run completed:** 2026-09-13 (snapshot date `2026-09-12`, model `v1.0.0`).  
Scanned **10,896** SteamSpy Horror-tag candidates → kept **2,586** cohort games (21 soft errors, mostly missing Store pages).

| Metric | Value |
|--------|-------|
| Snapshot date | 2026-09-12 |
| Games in cohort | **2,586** |
| Paid games (in revenue totals) | **2,329** (257 F2P/unpriced excluded from $ totals) |
| Est. total revenue | **~$2.34B** |
| Est. median revenue (paid) | **~$52K** |
| Est. mean revenue (paid) | **~$1.0M** (mean ≫ median → heavy skew) |
| Top 10% revenue share | **~92.6%** |
| Tier mix | indie 2,556 · mid 5 · aaa 25 |
| % on sale (snapshot day) | ~6.6% |
| Releases by year | 2020: 252 · 2021: 304 · 2022: 350 · 2023: 444 · **2024: 849** · 2025: 367 · 2026: 20 |

Machine-readable copy: [`data/cohort_summary.json`](data/cohort_summary.json) (regenerate with `python scripts/summarize_cohort.py`).

### Observations

1. **Extremely top-heavy.** The top decile of paid titles accounts for ~93% of estimated cohort revenue. A typical horror release is closer to the **$52K median** than the **$1M mean**.
2. **Co-op / live-service-adjacent hits punch above price.** Phasmophobia, Lethal Company, R.E.P.O., and Content Warning clear huge estimated revenue at **≤ $20** list prices via ownership scale.
3. **Premium single-player still matters.** Resident Evil remakes/sequels and Silent Hill 2 sit near the top at **$40–$70** price points.
4. **2024 was a release boom** in this cohort (849 titles), far above prior years — more supply, not necessarily more winners.
5. **Most titles are labeled indie** under the project's tier rules (publisher blocklist + review thresholds). Indie games still hold ~**33%** of estimated revenue; the rest is concentrated in a thin AAA/mid head.
6. **Treat dollars as directional.** SteamSpy owner bands are coarse (e.g. multi-million ranges), so headline $M figures are model outputs, not audited sales.

### Top 15 by estimated revenue

| # | Est. revenue | Game | Tier | Release | List price |
|---|-------------|------|------|---------|------------|
| 1 | $210M | Resident Evil 4 | aaa | 2023-03-23 | $39.99 |
| 2 | $210M | Phasmophobia | aaa | 2020-09-18 | $19.99 |
| 3 | $105M | R.E.P.O. | aaa | 2025-02-26 | $9.99 |
| 4 | $105M | Lethal Company | aaa | 2023-10-23 | $9.99 |
| 5 | $98M | Resident Evil Village | aaa | 2021-05-06 | $39.99 |
| 6 | $98M | The Outlast Trials | mid | 2024-03-05 | $39.99 |
| 7 | $98M | Warhammer 40,000: Darktide | aaa | 2022-11-30 | $39.99 |
| 8 | $98M | Resident Evil 3 | aaa | 2020-04-02 | $39.99 |
| 9 | $98M | GTFO | mid | 2021-12-09 | $39.99 |
| 10 | $63M | Atomic Heart | aaa | 2023-02-20 | $59.99 |
| 11 | $63M | The Callisto Protocol | aaa | 2022-12-01 | $59.99 |
| 12 | $52M | Scorn | indie | 2022-10-14 | $49.99 |
| 13 | $42M | Five Nights at Freddy's: Security Breach | mid | 2021-12-16 | $39.99 |
| 14 | $42M | Content Warning | aaa | 2024-04-01 | $7.99 |
| 15 | $37M | SILENT HILL 2 | aaa | 2024-10-07 | $69.99 |

### How to explore further

```bash
./scripts/run_dashboard.sh
```

Use Streamlit filters (tier, price band, min reviews, subtags) to compare indie vs AAA slices and inspect individual game confidence bands.

### Ingest reliability note

An earlier full run reached ~2,282 kept games then crashed on an empty SteamSpy response; because commits only happened at the end, that attempt saved nothing. The pipeline now **commits every 25 games**, skips bad SteamSpy JSON, and the successful re-run used the warm API cache (~2.8 hours wall time).

## Scheduling (daily refresh)

SteamSpy refreshes about once per day. Run ingest after that (e.g. 06:00 UTC):

```bash
# crontab example
0 6 * * * cd /Users/penguinenthusiast/Documents/Coding_Projects/steam-horror-revenue && ./scripts/daily_ingest.sh >> data/ingest.log 2>&1
```

Or GitHub Actions: schedule a workflow that installs deps and runs `python scripts/run_ingest.py --no-cache`, then uploads `data/horror_index.sqlite3` as an artifact (or commits to a data branch).

## Limitations

- Ownership and revenue are **estimates** with wide error bars
- Ignores DLC, regional pricing, keys, refunds, bundles, Game Pass-like deals
- Free-to-play titles appear in counts/engagement but not revenue totals
- Full Store enrichment is rate-limited; first full run should use cache afterward
- SteamSpy’s Horror tag list is noisy; the horror-signal filter reduces (but does not eliminate) false positives

## License / affiliation

Unofficial fan analytics project. Not affiliated with Valve or SteamSpy.

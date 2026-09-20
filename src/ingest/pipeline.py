"""End-to-end daily ingest pipeline."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from src.config import AppConfig, get_config
from src.db.schema import connect, init_db
from src.ingest.http_util import HttpClient
from src.ingest.steam_store import fetch_appdetails, release_on_or_after
from src.ingest.steamspy import fetch_app_details, fetch_tag_games, parse_owners
from src.model.estimates import build_game_record, has_horror_signal


def _join_list(values: Optional[List[str]]) -> str:
    return "|".join(values or [])


def upsert_game(conn: Any, record: Dict[str, Any], updated_at: str) -> None:
    conn.execute(
        """
        INSERT INTO games (
            appid, name, developers, publishers, release_date, is_free, tier,
            tags, genres, header_image, steam_url, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(appid) DO UPDATE SET
            name=excluded.name,
            developers=excluded.developers,
            publishers=excluded.publishers,
            release_date=excluded.release_date,
            is_free=excluded.is_free,
            tier=excluded.tier,
            tags=excluded.tags,
            genres=excluded.genres,
            header_image=excluded.header_image,
            steam_url=excluded.steam_url,
            updated_at=excluded.updated_at
        """,
        (
            record["appid"],
            record["name"],
            _join_list(record["developers"]),
            _join_list(record["publishers"]),
            record["release_date"],
            1 if record["is_free"] else 0,
            record["tier"],
            _join_list(record["tags"]),
            _join_list(record["genres"]),
            record["header_image"],
            record["steam_url"],
            updated_at,
        ),
    )


def upsert_snapshot(
    conn: Any,
    record: Dict[str, Any],
    snapshot_date: str,
    model_version: str,
) -> None:
    conn.execute(
        """
        INSERT INTO snapshots (
            appid, snapshot_date, price_initial, price_final, discount,
            positive, negative, owners_min, owners_max, owners_est, owners_source,
            ccu, est_revenue, est_revenue_low, est_revenue_high,
            include_in_revenue, model_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(appid, snapshot_date) DO UPDATE SET
            price_initial=excluded.price_initial,
            price_final=excluded.price_final,
            discount=excluded.discount,
            positive=excluded.positive,
            negative=excluded.negative,
            owners_min=excluded.owners_min,
            owners_max=excluded.owners_max,
            owners_est=excluded.owners_est,
            owners_source=excluded.owners_source,
            ccu=excluded.ccu,
            est_revenue=excluded.est_revenue,
            est_revenue_low=excluded.est_revenue_low,
            est_revenue_high=excluded.est_revenue_high,
            include_in_revenue=excluded.include_in_revenue,
            model_version=excluded.model_version
        """,
        (
            record["appid"],
            snapshot_date,
            record["price_initial"],
            record["price_final"],
            record["discount"],
            record["positive"],
            record["negative"],
            record["owners_min"],
            record["owners_max"],
            record["owners_est"],
            record["owners_source"],
            record["ccu"],
            record["est_revenue"],
            record["est_revenue_low"],
            record["est_revenue_high"],
            1 if record["include_in_revenue"] else 0,
            model_version,
        ),
    )


def run_ingest(
    config: Optional[AppConfig] = None,
    snapshot_date: Optional[str] = None,
    use_cache: bool = True,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Pull Horror-tagged games, enrich from Steam Store, estimate revenue, snapshot to SQLite.

    Args:
        limit: optional cap on apps processed (useful for smoke tests).
    """
    config = config or get_config()
    snapshot_date = snapshot_date or date.today().isoformat()
    started_at = datetime.now(timezone.utc).isoformat()
    db_path = config.paths.database_path()
    cache_dir = config.paths.cache_path()
    init_db(db_path)

    errors: List[str] = []
    games_upserted = 0
    snapshots_upserted = 0
    run_id: Optional[int] = None

    conn = connect(db_path)
    try:
        run_id = conn.execute(
            """
            INSERT INTO ingest_runs (started_at, status)
            VALUES (?, 'running')
            """,
            (started_at,),
        ).lastrowid
        conn.commit()

        with HttpClient(config.rate_limits.steamspy_requests_per_second) as spy_client:
            spy_games = fetch_tag_games(
                spy_client,
                config.cohort.steamspy_tag,
                cache_dir=cache_dir,
                use_cache=use_cache,
            )

        # SteamSpy tag endpoint returns {appid: {...}}
        app_items = list(spy_games.items())
        spy_by_id: Dict[int, Dict[str, Any]] = {}
        ordered_appids: List[int] = []
        for key, payload in app_items:
            try:
                appid = int(payload.get("appid") or key)
            except (TypeError, ValueError):
                errors.append(f"skip invalid appid key={key!r}")
                continue
            spy_by_id[appid] = payload
            ordered_appids.append(appid)

        print(
            f"[ingest] candidates={len(ordered_appids)} "
            f"snapshot={snapshot_date} model={config.model.version}",
            flush=True,
        )

        # Enrich + filter incrementally so --limit means "N cohort games", not "N raw Spy rows"
        updated_at = datetime.now(timezone.utc).isoformat()
        batch_size = 40
        scanned = 0
        with HttpClient(config.rate_limits.steamspy_requests_per_second) as spy_detail_client:
            with HttpClient(config.rate_limits.steam_store_requests_per_second) as store_client:
                for start in range(0, len(ordered_appids), batch_size):
                    if limit is not None and games_upserted >= limit:
                        break
                    batch = ordered_appids[start : start + batch_size]
                    store_by_id = fetch_appdetails(
                        store_client,
                        batch,
                        cache_dir=cache_dir,
                        batch_pause_seconds=config.rate_limits.steam_store_batch_pause_seconds,
                        use_cache=use_cache,
                    )
                    for appid in batch:
                        if limit is not None and games_upserted >= limit:
                            break
                        scanned += 1
                        if scanned % 50 == 0 or scanned == 1:
                            print(
                                f"[ingest] scanned={scanned}/{len(ordered_appids)} "
                                f"cohort_kept={games_upserted} errors={len(errors)}",
                                flush=True,
                            )
                        spy = dict(spy_by_id.get(appid) or {})
                        store = store_by_id.get(appid)
                        if not store:
                            errors.append(f"no store details for {appid}")
                            continue
                        if store.get("coming_soon"):
                            continue
                        if not release_on_or_after(
                            store.get("release_date"), config.cohort.release_date_min
                        ):
                            continue

                        # Prefer cheap Store genre check; only hit SteamSpy appdetails if needed.
                        horror_ok = False
                        if config.cohort.require_horror_signal:
                            if has_horror_signal(
                                store.get("genres") or [],
                                spy.get("tags"),
                                tag_name=config.cohort.steamspy_tag,
                                max_rank=config.cohort.horror_tag_max_rank,
                                min_vote_ratio=config.cohort.horror_tag_min_vote_ratio,
                            ):
                                horror_ok = True
                            elif not spy.get("tags"):
                                try:
                                    details = fetch_app_details(
                                        spy_detail_client,
                                        appid,
                                        cache_dir=cache_dir,
                                        use_cache=use_cache,
                                    )
                                except Exception as exc:  # noqa: BLE001
                                    errors.append(f"steamspy appdetails failed for {appid}: {exc}")
                                    details = {}
                                if details.get("tags"):
                                    spy["tags"] = details["tags"]
                                if details.get("genre") and not spy.get("genre"):
                                    spy["genre"] = details["genre"]
                                for key in ("positive", "negative", "owners", "ccu", "name"):
                                    if details.get(key) is not None and spy.get(key) is None:
                                        spy[key] = details[key]
                                horror_ok = has_horror_signal(
                                    store.get("genres") or [],
                                    spy.get("tags"),
                                    tag_name=config.cohort.steamspy_tag,
                                    max_rank=config.cohort.horror_tag_max_rank,
                                    min_vote_ratio=config.cohort.horror_tag_min_vote_ratio,
                                )
                            if not horror_ok:
                                continue

                        owners_min, owners_max = parse_owners(spy.get("owners"))
                        try:
                            record = build_game_record(
                                appid, spy, store, owners_min, owners_max, config
                            )
                        except Exception as exc:  # noqa: BLE001 — collect and continue
                            errors.append(f"model failed for {appid}: {exc}")
                            continue

                        upsert_game(conn, record, updated_at)
                        upsert_snapshot(conn, record, snapshot_date, config.model.version)
                        games_upserted += 1
                        snapshots_upserted += 1

                        # Commit often so a late crash does not discard hours of work.
                        if games_upserted % 25 == 0:
                            conn.commit()

                    conn.commit()

        finished_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE ingest_runs
            SET finished_at = ?, status = ?, games_upserted = ?,
                snapshots_upserted = ?, errors = ?
            WHERE id = ?
            """,
            (
                finished_at,
                "success" if games_upserted else "empty",
                games_upserted,
                snapshots_upserted,
                json.dumps(errors[:200]),
                run_id,
            ),
        )
        conn.commit()

        return {
            "run_id": run_id,
            "snapshot_date": snapshot_date,
            "games_upserted": games_upserted,
            "snapshots_upserted": snapshots_upserted,
            "error_count": len(errors),
            "errors_sample": errors[:20],
            "status": "success" if games_upserted else "empty",
        }
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        if run_id is not None:
            try:
                conn.execute(
                    """
                    UPDATE ingest_runs
                    SET finished_at = ?, status = ?, games_upserted = ?,
                        snapshots_upserted = ?, errors = ?
                    WHERE id = ?
                    """,
                    (
                        datetime.now(timezone.utc).isoformat(),
                        "failed",
                        games_upserted,
                        snapshots_upserted,
                        json.dumps([str(exc)] + errors[:50]),
                        run_id,
                    ),
                )
                conn.commit()
            except Exception:
                pass
        raise
    finally:
        conn.close()

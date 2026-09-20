"""Steam Store API client."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dateutil import parser as date_parser

from src.ingest.http_util import HttpClient

STORE_URL = "https://store.steampowered.com/api/appdetails"


def parse_release_date(raw: Optional[Dict[str, Any]]) -> Optional[str]:
    if not raw or raw.get("coming_soon"):
        return None
    date_str = (raw.get("date") or "").strip()
    if not date_str:
        return None
    try:
        dt = date_parser.parse(date_str, fuzzy=True)
        return dt.date().isoformat()
    except (ValueError, OverflowError, TypeError):
        return None


def cents_to_usd(cents: Optional[int]) -> Optional[float]:
    if cents is None:
        return None
    return round(cents / 100.0, 2)


def normalize_store_app(appid: int, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not payload.get("success"):
        return None
    data = payload.get("data") or {}
    app_type = (data.get("type") or "").lower()
    if app_type and app_type != "game":
        return None

    release_date = parse_release_date(data.get("release_date"))
    price = data.get("price_overview") or {}
    is_free = bool(data.get("is_free"))
    if not price and data.get("is_free") is True:
        is_free = True
    elif price:
        is_free = bool(data.get("is_free")) or int(price.get("final") or 0) == 0
    else:
        # Missing price_overview: unknown; treat as free/unpriced for revenue exclusion
        is_free = True if data.get("is_free") else True

    developers = data.get("developers") or []
    publishers = data.get("publishers") or []
    genres = [g.get("description") for g in (data.get("genres") or []) if g.get("description")]
    categories = [
        c.get("description") for c in (data.get("categories") or []) if c.get("description")
    ]

    return {
        "appid": appid,
        "name": data.get("name") or f"App {appid}",
        "type": app_type or "game",
        "developers": developers,
        "publishers": publishers,
        "release_date": release_date,
        "coming_soon": bool((data.get("release_date") or {}).get("coming_soon")),
        "is_free": is_free,
        "price_initial": None if is_free and not price else cents_to_usd(price.get("initial")),
        "price_final": None if is_free and not price else cents_to_usd(price.get("final")),
        "discount": int(price.get("discount_percent") or 0) if price else 0,
        "genres": genres,
        "categories": categories,
        "header_image": data.get("header_image"),
        "steam_url": f"https://store.steampowered.com/app/{appid}/",
    }


def fetch_appdetails(
    client: HttpClient,
    appids: List[int],
    cache_dir: Optional[Path] = None,
    batch_pause_seconds: float = 0.5,
    use_cache: bool = True,
) -> Dict[int, Dict[str, Any]]:
    """Fetch and normalize Steam Store appdetails for many appids."""
    results: Dict[int, Dict[str, Any]] = {}
    cache_dir_path = None
    if cache_dir is not None:
        cache_dir_path = cache_dir / "store"
        cache_dir_path.mkdir(parents=True, exist_ok=True)

    pending: List[int] = []
    for appid in appids:
        if cache_dir_path is not None and use_cache:
            cache_file = cache_dir_path / f"{appid}.json"
            if cache_file.exists():
                with cache_file.open("r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                normalized = normalize_store_app(appid, raw.get(str(appid), raw))
                if normalized:
                    results[appid] = normalized
                continue
        pending.append(appid)

    # Steam Store accepts one appid reliably; batching can be flaky.
    for index, appid in enumerate(pending):
        try:
            raw = client.get_json(
                STORE_URL, params={"appids": appid, "cc": "us", "l": "english"}
            )
            entry = raw.get(str(appid), {"success": False})
        except Exception:
            # Skip individual failures so one 429/timeout doesn't abort the cohort.
            continue
        if cache_dir_path is not None:
            cache_file = cache_dir_path / f"{appid}.json"
            with cache_file.open("w", encoding="utf-8") as fh:
                json.dump({str(appid): entry}, fh)
        normalized = normalize_store_app(appid, entry)
        if normalized:
            results[appid] = normalized
        if batch_pause_seconds and index < len(pending) - 1:
            time.sleep(batch_pause_seconds)

    return results


def release_on_or_after(release_date: Optional[str], minimum: str) -> bool:
    if not release_date:
        return False
    try:
        return datetime.fromisoformat(release_date).date() >= datetime.fromisoformat(minimum).date()
    except ValueError:
        return False

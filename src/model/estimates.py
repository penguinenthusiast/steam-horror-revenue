"""Owners, revenue estimates, and tier classification."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.config import AppConfig, ModelConfig


def classify_tier(
    publishers: Sequence[str],
    total_reviews: int,
    major_publishers: Sequence[str],
    model: ModelConfig,
) -> str:
    """Return indie | mid | aaa."""
    pub_blob = " | ".join(p.lower() for p in publishers)
    is_major = any(needle.lower() in pub_blob for needle in major_publishers)

    if is_major or total_reviews >= model.aaa_min_reviews:
        return "aaa"
    if (not is_major) and total_reviews < model.indie_max_reviews:
        return "indie"
    return "mid"


def estimate_owners(
    owners_min: Optional[int],
    owners_max: Optional[int],
    total_reviews: int,
    model: ModelConfig,
) -> Tuple[float, float, float, str]:
    """
    Return (owners_est, owners_low, owners_high, source).
    Prefer SteamSpy midpoint; fallback to review proxy.
    """
    if owners_min is not None and owners_max is not None and (owners_min > 0 or owners_max > 0):
        low = float(owners_min)
        high = float(owners_max)
        mid = (low + high) / 2.0
        return mid, low, high, "steamspy_range"

    proxy = float(total_reviews) * model.review_multiplier
    uncertainty = model.review_proxy_uncertainty
    low = proxy * (1.0 - uncertainty)
    high = proxy * (1.0 + uncertainty)
    return proxy, low, high, "review_proxy"


def estimate_revenue(
    owners_est: float,
    owners_low: float,
    owners_high: float,
    list_price_usd: Optional[float],
    is_free: bool,
    model: ModelConfig,
) -> Tuple[Optional[float], Optional[float], Optional[float], bool]:
    """
    Lifetime-style estimate using list price.
    Returns (est, low, high, include_in_revenue).
    """
    if is_free or list_price_usd is None or list_price_usd <= 0:
        return None, None, None, False

    factor = model.net_revenue_factor
    est = owners_est * list_price_usd * factor
    low = owners_low * list_price_usd * factor
    high = owners_high * list_price_usd * factor
    return est, low, high, True


def tags_from_steamspy(raw_tags: Any) -> List[str]:
    if isinstance(raw_tags, dict):
        # SteamSpy returns {tag: vote_count}
        return sorted(raw_tags.keys(), key=lambda t: raw_tags[t], reverse=True)
    if isinstance(raw_tags, list):
        return [str(t) for t in raw_tags]
    if isinstance(raw_tags, str) and raw_tags.strip():
        return [t.strip() for t in raw_tags.split(",") if t.strip()]
    return []


def has_horror_signal(
    store_genres: Sequence[str],
    spy_tags: Any,
    tag_name: str = "Horror",
    max_rank: int = 3,
    min_vote_ratio: float = 0.35,
) -> bool:
    """
    True if this looks like a real horror title.

    Prefer Steam Store genres containing 'Horror'. When SteamSpy provides ranked
    community tags, accept Horror only if it ranks within `max_rank` and has at
    least `min_vote_ratio` of the top tag's votes (filters meme/weak tags).
    """
    target = tag_name.lower()
    for genre in store_genres or []:
        if target in str(genre).lower():
            return True

    if isinstance(spy_tags, dict) and spy_tags:
        ranked = sorted(spy_tags.items(), key=lambda kv: kv[1], reverse=True)
        if not ranked:
            return False
        top_votes = float(ranked[0][1] or 0) or 1.0
        for name, votes in ranked[: max(1, max_rank)]:
            if str(name).lower() == target:
                return (float(votes) / top_votes) >= min_vote_ratio
        return False

    tags = tags_from_steamspy(spy_tags)
    for name in tags[: max(1, max_rank)]:
        if str(name).lower() == target:
            return True
    return False


def build_game_record(
    appid: int,
    spy: Dict[str, Any],
    store: Dict[str, Any],
    owners_min: Optional[int],
    owners_max: Optional[int],
    config: AppConfig,
) -> Dict[str, Any]:
    positive = int(spy.get("positive") or 0)
    negative = int(spy.get("negative") or 0)
    total_reviews = positive + negative
    publishers = store.get("publishers") or []
    if not publishers and spy.get("publisher"):
        publishers = [spy["publisher"]]
    developers = store.get("developers") or []
    if not developers and spy.get("developer"):
        developers = [spy["developer"]]

    tier = classify_tier(publishers, total_reviews, config.major_publishers, config.model)
    tags = tags_from_steamspy(spy.get("tags"))

    genres = store.get("genres") or []
    if spy.get("genre"):
        for g in str(spy["genre"]).split(","):
            g = g.strip()
            if g and g not in genres:
                genres.append(g)

    owners_est, owners_low, owners_high, owners_source = estimate_owners(
        owners_min, owners_max, total_reviews, config.model
    )

    list_price = store.get("price_initial")
    if list_price is None:
        try:
            spy_price = int(spy.get("initialprice") or spy.get("price") or 0) / 100.0
            list_price = spy_price if spy_price > 0 else None
        except (TypeError, ValueError):
            list_price = None

    is_free = bool(store.get("is_free"))
    if not is_free and list_price is None and store.get("price_final") is None:
        # No priced store package and SteamSpy shows 0 → treat as free/unpriced
        try:
            is_free = int(spy.get("price") or 0) == 0
        except (TypeError, ValueError):
            is_free = True

    est_rev, est_low, est_high, include = estimate_revenue(
        owners_est, owners_low, owners_high, list_price, is_free, config.model
    )

    name = store.get("name") or spy.get("name") or f"App {appid}"
    release_date = store.get("release_date")

    return {
        "appid": appid,
        "name": name,
        "developers": developers,
        "publishers": publishers,
        "release_date": release_date,
        "is_free": is_free,
        "tier": tier,
        "tags": tags,
        "genres": genres,
        "header_image": store.get("header_image"),
        "steam_url": store.get("steam_url") or f"https://store.steampowered.com/app/{appid}/",
        "positive": positive,
        "negative": negative,
        "owners_min": owners_min,
        "owners_max": owners_max,
        "owners_est": owners_est,
        "owners_source": owners_source,
        "ccu": int(spy.get("ccu") or 0),
        "price_initial": list_price,
        "price_final": store.get("price_final") if not is_free else None,
        "discount": int(store.get("discount") or 0),
        "est_revenue": est_rev,
        "est_revenue_low": est_low,
        "est_revenue_high": est_high,
        "include_in_revenue": include,
    }

"""SteamSpy API client."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from src.ingest.http_util import HttpClient

STEAMSPY_URL = "https://steamspy.com/api.php"
OWNERS_RE = re.compile(
    r"([\d,]+)\s*\.\.\s*([\d,]+)|([\d,]+)\s*[-–]\s*([\d,]+)"
)


def parse_owners(owners: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """Parse SteamSpy owners strings like '20,000 .. 50,000'."""
    if not owners or not isinstance(owners, str):
        return None, None
    text = owners.strip()
    if text.lower() in {"", "0", "n/a", "na"}:
        return 0, 0
    match = OWNERS_RE.search(text)
    if not match:
        digits = re.sub(r"[^\d]", "", text)
        if digits:
            value = int(digits)
            return value, value
        return None, None
    if match.group(1) and match.group(2):
        low = int(match.group(1).replace(",", ""))
        high = int(match.group(2).replace(",", ""))
        return low, high
    low = int(match.group(3).replace(",", ""))
    high = int(match.group(4).replace(",", ""))
    return low, high


def fetch_tag_games(
    client: HttpClient,
    tag: str,
    cache_dir: Optional[Path] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """Return mapping of appid -> SteamSpy app payload for a tag."""
    cache_file = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\-]+", "_", tag.lower())
        cache_file = cache_dir / f"steamspy_tag_{safe}.json"
        if use_cache and cache_file.exists():
            with cache_file.open("r", encoding="utf-8") as fh:
                return json.load(fh)

    data = client.get_json(STEAMSPY_URL, params={"request": "tag", "tag": tag})
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected SteamSpy response for tag={tag!r}: {type(data)}")

    if cache_file is not None:
        with cache_file.open("w", encoding="utf-8") as fh:
            json.dump(data, fh)

    return data


def fetch_app_details(
    client: HttpClient,
    appid: int,
    cache_dir: Optional[Path] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """Fetch SteamSpy appdetails (includes ranked tags)."""
    cache_file = None
    if cache_dir is not None:
        details_dir = cache_dir / "steamspy_app"
        details_dir.mkdir(parents=True, exist_ok=True)
        cache_file = details_dir / f"{appid}.json"
        if use_cache and cache_file.exists():
            with cache_file.open("r", encoding="utf-8") as fh:
                return json.load(fh)

    try:
        data = client.get_json(STEAMSPY_URL, params={"request": "appdetails", "appid": appid})
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    if cache_file is not None and data:
        with cache_file.open("w", encoding="utf-8") as fh:
            json.dump(data, fh)
    return data

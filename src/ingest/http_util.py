"""Rate-limited HTTP helpers."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class RateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        self._min_interval = 1.0 / max(requests_per_second, 0.01)
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last = time.monotonic()


class HttpClient:
    def __init__(self, requests_per_second: float, timeout: float = 30.0) -> None:
        self.limiter = RateLimiter(requests_per_second)
        self.client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "SteamHorrorRevenueIndex/0.1 (analytics project)"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        stop=stop_after_attempt(6),
        reraise=True,
    )
    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        self.limiter.wait()
        response = self.client.get(url, params=params)
        if response.status_code == 429:
            # Honor Retry-After when present; otherwise wait before tenacity backoff.
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                time.sleep(min(int(retry_after), 90))
            else:
                time.sleep(10)
            response.raise_for_status()
        response.raise_for_status()
        if not response.content or not response.content.strip():
            raise httpx.TransportError(f"Empty response body from {url}")
        try:
            return response.json()
        except ValueError as exc:
            raise httpx.TransportError(f"Invalid JSON from {url}: {exc}") from exc

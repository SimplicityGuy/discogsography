"""SSRF-safe HTTP client for scraping discogs.com.

Allow-list: only *.discogs.com hosts are permitted. Redirects must stay
within the allow-list or are rejected with BlockedTargetError.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

ALLOWED_HOSTS: frozenset[str] = frozenset({"www.discogs.com", "discogs.com"})


class BlockedTargetError(RuntimeError):
    """Raised when a request target is not in the allow-list."""


def _check_host(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise BlockedTargetError(f"host {host!r} not in allow-list")


class DiggerHttpClient:
    """Async HTTP client restricted to the Discogs domain allow-list.

    Redirects are followed manually so each hop can be validated against
    the allow-list before the request is made.

    Args:
        user_agent: Value for the User-Agent header.
        timeout_seconds: Total request timeout in seconds (connect timeout is 5 s).
    """

    def __init__(self, user_agent: str, timeout_seconds: float = 15.0) -> None:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent, "Accept-Language": "en"},
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
            follow_redirects=False,
        )

    async def __aenter__(self) -> DiggerHttpClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def get(self, url: str) -> httpx.Response:
        """Fetch ``url``, validating the host against the allow-list.

        Manually follows 3xx redirects and re-validates each ``Location``
        header before issuing the next request.

        Raises:
            BlockedTargetError: If the URL or any redirect target is not in the allow-list.
        """
        _check_host(url)
        r = await self._client.get(url)
        while r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("location")
            if not loc:
                break
            _check_host(loc)
            r = await self._client.get(loc)
        return r

"""Tests for the SSRF-safe HTTP client."""

import httpx
import pytest
import respx

from digger.scraper.http_client import BlockedTargetError, DiggerHttpClient


@pytest.mark.asyncio
async def test_blocks_non_discogs_hosts():
    client = DiggerHttpClient(user_agent="test/1.0")
    with pytest.raises(BlockedTargetError):
        await client.get("https://example.com/foo")


@pytest.mark.asyncio
@respx.mock
async def test_allows_discogs_hosts():
    respx.get("https://www.discogs.com/sell/release/42").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
    client = DiggerHttpClient(user_agent="test/1.0")
    r = await client.get("https://www.discogs.com/sell/release/42")
    assert r.status_code == 200
    assert "ok" in r.text

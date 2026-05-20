"""Tests for the SSRF-safe HTTP client."""

import httpx
import pytest
import respx

from digger.scraper.http_client import BlockedTargetError, DiggerHttpClient


@pytest.mark.asyncio
async def test_blocks_non_discogs_hosts():
    async with DiggerHttpClient(user_agent="test/1.0") as client:
        with pytest.raises(BlockedTargetError):
            await client.get("https://example.com/foo")


@pytest.mark.asyncio
@respx.mock
async def test_allows_discogs_hosts():
    respx.get("https://www.discogs.com/sell/release/42").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
    async with DiggerHttpClient(user_agent="test/1.0") as client:
        r = await client.get("https://www.discogs.com/sell/release/42")
    assert r.status_code == 200
    assert "ok" in r.text


@pytest.mark.asyncio
@respx.mock
async def test_blocks_absolute_cross_host_redirect():
    respx.get("https://www.discogs.com/sell/release/42").mock(
        return_value=httpx.Response(302, headers={"location": "https://evil.example.com/steal"})
    )
    async with DiggerHttpClient(user_agent="test/1.0") as client:
        with pytest.raises(BlockedTargetError):
            await client.get("https://www.discogs.com/sell/release/42")


@pytest.mark.asyncio
@respx.mock
async def test_follows_same_host_relative_redirect():
    respx.get("https://www.discogs.com/sell/release/42").mock(return_value=httpx.Response(302, headers={"location": "/sell/release/43"}))
    respx.get("https://www.discogs.com/sell/release/43").mock(return_value=httpx.Response(200, text="<html>moved</html>"))
    async with DiggerHttpClient(user_agent="test/1.0") as client:
        r = await client.get("https://www.discogs.com/sell/release/42")
    assert r.status_code == 200
    assert "moved" in r.text

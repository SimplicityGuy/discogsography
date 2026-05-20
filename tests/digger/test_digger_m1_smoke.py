"""M1 happy-path smoke test for the digger feature.

This single file wires the REAL digger components together at their seams, with
mocks only at the I/O boundaries (HTTP via respx, Postgres via a mock pool/cursor).
Its value over the existing isolated unit tests is that it exercises the genuine
contracts between components, so a break between any of these pairs is caught here:

    Part 1 (scrape -> persist):
        DiggerHttpClient (respx) -> ScrapeExecutor -> parse_listings -> _persist SQL
    Part 2 (persist -> API surface):
        require_user -> get_wantlist router -> get_wantlist_with_listings_counts ->
        DiggerWantlistResponse response model

No part of the real parser, executor, router, or query is reimplemented or
over-mocked: the actual functions run end to end against the mock boundaries.

SCOPE NOTE: A true cross-process E2E (real Postgres, a running stack, a browser)
is INTENTIONALLY out of scope. This repository has no real-DB test infrastructure
-- every test, including ones named "*integration*", is mock-based, and the only
live marker is ``e2e`` (which assumes a running stack). This smoke is therefore
mock-based and in-process so it runs in normal CI (``just test-digger``) without a
database, a stack, a browser, or a new marker. It is NOT marked ``e2e`` and runs
under the default ``-m 'not e2e'`` selection.
"""

from __future__ import annotations

import base64
from decimal import Decimal
import hashlib
import hmac
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
import respx

from api.routers import digger as digger_router
from digger.scraper.executor import ScrapeExecutor, _placeholder_seller_id
from digger.scraper.http_client import DiggerHttpClient


if TYPE_CHECKING:
    from collections.abc import Iterator


FIXTURES = Path(__file__).parent / "fixtures"

# Mirrors tests/api/conftest.py so the JWT is minted exactly the same way.
TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests"
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_USER_EMAIL = "test@example.com"


# ---------------------------------------------------------------------------
# Part 1 helpers: a mock pool/conn/cursor chain that records the SQL it receives
# ---------------------------------------------------------------------------


def _make_executor_pool(fetchone_return: object = None) -> tuple[MagicMock, AsyncMock]:
    """Build a mock pool -> conn -> cursor chain for ScrapeExecutor._persist.

    Mirrors the shape used in tests/digger/test_executor.py. Returns (pool, cursor)
    so the caller can assert on the SQL the executor issued.
    """
    cursor = AsyncMock()
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=False)
    cursor.execute = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=fetchone_return)
    cursor.rowcount = 0

    conn = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.set_autocommit = AsyncMock()
    conn.cursor = MagicMock(return_value=cursor)
    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)

    pool = MagicMock()
    pool.connection = MagicMock(return_value=conn)
    return pool, cursor


# ---------------------------------------------------------------------------
# Part 1: scrape -> persist  (real http client + real parser + real executor)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_m1_smoke_scrape_release_persists_parsed_listings() -> None:
    """Fetch a release page, parse the real HTML, persist via the real executor.

    Asserts the full scrape-one-release contract:
      (i)   the correct Discogs /sell/release/<id> URL was requested,
      (ii)  the canned HTML was parsed into >= 1 marketplace listing,
      (iii) the executor upserted that listing into digger.listings with the
            price/condition that came out of the parsed HTML,
      (iv)  the executor set next_scrape_due_at so the queue runner will not
            immediately re-pop and re-scrape the release.
    """
    release_id = 12345
    html = (FIXTURES / "listing_page_basic.html").read_text()

    listing_url = f"https://www.discogs.com/sell/release/{release_id}"
    route = respx.get(listing_url).mock(return_value=httpx.Response(200, text=html))

    # New seller -> the executor synthesises a placeholder seller_id.
    pool, cursor = _make_executor_pool(fetchone_return=None)

    async with DiggerHttpClient(user_agent="digger-smoke/1.0") as http:
        executor = ScrapeExecutor(http_client=http, pool=pool)
        result = await executor.scrape_release(release_id)

    assert result is True

    # (i) the correct listing URL was fetched
    assert route.called
    requested_url = str(route.calls.last.request.url)
    assert requested_url == listing_url

    # (ii) the real parser produced listings from the canned HTML. The first
    # fixture row is listing_id=20001, seller "vinylking", NM/NM, USD 12.99 -- so
    # a SELECT on that exact username confirms the parsed record reached _persist.
    select_calls = [c for c in cursor.execute.call_args_list if "SELECT seller_id" in c[0][0]]
    selected_usernames = {c[0][1][0] for c in select_calls}
    assert "vinylking" in selected_usernames

    # (iii) the parsed listing was upserted into digger.listings with values
    # derived from the HTML (listing_id 20001, USD 12.99, NM media condition,
    # and the placeholder seller_id for the new "vinylking" seller).
    listing_inserts = [c for c in cursor.execute.call_args_list if "INSERT INTO digger.listings" in c[0][0]]
    assert listing_inserts, "expected an upsert into digger.listings"
    insert_sql = listing_inserts[0][0][0]
    assert "ON CONFLICT (listing_id) DO UPDATE" in insert_sql

    row_20001 = next(c for c in listing_inserts if c[0][1][0] == 20001)
    params = row_20001[0][1]
    # Positional params: listing_id, release_id, seller_id, price_value,
    # price_currency, media_condition, sleeve_condition, comments, posted_at.
    # Sanity-guard params[0] so a future column reorder fails loudly here.
    assert params[0] == 20001, f"listing_id should be the first param; got {params!r}"
    assert params[1] == release_id
    assert params[2] == _placeholder_seller_id("vinylking")
    assert params[3] == Decimal("12.99")
    assert params[4] == "USD"
    assert params[5] == "NM"

    # (iv) the executor set next_scrape_due_at (and recorded a successful scrape)
    # so the queue runner will not immediately re-pop this release.
    state_calls = [c for c in cursor.execute.call_args_list if "release_scrape_state" in c[0][0]]
    assert state_calls, "expected a release_scrape_state update"
    state_sql = state_calls[0][0][0]
    assert "next_scrape_due_at" in state_sql
    assert "last_scraped_at" in state_sql
    assert "consecutive_failures = 0" in state_sql


# ---------------------------------------------------------------------------
# Part 2 helpers: mint a JWT + a mock pool whose cursor drives the REAL query
# ---------------------------------------------------------------------------


def _make_test_jwt(
    user_id: str = TEST_USER_ID,
    email: str = TEST_USER_EMAIL,
    exp: int = 9_999_999_999,
    secret: str = TEST_JWT_SECRET,
) -> str:
    """Mint a valid HS256 JWT exactly as tests/api/conftest.make_test_jwt does."""

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(json.dumps({"sub": user_id, "email": email, "exp": exp}, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    sig = b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def _make_query_pool(rows: list[dict[str, Any]]) -> MagicMock:
    """Build a mock pool whose cursor returns *rows* from fetchall().

    Shaped so the REAL get_wantlist_with_listings_counts runs unchanged: it opens
    pool.connection(), calls conn.cursor(row_factory=dict_row), executes, and
    fetchall()s dict rows. We mock only at that boundary.
    """
    cursor = AsyncMock()
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=False)
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=rows)
    cursor.fetchone = AsyncMock(return_value=None)

    conn = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    # cursor() must accept the row_factory=dict_row kwarg the real query passes.
    conn.cursor = MagicMock(return_value=cursor)

    pool = MagicMock()
    pool.connection = MagicMock(return_value=conn)
    return pool


@pytest.fixture
def digger_api_client() -> Iterator[TestClient]:
    """A minimal FastAPI app mounting the REAL digger router + REAL auth dependency.

    Self-contained: tests/api/conftest fixtures are not visible here (conftest is
    directory-scoped). We configure api.dependencies with a known JWT secret so the
    real require_user runs, mount the real router, and restore module state on exit.
    """
    import api.dependencies as deps

    original_jwt = deps._jwt_secret
    original_redis = deps._redis
    original_pool_deps = deps._pool
    original_token = deps._digger_api_service_token
    original_router_pool = digger_router._pool

    # Real require_user only needs the JWT secret; Redis is optional (revocation
    # checks are skipped when _redis is None).
    deps.configure(TEST_JWT_SECRET, redis=None, pool=None, digger_api_service_token=None)

    app = FastAPI()
    app.include_router(digger_router.router)

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        deps.configure(original_jwt, redis=original_redis, pool=original_pool_deps, digger_api_service_token=original_token)
        digger_router._pool = original_router_pool


# ---------------------------------------------------------------------------
# Part 2: persist -> API surface  (real router + real query shaping)
# ---------------------------------------------------------------------------


def test_m1_smoke_scraped_listing_surfaces_through_wantlist_api(digger_api_client: TestClient) -> None:
    """A "scraped" wantlist row (active_listings >= 1) surfaces through the API.

    Stands up the REAL digger router with a mock pool whose query path returns one
    wantlist row shaped exactly as get_wantlist_with_listings_counts emits (the
    SELECT's column aliases). Authenticates with a real JWT (exercising the real
    require_user), GETs /api/digger/wantlist, and asserts the response item shows
    active_listings > 0 with the expected tier and release_id -- proving a scraped
    listing flows through the real query shaping and DiggerWantlistResponse model.
    """
    release_id = 12345
    # Row shape mirrors get_wantlist_with_listings_counts: the SELECT aliases the
    # active count to "active_listings"; a value >= 1 means this release has been
    # scraped and has live marketplace listings.
    scraped_row: dict[str, Any] = {
        "release_id": release_id,
        "tier": "must",
        "min_media_condition": "VG",
        "min_sleeve_condition": "VG",
        "max_price_cents": None,
        "last_scraped_at": None,
        "active_listings": 3,
        "title": "Awesome Record",
        "artist": "The Diggers",
        "year": 1999,
    }
    pool = _make_query_pool([scraped_row])
    digger_router.configure(pool)

    token = _make_test_jwt()
    resp = digger_api_client.get("/api/digger/wantlist", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["release_id"] == release_id
    assert item["tier"] == "must"
    assert item["active_listings"] == 3  # > 0 => release has live scraped listings
    assert item["title"] == "Awesome Record"

    # Guard the seam this smoke exists to protect: the real query must open the
    # cursor with row_factory=dict_row, else the router's r["..."] lookups break.
    from psycopg.rows import dict_row

    conn = pool.connection.return_value
    conn.cursor.assert_called_once_with(row_factory=dict_row)


def test_m1_smoke_wantlist_requires_authentication(digger_api_client: TestClient) -> None:
    """The real require_user dependency rejects an unauthenticated wantlist request."""
    digger_router.configure(_make_query_pool([]))
    resp = digger_api_client.get("/api/digger/wantlist")
    assert resp.status_code == 401

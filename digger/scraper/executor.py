"""End-to-end scrape of a single release.

Placeholder seller IDs are negative integers derived from the username via
BLAKE2b — they are deterministic, stable across processes, and negligible-collision
in a ~56-bit space. They are superseded by the real Discogs seller_id once the
seller-profile scrape runs; ``username`` is the stable lookup key.
"""

from __future__ import annotations

import hashlib
import logging

from common.postgres_resilient import AsyncPostgreSQLPool
from digger.metrics import SCRAPE_TOTAL, UNKNOWN_LAYOUT_TOTAL
from digger.scraper.http_client import DiggerHttpClient
from digger.scraper.listing_parser import UnknownLayoutError, parse_listings
from digger.scraper.types import ParsedListing

log = logging.getLogger(__name__)


def _placeholder_seller_id(username: str) -> int:
    """Return a deterministic, stable, negative placeholder seller_id for ``username``.

    Uses BLAKE2b with a 7-byte digest (~56-bit), giving negligible collision
    probability.  The value is always negative so it cannot clash with a real
    Discogs seller_id (which are positive).  It is superseded by the real id
    once the seller-profile scrape resolves it.
    """
    return -int.from_bytes(
        hashlib.blake2b(username.encode(), digest_size=7).digest(), "big"
    )


class ScrapeExecutor:
    """Orchestrates a single release scrape: fetch → parse → persist."""

    def __init__(
        self, http_client: DiggerHttpClient, pool: AsyncPostgreSQLPool
    ) -> None:
        self._http = http_client
        self._pool = pool

    async def scrape_release(self, release_id: int) -> bool:
        """Scrape marketplace listings for *release_id*.  Returns True on success."""
        url = f"https://www.discogs.com/sell/release/{release_id}"
        try:
            resp = await self._http.get(url)
            if resp.status_code == 429:
                SCRAPE_TOTAL.labels(outcome="http_429").inc()
                return False
            if resp.status_code >= 500:
                SCRAPE_TOTAL.labels(outcome="http_5xx").inc()
                return False
            if resp.status_code != 200:
                SCRAPE_TOTAL.labels(outcome="parse_error").inc()
                return False
            try:
                listings = parse_listings(resp.text, release_id)
            except UnknownLayoutError:
                UNKNOWN_LAYOUT_TOTAL.inc()
                SCRAPE_TOTAL.labels(outcome="unknown_layout").inc()
                return False
            await self._persist(release_id, listings)
            SCRAPE_TOTAL.labels(outcome="ok").inc()
            return True
        except Exception:
            log.exception("⚠️ scrape failed for release_id=%d", release_id)
            SCRAPE_TOTAL.labels(outcome="parse_error").inc()
            return False

    async def _persist(self, release_id: int, listings: list[ParsedListing]) -> None:
        """Write parsed listings to Postgres inside a single transaction.

        Algorithm:
        1. Resolve or synthesise a seller_id for each seller_username.
        2. Upsert each listing (update price/condition/last_seen_at, clear removed_at).
        3. Soft-delete any previously-seen listings not present in this scrape.
        4. Update the scrape-state row to record success.
        """
        async with self._pool.connection() as conn:
            await conn.set_autocommit(False)
            async with conn.transaction():
                async with conn.cursor() as cur:
                    # --- 1. Resolve seller IDs ---
                    seller_ids: dict[str, int] = {}
                    for listing in listings:
                        username = listing.seller_username
                        if username in seller_ids:
                            continue
                        await cur.execute(
                            "SELECT seller_id FROM digger.sellers WHERE username = %s",
                            (username,),
                        )
                        row = await cur.fetchone()
                        if row is not None:
                            seller_ids[username] = row[0]
                        else:
                            placeholder = _placeholder_seller_id(username)
                            await cur.execute(
                                "INSERT INTO digger.sellers(seller_id, username, region) "
                                "VALUES (%s, %s, 'other') ON CONFLICT (seller_id) DO NOTHING",
                                (placeholder, username),
                            )
                            seller_ids[username] = placeholder

                    # --- 2. Upsert each listing ---
                    seen_ids: list[int] = []
                    for listing in listings:
                        sid = seller_ids[listing.seller_username]
                        seen_ids.append(listing.listing_id)
                        await cur.execute(
                            """
                            INSERT INTO digger.listings(
                                listing_id, release_id, seller_id, price_value, price_currency,
                                media_condition, sleeve_condition, comments, posted_at,
                                first_seen_at, last_seen_at, removed_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now(), NULL)
                            ON CONFLICT (listing_id) DO UPDATE SET
                                price_value      = EXCLUDED.price_value,
                                price_currency   = EXCLUDED.price_currency,
                                media_condition  = EXCLUDED.media_condition,
                                sleeve_condition = EXCLUDED.sleeve_condition,
                                comments         = EXCLUDED.comments,
                                last_seen_at     = now(),
                                removed_at       = NULL
                            """,
                            (
                                listing.listing_id,
                                listing.release_id,
                                sid,
                                listing.price_value,
                                listing.price_currency,
                                listing.media_condition,
                                listing.sleeve_condition,
                                listing.comments,
                                listing.posted_at,
                            ),
                        )

                    # --- 3. Soft-delete vanished listings ---
                    if seen_ids:
                        await cur.execute(
                            "UPDATE digger.listings "
                            "   SET removed_at = now() "
                            " WHERE release_id = %s "
                            "   AND removed_at IS NULL "
                            "   AND listing_id != ALL(%s)",
                            (release_id, seen_ids),
                        )
                    else:
                        await cur.execute(
                            "UPDATE digger.listings "
                            "   SET removed_at = now() "
                            " WHERE release_id = %s AND removed_at IS NULL",
                            (release_id,),
                        )

                    # --- 4. Update scrape state ---
                    await cur.execute(
                        "UPDATE digger.release_scrape_state "
                        "   SET last_scraped_at = now(), consecutive_failures = 0, next_retry_at = NULL "
                        " WHERE release_id = %s",
                        (release_id,),
                    )

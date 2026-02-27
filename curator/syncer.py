"""Discogs collection and wantlist sync logic.

Handles paginated fetching from the Discogs API and upserting data into
PostgreSQL (user_collections, user_wantlists) and Neo4j (COLLECTED, WANTS
relationships on existing Release nodes).

Key Discogs API gotchas:
- Collection: response key is 'releases', release ID at item['basic_information']['id']
- Wantlist:   response key is 'wants',    release ID at item['id']
"""

import asyncio
from base64 import b64encode
from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
import time
from typing import Any
import urllib.parse
from uuid import UUID

import httpx
from psycopg.rows import dict_row
import structlog

from common import AsyncPostgreSQLPool, AsyncResilientNeo4jDriver


logger = structlog.get_logger(__name__)

DISCOGS_API_BASE = "https://api.discogs.com"
SYNC_DELAY_SECONDS = 0.5  # 0.5s between requests to stay under 60 req/min
PAGE_SIZE = 100


def _oauth_escape(value: str) -> str:
    """Percent-encode a string for OAuth signatures (RFC 3986)."""
    return urllib.parse.quote(value, safe="")


def _build_oauth_header(params: dict[str, str]) -> str:
    """Build an OAuth Authorization header."""
    parts = [f'{k}="{_oauth_escape(v)}"' for k, v in sorted(params.items())]
    return "OAuth " + ", ".join(parts)


def _hmac_sha1(
    method: str,
    url: str,
    oauth_params: dict[str, str],
    consumer_secret: str,
    token_secret: str,
) -> str:
    """Generate HMAC-SHA1 OAuth 1.0a signature."""
    param_string = "&".join(f"{_oauth_escape(k)}={_oauth_escape(v)}" for k, v in sorted(oauth_params.items()))
    base_string = "&".join(
        [
            _oauth_escape(method.upper()),
            _oauth_escape(url),
            _oauth_escape(param_string),
        ]
    )
    signing_key = f"{_oauth_escape(consumer_secret)}&{_oauth_escape(token_secret)}"
    digest = hmac.new(signing_key.encode("ascii"), base_string.encode("ascii"), hashlib.sha1).digest()
    return b64encode(digest).decode("ascii")


def _auth_header(
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    token_secret: str,
) -> str:
    """Build a complete OAuth 1.0a Authorization header for a request."""
    nonce = os.urandom(16).hex()
    timestamp = str(int(time.time()))

    params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp,
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }
    sig = _hmac_sha1(method, url, params, consumer_secret, token_secret)
    params["oauth_signature"] = sig
    return _build_oauth_header(params)


async def sync_collection(
    user_uuid: UUID,
    discogs_username: str,
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    token_secret: str,
    user_agent: str,
    pg_pool: AsyncPostgreSQLPool,
    neo4j_driver: AsyncResilientNeo4jDriver,
) -> int:
    """Sync user's Discogs collection to PostgreSQL and Neo4j.

    Collection API: GET /users/{username}/collection/folders/0/releases
    Response key: 'releases'
    Release ID: item['basic_information']['id']

    Returns:
        Total number of items synced
    """
    total_synced = 0
    page = 1

    logger.info("📋 Starting collection sync", user=discogs_username)

    async with httpx.AsyncClient() as client:
        while True:
            url = f"{DISCOGS_API_BASE}/users/{discogs_username}/collection/folders/0/releases"
            params = {"page": str(page), "per_page": str(PAGE_SIZE), "sort": "added", "sort_order": "desc"}
            full_url = f"{url}?{urllib.parse.urlencode(params)}"

            auth = _auth_header("GET", url, consumer_key, consumer_secret, access_token, token_secret)
            headers = {
                "Authorization": auth,
                "User-Agent": user_agent,
                "Accept": "application/json",
            }

            response = await client.get(full_url, headers=headers)

            if response.status_code == 429:
                logger.warning("⚠️ Rate limited by Discogs, waiting 60s...")
                await asyncio.sleep(60)
                continue

            if response.status_code != 200:
                logger.error(
                    "❌ Collection API error",
                    status=response.status_code,
                    page=page,
                )
                break

            data = response.json()
            releases = data.get("releases", [])

            if not releases:
                break

            # Upsert to PostgreSQL
            async with pg_pool.connection() as conn, conn.cursor() as cur:
                for item in releases:
                    basic = item.get("basic_information", {})
                    release_id = basic.get("id")
                    if not release_id:
                        continue

                    artists = basic.get("artists", [])
                    artist_name = artists[0]["name"] if artists else None
                    labels = basic.get("labels", [])
                    label_name = labels[0]["name"] if labels else None
                    formats_raw = basic.get("formats", [])
                    formats_json = json.dumps(formats_raw) if formats_raw else None

                    await cur.execute(
                        """
                            INSERT INTO user_collections (
                                user_id, release_id, instance_id, folder_id,
                                title, artist, year, formats, label,
                                rating, date_added, metadata, updated_at
                            ) VALUES (
                                %s::uuid, %s, %s, %s,
                                %s, %s, %s, %s::jsonb, %s,
                                %s, %s, %s::jsonb, NOW()
                            )
                            ON CONFLICT (user_id, release_id, instance_id) DO UPDATE SET
                                folder_id = EXCLUDED.folder_id,
                                title = EXCLUDED.title,
                                artist = EXCLUDED.artist,
                                year = EXCLUDED.year,
                                formats = EXCLUDED.formats,
                                label = EXCLUDED.label,
                                rating = EXCLUDED.rating,
                                date_added = EXCLUDED.date_added,
                                metadata = EXCLUDED.metadata,
                                updated_at = NOW()
                            """,
                        (
                            str(user_uuid),
                            release_id,
                            item.get("instance_id"),
                            item.get("folder_id"),
                            basic.get("title"),
                            artist_name,
                            basic.get("year"),
                            formats_json,
                            label_name,
                            item.get("rating", 0),
                            item.get("date_added"),
                            None,  # metadata reserved for future use
                        ),
                    )
                    total_synced += 1

            # Upsert to Neo4j — ensure User node and COLLECTED relationships
            cypher = """
            MERGE (u:User {id: $user_id})
            ON CREATE SET u.discogs_username = $discogs_username
            WITH u
            UNWIND $releases AS rel
            MATCH (r:Release {id: toString(rel.release_id)})
            MERGE (u)-[c:COLLECTED {instance_id: rel.instance_id}]->(r)
            SET c.rating = rel.rating,
                c.folder_id = rel.folder_id,
                c.date_added = rel.date_added,
                c.synced_at = $synced_at
            """
            neo4j_releases = [
                {
                    "release_id": item.get("basic_information", {}).get("id"),
                    "instance_id": str(item.get("instance_id", "")),
                    "rating": item.get("rating", 0),
                    "folder_id": item.get("folder_id"),
                    "date_added": item.get("date_added"),
                }
                for item in releases
                if item.get("basic_information", {}).get("id")
            ]

            if neo4j_releases:
                async with await neo4j_driver.session() as session:
                    await session.run(
                        cypher,
                        {
                            "user_id": str(user_uuid),
                            "discogs_username": discogs_username,
                            "releases": neo4j_releases,
                            "synced_at": datetime.now(UTC).isoformat(),
                        },
                    )

            # Check if there are more pages
            pagination = data.get("pagination", {})
            if page >= pagination.get("pages", 1):
                break

            page += 1
            await asyncio.sleep(SYNC_DELAY_SECONDS)

    logger.info("✅ Collection sync complete", user=discogs_username, total=total_synced)
    return total_synced


async def sync_wantlist(
    user_uuid: UUID,
    discogs_username: str,
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    token_secret: str,
    user_agent: str,
    pg_pool: AsyncPostgreSQLPool,
    neo4j_driver: AsyncResilientNeo4jDriver,
) -> int:
    """Sync user's Discogs wantlist to PostgreSQL and Neo4j.

    Wantlist API: GET /users/{username}/wants
    Response key: 'wants'
    Release ID: item['id']  ← NOTE: top-level, NOT nested in basic_information

    Returns:
        Total number of items synced
    """
    total_synced = 0
    page = 1

    logger.info("📋 Starting wantlist sync", user=discogs_username)

    async with httpx.AsyncClient() as client:
        while True:
            url = f"{DISCOGS_API_BASE}/users/{discogs_username}/wants"
            params = {"page": str(page), "per_page": str(PAGE_SIZE)}
            full_url = f"{url}?{urllib.parse.urlencode(params)}"

            auth = _auth_header("GET", url, consumer_key, consumer_secret, access_token, token_secret)
            headers = {
                "Authorization": auth,
                "User-Agent": user_agent,
                "Accept": "application/json",
            }

            response = await client.get(full_url, headers=headers)

            if response.status_code == 429:
                logger.warning("⚠️ Rate limited by Discogs, waiting 60s...")
                await asyncio.sleep(60)
                continue

            if response.status_code != 200:
                logger.error(
                    "❌ Wantlist API error",
                    status=response.status_code,
                    page=page,
                )
                break

            data = response.json()
            wants = data.get("wants", [])

            if not wants:
                break

            # Upsert to PostgreSQL
            async with pg_pool.connection() as conn, conn.cursor() as cur:
                for item in wants:
                    # CRITICAL: wantlist ID is at item['id'] (top-level)
                    # unlike collection where it's at item['basic_information']['id']
                    release_id = item.get("id")
                    if not release_id:
                        continue

                    basic = item.get("basic_information", {})
                    artists = basic.get("artists", [])
                    artist_name = artists[0]["name"] if artists else None
                    formats = basic.get("formats", [])
                    fmt_name = formats[0]["name"] if formats else None

                    await cur.execute(
                        """
                            INSERT INTO user_wantlists (
                                user_id, release_id,
                                title, artist, year, format,
                                rating, notes, date_added, updated_at
                            ) VALUES (
                                %s::uuid, %s,
                                %s, %s, %s, %s,
                                %s, %s, %s, NOW()
                            )
                            ON CONFLICT (user_id, release_id) DO UPDATE SET
                                title = EXCLUDED.title,
                                artist = EXCLUDED.artist,
                                year = EXCLUDED.year,
                                format = EXCLUDED.format,
                                rating = EXCLUDED.rating,
                                notes = EXCLUDED.notes,
                                date_added = EXCLUDED.date_added,
                                updated_at = NOW()
                            """,
                        (
                            str(user_uuid),
                            release_id,
                            basic.get("title"),
                            artist_name,
                            basic.get("year"),
                            fmt_name,
                            item.get("rating", 0),
                            item.get("notes"),
                            item.get("date_added"),
                        ),
                    )
                    total_synced += 1

            # Upsert to Neo4j — ensure User node and WANTS relationships
            cypher = """
            MERGE (u:User {id: $user_id})
            ON CREATE SET u.discogs_username = $discogs_username
            WITH u
            UNWIND $wants AS w
            MATCH (r:Release {id: toString(w.release_id)})
            MERGE (u)-[wnt:WANTS]->(r)
            SET wnt.rating = w.rating,
                wnt.date_added = w.date_added,
                wnt.synced_at = $synced_at
            """
            neo4j_wants = [
                {
                    "release_id": item.get("id"),
                    "rating": item.get("rating", 0),
                    "date_added": item.get("date_added"),
                }
                for item in wants
                if item.get("id")
            ]

            if neo4j_wants:
                async with await neo4j_driver.session() as session:
                    await session.run(
                        cypher,
                        {
                            "user_id": str(user_uuid),
                            "discogs_username": discogs_username,
                            "wants": neo4j_wants,
                            "synced_at": datetime.now(UTC).isoformat(),
                        },
                    )

            pagination = data.get("pagination", {})
            if page >= pagination.get("pages", 1):
                break

            page += 1
            await asyncio.sleep(SYNC_DELAY_SECONDS)

    logger.info("✅ Wantlist sync complete", user=discogs_username, total=total_synced)
    return total_synced


async def run_full_sync(
    user_uuid: UUID,
    sync_id: str,
    pg_pool: AsyncPostgreSQLPool,
    neo4j_driver: AsyncResilientNeo4jDriver,
    discogs_user_agent: str,
) -> dict[str, Any]:
    """Run a full collection + wantlist sync for a user.

    Fetches OAuth credentials from PostgreSQL and app config,
    then syncs collection and wantlist.

    Returns:
        dict with sync results (items_synced, pages_fetched, error)
    """
    error_message = None
    collection_count = 0
    wantlist_count = 0

    try:
        # Fetch OAuth tokens for the user
        async with pg_pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                    SELECT ot.access_token, ot.access_secret, ot.provider_username
                    FROM oauth_tokens ot
                    WHERE ot.user_id = %s::uuid AND ot.provider = 'discogs'
                    """,
                (str(user_uuid),),
            )
            token = await cur.fetchone()

            if not token:
                raise ValueError("No Discogs OAuth token found for user. Please connect Discogs first.")

            # Fetch app credentials
            await cur.execute("SELECT key, value FROM app_config WHERE key IN ('discogs_consumer_key', 'discogs_consumer_secret')")
            config_rows = await cur.fetchall()
            app_config = {row["key"]: row["value"] for row in config_rows}

        if "discogs_consumer_key" not in app_config or "discogs_consumer_secret" not in app_config:
            raise ValueError("Discogs app credentials not configured in app_config table")

        discogs_username = token["provider_username"]

        # Run collection sync
        collection_count = await sync_collection(
            user_uuid=user_uuid,
            discogs_username=discogs_username,
            consumer_key=app_config["discogs_consumer_key"],
            consumer_secret=app_config["discogs_consumer_secret"],
            access_token=token["access_token"],
            token_secret=token["access_secret"],
            user_agent=discogs_user_agent,
            pg_pool=pg_pool,
            neo4j_driver=neo4j_driver,
        )

        # Run wantlist sync
        wantlist_count = await sync_wantlist(
            user_uuid=user_uuid,
            discogs_username=discogs_username,
            consumer_key=app_config["discogs_consumer_key"],
            consumer_secret=app_config["discogs_consumer_secret"],
            access_token=token["access_token"],
            token_secret=token["access_secret"],
            user_agent=discogs_user_agent,
            pg_pool=pg_pool,
            neo4j_driver=neo4j_driver,
        )

    except Exception as exc:
        error_message = str(exc)
        logger.error("❌ Sync failed", user_id=str(user_uuid), error=error_message)

    # Update sync_history record
    final_status = "failed" if error_message else "completed"
    async with pg_pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
                UPDATE sync_history
                SET status = %s,
                    items_synced = %s,
                    error_message = %s,
                    completed_at = NOW()
                WHERE id = %s::uuid
                """,
            (final_status, collection_count + wantlist_count, error_message, sync_id),
        )

    return {
        "sync_id": sync_id,
        "status": final_status,
        "collection_count": collection_count,
        "wantlist_count": wantlist_count,
        "error": error_message,
    }

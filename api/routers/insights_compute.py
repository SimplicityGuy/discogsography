"""Internal computation query endpoints for the insights service.

Exposes raw Neo4j and PostgreSQL query results as JSON so the insights
service can fetch data over HTTP instead of importing query modules directly.
"""

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
import httpx
from psycopg.rows import dict_row
import structlog

from api.auth import decrypt_oauth_token, get_oauth_encryption_key
from api.limiter import limiter
from api.queries.insights_neo4j_queries import (
    query_artist_centrality,
    query_genre_trends,
    query_label_longevity,
    query_monthly_anniversaries,
)
from api.queries.insights_pg_queries import query_data_completeness
from api.queries.rarity_queries import fetch_all_rarity_signals
from api.syncer import DISCOGS_API_BASE, MAX_RATE_LIMIT_RETRIES, _auth_header


logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/internal/insights", tags=["insights-compute"])

_neo4j: Any = None
_pool: Any = None
_redis: Any = None
_config: Any = None

_ENRICHMENT_DELAY_SECONDS = 1.0  # 1 req/sec to stay under 60 req/min
_STALENESS_DAYS = 7

# Cache TTL for data-completeness (6 hours — full table scans are very expensive)
_COMPLETENESS_CACHE_TTL = 21600


def configure(neo4j: Any, pool: Any, redis: Any = None, config: Any = None) -> None:
    """Configure the insights compute router with database connections."""
    global _neo4j, _pool, _redis, _config
    _neo4j = neo4j
    _pool = pool
    _redis = redis
    _config = config


@router.get("/artist-centrality")
@limiter.limit("5/minute")
async def artist_centrality(request: Request, limit: int = Query(100, ge=1, le=500)) -> JSONResponse:  # noqa: ARG001
    """Return raw artist centrality query results from Neo4j."""
    if not _neo4j:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    results = await query_artist_centrality(_neo4j, limit=limit)
    return JSONResponse(content={"items": results})


@router.get("/genre-trends")
@limiter.limit("5/minute")
async def genre_trends(request: Request) -> JSONResponse:  # noqa: ARG001
    """Return raw genre trends query results from Neo4j."""
    if not _neo4j:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    results = await query_genre_trends(_neo4j)
    return JSONResponse(content={"items": results})


@router.get("/label-longevity")
@limiter.limit("5/minute")
async def label_longevity(request: Request, limit: int = Query(50, ge=1, le=500)) -> JSONResponse:  # noqa: ARG001
    """Return raw label longevity query results from Neo4j."""
    if not _neo4j:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    results = await query_label_longevity(_neo4j, limit=limit)
    return JSONResponse(content={"items": results})


@router.get("/anniversaries")
@limiter.limit("5/minute")
async def anniversaries(
    request: Request,  # noqa: ARG001
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    milestones: str = Query("25,30,40,50,75,100"),
) -> JSONResponse:
    """Return raw monthly anniversary query results from Neo4j."""
    if not _neo4j:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    try:
        milestone_years = [int(m.strip()) for m in milestones.split(",") if m.strip()]
    except ValueError:
        return JSONResponse(content={"error": "milestones must be comma-separated integers"}, status_code=422)
    results = await query_monthly_anniversaries(_neo4j, current_year=year, current_month=month, milestone_years=milestone_years)
    return JSONResponse(content={"items": results})


@router.get("/data-completeness")
@limiter.limit("5/minute")
async def data_completeness(request: Request) -> JSONResponse:  # noqa: ARG001
    """Return raw data completeness query results from PostgreSQL.

    Caches results in Redis (6h TTL) because the underlying queries do
    full sequential scans — the releases table alone takes ~400s.
    """
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    cache_key = "insights:data-completeness"
    if _redis:
        try:
            cached = await _redis.get(cache_key)
            if cached:
                return JSONResponse(content=json.loads(cached))
        except Exception:
            logger.debug("⚠️ Data completeness cache get failed")

    results = await query_data_completeness(_pool)
    response = {"items": results}

    if _redis:
        try:
            await _redis.setex(cache_key, _COMPLETENESS_CACHE_TTL, json.dumps(response))
        except Exception:
            logger.debug("⚠️ Data completeness cache set failed")

    return JSONResponse(content=response)


@router.get("/rarity-scores")
@limiter.limit("5/minute")
async def rarity_scores(request: Request) -> JSONResponse:  # noqa: ARG001
    """Return computed rarity scores for all releases from Neo4j."""
    if not _neo4j:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    results = await fetch_all_rarity_signals(_neo4j, _pool)
    return JSONResponse(content={"items": results})


async def _enrich_community_counts(
    pool: Any,
    neo4j: Any,
    encryption_key: str | None,
) -> dict[str, Any]:
    """Fetch community have/want counts from Discogs API for releases in user collections."""
    # 1. Find releases needing enrichment (new or stale)
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT DISTINCT release_id FROM (
                SELECT release_id FROM user_collections
                UNION
                SELECT release_id FROM user_wantlists
            ) AS combined
            WHERE release_id NOT IN (
                SELECT release_id FROM insights.community_counts
                WHERE fetched_at > NOW() - make_interval(days => %s)
            )
            """,
            (_STALENESS_DAYS,),
        )
        rows = await cur.fetchall()
        release_ids = [r["release_id"] for r in rows]

    if not release_ids:
        logger.info("📊 No releases need community enrichment")
        return {"enriched": 0, "skipped": 0, "errors": 0}

    logger.info("📊 Releases needing community enrichment", count=len(release_ids))

    # 2. Get OAuth credentials (any user with valid Discogs OAuth)
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT ot.access_token, ot.access_secret, ot.provider_username
            FROM oauth_tokens ot
            WHERE ot.provider = 'discogs'
            LIMIT 1
            """
        )
        token = await cur.fetchone()

        if not token:
            logger.warning("⚠️ No Discogs OAuth credentials for community enrichment")
            return {"enriched": 0, "skipped": len(release_ids), "errors": 0, "error": "no_credentials"}

        access_token = decrypt_oauth_token(token["access_token"], encryption_key)
        access_secret = decrypt_oauth_token(token["access_secret"], encryption_key)

        await cur.execute("SELECT key, value FROM app_config WHERE key IN ('discogs_consumer_key', 'discogs_consumer_secret')")
        config_rows = await cur.fetchall()
        app_config = {r["key"]: r["value"] for r in config_rows}
        if "discogs_consumer_key" not in app_config or "discogs_consumer_secret" not in app_config:
            logger.warning("⚠️ Discogs app credentials not configured")
            return {"enriched": 0, "skipped": len(release_ids), "errors": 0, "error": "no_credentials"}
        consumer_key = decrypt_oauth_token(app_config["discogs_consumer_key"], encryption_key)
        consumer_secret = decrypt_oauth_token(app_config["discogs_consumer_secret"], encryption_key)

    # 3. Fetch community counts from Discogs API
    enriched = 0
    errors = 0
    batch: list[dict[str, Any]] = []
    rate_limit_retries = 0

    exhausted = False
    async with httpx.AsyncClient(timeout=30.0) as client:
        for release_id in release_ids:
            if exhausted:
                break

            url = f"{DISCOGS_API_BASE}/releases/{release_id}"
            auth = _auth_header(
                "GET",
                url,
                consumer_key,
                consumer_secret,
                access_token,
                access_secret,
            )
            headers = {
                "Authorization": auth,
                "User-Agent": "discogsography/1.0 +https://github.com/SimplicityGuy/discogsography",
                "Accept": "application/json",
            }

            # Retry loop for rate limiting — ensures the same release is retried
            while True:
                response = await client.get(url, headers=headers)

                if response.status_code == 429:
                    rate_limit_retries += 1
                    if rate_limit_retries > MAX_RATE_LIMIT_RETRIES:
                        logger.error("❌ Rate limit retries exhausted during enrichment")
                        exhausted = True
                        break
                    logger.warning("⚠️ Rate limited, waiting 60s...", retry=rate_limit_retries)
                    await asyncio.sleep(60)
                    continue

                rate_limit_retries = 0
                break  # Got a non-429 response

            if exhausted:
                break

            if response.status_code != 200:
                logger.warning("⚠️ Discogs API error for release", release_id=release_id, status=response.status_code)
                errors += 1
                await asyncio.sleep(_ENRICHMENT_DELAY_SECONDS)
                continue

            data = response.json()
            community = data.get("community", {})
            have = community.get("have", 0)
            want = community.get("want", 0)

            # Upsert to PostgreSQL
            async with pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO insights.community_counts (release_id, have_count, want_count, fetched_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (release_id) DO UPDATE SET
                        have_count = EXCLUDED.have_count,
                        want_count = EXCLUDED.want_count,
                        fetched_at = NOW()
                    """,
                    (release_id, have, want),
                )

            batch.append({"release_id": release_id, "have": have, "want": want})
            enriched += 1
            await asyncio.sleep(_ENRICHMENT_DELAY_SECONDS)

    # 4. Batch update Neo4j Release nodes
    if batch and neo4j is not None:
        cypher = """
        UNWIND $batch AS item
        MATCH (r:Release {id: toString(item.release_id)})
        SET r.community_have = item.have,
            r.community_want = item.want
        """
        try:
            async with neo4j.session() as session:
                result = await session.run(cypher, {"batch": batch})
                await result.consume()
            logger.info("✅ Neo4j Release nodes updated with community counts", count=len(batch))
        except Exception as e:
            logger.error("❌ Failed to update Neo4j community counts", error=str(e))

    logger.info("✅ Community enrichment complete", enriched=enriched, errors=errors)
    return {"enriched": enriched, "skipped": len(release_ids) - enriched - errors, "errors": errors}


@router.get("/community-enrichment")
@limiter.limit("1/minute")
async def community_enrichment(request: Request) -> JSONResponse:  # noqa: ARG001
    """Enrich releases in user collections with Discogs community have/want counts."""
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    encryption_key = get_oauth_encryption_key(_config.encryption_master_key) if _config else None
    result = await _enrich_community_counts(_pool, _neo4j, encryption_key)
    return JSONResponse(content=result)

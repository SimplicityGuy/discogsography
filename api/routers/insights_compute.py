"""Internal computation query endpoints for the insights service.

Exposes raw Neo4j and PostgreSQL query results as JSON so the insights
service can fetch data over HTTP instead of importing query modules directly.
"""

import asyncio
import json
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
import httpx
from neo4j.exceptions import ClientError, Neo4jError, TransientError
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
from common import describe_exception


logger = structlog.get_logger(__name__)

_neo4j: Any = None
_pool: Any = None
_redis: Any = None
_config: Any = None


async def require_internal_secret(
    x_internal_secret: Annotated[str | None, Header()] = None,
) -> None:
    """Gate the internal insights router with a shared secret.

    These endpoints are mounted on the public app and reachable through the
    explore ``/api/{path:path}`` proxy, so the ``/api/internal`` prefix alone
    provides no isolation. The insights service presents the configured secret
    as the ``X-Internal-Secret`` header; any other caller is rejected.

    Fails closed: if no secret is configured the router is unreachable rather
    than anonymously open.
    """
    configured = getattr(_config, "insights_internal_secret", None) if _config is not None else None
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal insights API is not configured",
        )
    if not x_internal_secret or not secrets.compare_digest(x_internal_secret, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing internal API credentials",
        )


router = APIRouter(
    prefix="/api/internal/insights",
    tags=["insights-compute"],
    dependencies=[Depends(require_internal_secret)],
)

_ENRICHMENT_DELAY_SECONDS = 1.0  # 1 req/sec to stay under 60 req/min
_STALENESS_DAYS = 7

# Hard cap on releases enriched per invocation.
#
# The enrichment loop is rate-limited to one Discogs request per second, so its
# wall-clock cost is unbounded in the number of stale releases — a backlog of
# 10k releases would take ~3 hours and blow ANY client read timeout. That is why
# community_enrichment failed four times in production with an (empty-stringing)
# ReadTimeout: the endpoint simply never returned.
#
# Bounding the batch makes the endpoint's worst case predictable
# (~1500 * 1.5s ≈ 2250s, comfortably inside the insights client's 3600s read
# budget) and costs nothing in completeness: the daily scheduler drains the
# remaining backlog on subsequent cycles.
MAX_ENRICHMENT_RELEASES = 1500

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


# Neo4j error codes that mean "the database gave up on this transaction", not
# "the server has a bug". Both are retryable and must surface as 503, never 500.
#
# TransactionTimedOutClientConfiguration is a *ClientError*, not a TransientError,
# which is exactly why the previous handler missed it: rarity-scores blew
# db.transaction.timeout (600s) on every production run and the ClientError
# escaped as an unhandled 500.
TRANSACTION_TIMEOUT_CODES = frozenset(
    {
        "Neo.ClientError.Transaction.TransactionTimedOut",
        "Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration",
    }
)


def _find_retryable_neo4j_error(exc: BaseException) -> Neo4jError | None:
    """Return the first retryable Neo4j error in ``exc``, or ``None``.

    Unwraps ``BaseExceptionGroup`` (the driver's internals can surface a
    transaction failure wrapped in one) and ``__cause__`` chains, so a retryable
    error is recognised no matter how it was re-raised.
    """
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            found = _find_retryable_neo4j_error(inner)
            if found is not None:
                return found
        return None
    if isinstance(exc, TransientError):
        return exc
    if isinstance(exc, ClientError) and exc.code in TRANSACTION_TIMEOUT_CODES:
        return exc
    cause = exc.__cause__
    if cause is not None and cause is not exc:
        return _find_retryable_neo4j_error(cause)
    return None


@router.get("/rarity-scores")
@limiter.limit("5/minute")
async def rarity_scores(request: Request) -> JSONResponse:  # noqa: ARG001
    """Return computed rarity scores for all releases from Neo4j."""
    if not _neo4j:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    try:
        results = await fetch_all_rarity_signals(_neo4j, _pool)
    except (TransientError, ClientError, BaseExceptionGroup) as exc:
        # TransientError: e.g. MemoryPoolOutOfMemoryError under DB pressure.
        # ClientError: a transaction timeout (see TRANSACTION_TIMEOUT_CODES).
        # Neither is a server bug — return 503 so the caller logs a meaningful,
        # retryable failure instead of a bare 500.
        retryable = _find_retryable_neo4j_error(exc)
        if retryable is None:
            raise
        logger.warning(
            "⚠️ Rarity computation hit a retryable Neo4j error",
            code=retryable.code,
            exc_info=True,
        )
        return JSONResponse(
            content={"error": "Neo4j temporarily unavailable (retryable error)", "code": retryable.code},
            status_code=503,
        )
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
        all_release_ids = [r["release_id"] for r in rows]

    if not all_release_ids:
        logger.info("📊 No releases need community enrichment")
        return {"enriched": 0, "skipped": 0, "errors": 0, "remaining": 0}

    # Bound the batch so this endpoint always returns inside the caller's read
    # timeout — the leftover backlog is picked up by the next scheduled cycle.
    release_ids = all_release_ids[:MAX_ENRICHMENT_RELEASES]
    remaining = len(all_release_ids) - len(release_ids)
    if remaining:
        logger.info(
            "📊 Community enrichment backlog capped for this cycle",
            batch_size=len(release_ids),
            backlog=len(all_release_ids),
            remaining=remaining,
        )

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
            return {"enriched": 0, "skipped": len(release_ids), "errors": 0, "remaining": remaining, "error": "no_credentials"}

        access_token = decrypt_oauth_token(token["access_token"], encryption_key)
        access_secret = decrypt_oauth_token(token["access_secret"], encryption_key)

        await cur.execute("SELECT key, value FROM app_config WHERE key IN ('discogs_consumer_key', 'discogs_consumer_secret')")
        config_rows = await cur.fetchall()
        app_config = {r["key"]: r["value"] for r in config_rows}
        if "discogs_consumer_key" not in app_config or "discogs_consumer_secret" not in app_config:
            logger.warning("⚠️ Discogs app credentials not configured")
            return {"enriched": 0, "skipped": len(release_ids), "errors": 0, "remaining": remaining, "error": "no_credentials"}
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

            # Retry loop for rate limiting — ensures the same release is retried.
            # A transient transport error (timeout, reset, truncated body) must
            # count as an error for THIS release and move on, not abort the whole
            # run — mirroring the non-200 branch below.
            fetch_failed = False
            while True:
                try:
                    response = await client.get(url, headers=headers)
                except httpx.HTTPError as exc:
                    logger.warning("⚠️ Discogs API request failed for release", release_id=release_id, error=describe_exception(exc))
                    fetch_failed = True
                    break

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

            if fetch_failed:
                errors += 1
                await asyncio.sleep(_ENRICHMENT_DELAY_SECONDS)
                continue

            if response.status_code != 200:
                logger.warning("⚠️ Discogs API error for release", release_id=release_id, status=response.status_code)
                errors += 1
                await asyncio.sleep(_ENRICHMENT_DELAY_SECONDS)
                continue

            try:
                data = response.json()
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("⚠️ Discogs API returned a non-JSON body for release", release_id=release_id, error=str(exc))
                errors += 1
                await asyncio.sleep(_ENRICHMENT_DELAY_SECONDS)
                continue
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

    logger.info("✅ Community enrichment complete", enriched=enriched, errors=errors, remaining=remaining)
    return {
        "enriched": enriched,
        "skipped": len(release_ids) - enriched - errors,
        "errors": errors,
        "remaining": remaining,
    }


@router.get("/community-enrichment")
@limiter.limit("1/minute")
async def community_enrichment(request: Request) -> JSONResponse:  # noqa: ARG001
    """Enrich releases in user collections with Discogs community have/want counts."""
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    encryption_key = get_oauth_encryption_key(_config.encryption_master_key) if _config else None
    result = await _enrich_community_counts(_pool, _neo4j, encryption_key)
    return JSONResponse(content=result)

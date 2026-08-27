"""Computation orchestration for insights.

Each compute_and_store_* function:
1. Fetches raw query results from the API service over HTTP
2. Clears the previous results from the insights table
3. Inserts the new results
4. Returns the number of rows written
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import httpx
import structlog

from common import describe_exception
from insights.catalog_api_contract import (
    ANNIVERSARIES_PATH,
    ARTIST_CENTRALITY_PATH,
    COMMUNITY_ENRICHMENT_PATH,
    DATA_COMPLETENESS_PATH,
    GENRE_TRENDS_PATH,
    LABEL_LONGEVITY_PATH,
    RARITY_SCORES_PATH,
)


if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


logger = structlog.get_logger(__name__)


# ── Per-endpoint HTTP timeouts ──────────────────────────────────────────────
#
# Every /api/internal/insights/* endpoint runs an uncached full-scan computation
# on a cold cache, so a single scalar timeout for the whole client is wrong in
# both directions: passing ``timeout=300.0`` also gives *connect* 300 seconds
# (a dead API should fail in seconds), while 300s of *read* is far under the
# documented worst-case latency of the heavy endpoints. Production saw
# data_completeness fail once with ReadTimeout and community_enrichment fail
# four times for the same reason.
#
# Split the budget: a short connect/write/pool timeout, and a per-endpoint read
# timeout with generous headroom over the worst observed cold-cache latency.
#
#   endpoint              worst observed cold-cache cost          read budget
#   --------------------  --------------------------------------  -----------
#   data-completeness     ~400s releases seq scan (>600s on bad         1800s
#                         days); API caches the result for 6h
#   rarity-scores         chunked full-graph Neo4j scans                1800s
#   community-enrichment  1 Discogs request/second, capped at           3600s
#                         MAX_ENRICHMENT_RELEASES per invocation
#   everything else       full-graph Neo4j aggregations                  900s
_CONNECT_TIMEOUT_SECONDS = 10.0
_WRITE_TIMEOUT_SECONDS = 30.0
_POOL_TIMEOUT_SECONDS = 60.0
DEFAULT_READ_TIMEOUT_SECONDS = 900.0

ENDPOINT_READ_TIMEOUTS: dict[str, float] = {
    DATA_COMPLETENESS_PATH: 1800.0,
    RARITY_SCORES_PATH: 1800.0,
    COMMUNITY_ENRICHMENT_PATH: 3600.0,
}


def endpoint_timeout(path: str | None = None) -> httpx.Timeout:
    """Return the ``httpx.Timeout`` to use for an internal computation endpoint.

    Args:
        path: The API path being requested. ``None`` yields the default budget,
            which is what the shared client is constructed with.

    Returns:
        A timeout with a short connect/write/pool budget and a read budget sized
        for that endpoint's worst-case cold-cache latency.
    """
    read = ENDPOINT_READ_TIMEOUTS.get(path or "", DEFAULT_READ_TIMEOUT_SECONDS)
    return httpx.Timeout(
        connect=_CONNECT_TIMEOUT_SECONDS,
        read=read,
        write=_WRITE_TIMEOUT_SECONDS,
        pool=_POOL_TIMEOUT_SECONDS,
    )


async def _log_computation(
    pool: Any,
    insight_type: str,
    status: str,
    started_at: datetime,
    rows_affected: int = 0,
    error_message: str | None = None,
) -> None:
    """Write a computation log entry."""
    completed_at = datetime.now(UTC)
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)
    async with pool.connection() as conn, conn.cursor() as cursor:
        cursor = cast("Any", cursor)
        await cursor.execute(
            """
            INSERT INTO insights.computation_log
                (insight_type, status, started_at, completed_at, rows_affected, duration_ms, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (insight_type, status, started_at, completed_at, rows_affected, duration_ms, error_message),
        )


async def _fetch_from_api(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any] | None = None,
    timeout: httpx.Timeout | float | None = None,
) -> list[dict[str, Any]]:
    """Fetch computation data from the API service.

    Unless ``timeout`` is given explicitly, the per-endpoint budget from
    :func:`endpoint_timeout` is applied — never the client's scalar default.
    """
    kwargs: dict[str, Any] = {}
    if params:
        kwargs["params"] = params
    kwargs["timeout"] = endpoint_timeout(path) if timeout is None else timeout
    response = await client.get(path, **kwargs)
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    items: list[dict[str, Any]] = data.get("items", [])
    return items


async def compute_and_store_artist_centrality(client: httpx.AsyncClient, pool: Any, limit: int = 100) -> int:
    """Compute artist centrality and store results."""
    started_at = datetime.now(UTC)
    try:
        results = await _fetch_from_api(client, ARTIST_CENTRALITY_PATH, {"limit": limit})
        if not results:
            logger.info("📊 No artist centrality results to store")
            await _log_computation(pool, "artist_centrality", "completed", started_at, 0)
            return 0

        # Filter out artists with missing names (Neo4j nodes without a name property)
        results = [r for r in results if r.get("artist_name")]
        if not results:
            logger.info("📊 No artist centrality results with valid names")
            await _log_computation(pool, "artist_centrality", "completed", started_at, 0)
            return 0

        async with pool.connection() as conn:
            await conn.set_autocommit(False)
            async with conn.transaction(), conn.cursor() as cursor:
                cursor = cast("Any", cursor)
                await cursor.execute("DELETE FROM insights.artist_centrality")
                for rank, row in enumerate(results, 1):
                    await cursor.execute(
                        """
                            INSERT INTO insights.artist_centrality (rank, artist_id, artist_name, edge_count)
                            VALUES (%s, %s, %s, %s)
                            """,
                        (rank, row["artist_id"], row["artist_name"], row["edge_count"]),
                    )
        logger.info("💾 Artist centrality stored", count=len(results))
        await _log_computation(pool, "artist_centrality", "completed", started_at, len(results))
        return len(results)
    except Exception as e:
        logger.error("❌ Artist centrality computation failed", error=describe_exception(e))
        try:
            await _log_computation(pool, "artist_centrality", "failed", started_at, error_message=describe_exception(e))
        except Exception as log_err:
            logger.warning("⚠️ Failed to log computation error", error=describe_exception(log_err))
        raise


async def compute_and_store_genre_trends(client: httpx.AsyncClient, pool: Any) -> int:
    """Compute genre trends and store results."""
    started_at = datetime.now(UTC)
    try:
        results = await _fetch_from_api(client, GENRE_TRENDS_PATH)
        if not results:
            await _log_computation(pool, "genre_trends", "completed", started_at, 0)
            return 0

        async with pool.connection() as conn:
            await conn.set_autocommit(False)
            async with conn.transaction(), conn.cursor() as cursor:
                cursor = cast("Any", cursor)
                await cursor.execute("DELETE FROM insights.genre_trends")
                for row in results:
                    await cursor.execute(
                        """
                            INSERT INTO insights.genre_trends (genre, decade, release_count)
                            VALUES (%s, %s, %s)
                            """,
                        (row["genre"], row["decade"], row["release_count"]),
                    )
        logger.info("💾 Genre trends stored", count=len(results))
        await _log_computation(pool, "genre_trends", "completed", started_at, len(results))
        return len(results)
    except Exception as e:
        logger.error("❌ Genre trends computation failed", error=describe_exception(e))
        try:
            await _log_computation(pool, "genre_trends", "failed", started_at, error_message=describe_exception(e))
        except Exception as log_err:
            logger.warning("⚠️ Failed to log computation error", error=describe_exception(log_err))
        raise


async def compute_and_store_label_longevity(client: httpx.AsyncClient, pool: Any, limit: int = 50) -> int:
    """Compute label longevity and store results."""
    started_at = datetime.now(UTC)
    try:
        results = await _fetch_from_api(client, LABEL_LONGEVITY_PATH, {"limit": limit})
        if not results:
            await _log_computation(pool, "label_longevity", "completed", started_at, 0)
            return 0

        current_year = datetime.now(UTC).year
        async with pool.connection() as conn:
            await conn.set_autocommit(False)
            async with conn.transaction(), conn.cursor() as cursor:
                cursor = cast("Any", cursor)
                await cursor.execute("DELETE FROM insights.label_longevity")
                for rank, row in enumerate(results, 1):
                    still_active = row["last_year"] is not None and row["last_year"] >= current_year - 2
                    await cursor.execute(
                        """
                            INSERT INTO insights.label_longevity
                                (rank, label_id, label_name, first_year, last_year,
                                 years_active, total_releases, peak_decade, still_active)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                        (
                            rank,
                            row["label_id"],
                            row["label_name"],
                            row["first_year"],
                            row["last_year"],
                            row["years_active"],
                            row["total_releases"],
                            row.get("peak_decade"),
                            still_active,
                        ),
                    )
        logger.info("💾 Label longevity stored", count=len(results))
        await _log_computation(pool, "label_longevity", "completed", started_at, len(results))
        return len(results)
    except Exception as e:
        logger.error("❌ Label longevity computation failed", error=describe_exception(e))
        try:
            await _log_computation(pool, "label_longevity", "failed", started_at, error_message=describe_exception(e))
        except Exception as log_err:
            logger.warning("⚠️ Failed to log computation error", error=describe_exception(log_err))
        raise


async def compute_and_store_anniversaries(
    client: httpx.AsyncClient,
    pool: Any,
    current_year: int | None = None,
    current_month: int | None = None,
    milestone_years: list[int] | None = None,
) -> int:
    """Compute monthly anniversaries and store results."""
    started_at = datetime.now(UTC)
    now = datetime.now(UTC)
    year = current_year or now.year
    month = current_month or now.month

    if milestone_years is None:
        milestone_years = [25, 30, 40, 50, 75, 100]

    try:
        milestones_str = ",".join(str(m) for m in milestone_years)
        results = await _fetch_from_api(
            client,
            ANNIVERSARIES_PATH,
            {"year": year, "month": month, "milestones": milestones_str},
        )
        if not results:
            await _log_computation(pool, "anniversaries", "completed", started_at, 0)
            return 0
        rows_written = 0
        async with pool.connection() as conn:
            await conn.set_autocommit(False)
            async with conn.transaction(), conn.cursor() as cursor:
                cursor = cast("Any", cursor)
                await cursor.execute(
                    "DELETE FROM insights.monthly_anniversaries WHERE computed_year = %s AND computed_month = %s",
                    (year, month),
                )
                for row in results:
                    anniversary = year - int(row["release_year"])
                    if anniversary not in milestone_years:
                        logger.warning(
                            "⚠️ Skipping anniversary row — computed anniversary not in milestones",
                            master_id=row.get("master_id"),
                            anniversary=anniversary,
                        )
                        continue
                    await cursor.execute(
                        """
                            INSERT INTO insights.monthly_anniversaries
                                (master_id, title, artist_name, release_year, anniversary,
                                 computed_month, computed_year)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (master_id, computed_year, computed_month) DO UPDATE
                            SET title = EXCLUDED.title, artist_name = EXCLUDED.artist_name,
                                anniversary = EXCLUDED.anniversary, computed_at = NOW()
                            """,
                        (row["master_id"], row["title"], row.get("artist_name"), int(row["release_year"]), anniversary, month, year),
                    )
                    rows_written += 1
        logger.info("💾 Monthly anniversaries stored", count=rows_written, year=year, month=month)
        await _log_computation(pool, "anniversaries", "completed", started_at, rows_written)
        return rows_written
    except Exception as e:
        logger.error("❌ Anniversaries computation failed", error=describe_exception(e))
        try:
            await _log_computation(pool, "anniversaries", "failed", started_at, error_message=describe_exception(e))
        except Exception as log_err:
            logger.warning("⚠️ Failed to log computation error", error=describe_exception(log_err))
        raise


async def compute_and_store_data_completeness(client: httpx.AsyncClient, pool: Any) -> int:
    """Compute data completeness and store results."""
    started_at = datetime.now(UTC)
    try:
        # Full sequential scans whose duration varies widely (~230s warm, over
        # 600s on bad days). The endpoint caches in Redis for 6h, so only the
        # cold path is slow — see ENDPOINT_READ_TIMEOUTS for the budget.
        results = await _fetch_from_api(client, DATA_COMPLETENESS_PATH)
        if not results:
            await _log_computation(pool, "data_completeness", "completed", started_at, 0)
            return 0

        async with pool.connection() as conn:
            await conn.set_autocommit(False)
            async with conn.transaction(), conn.cursor() as cursor:
                cursor = cast("Any", cursor)
                await cursor.execute("DELETE FROM insights.data_completeness")
                for row in results:
                    await cursor.execute(
                        """
                            INSERT INTO insights.data_completeness
                                (entity_type, total_count, with_image, with_year,
                                 with_country, with_genre, completeness_pct)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                        (
                            row["entity_type"],
                            row["total_count"],
                            row["with_image"],
                            row["with_year"],
                            row["with_country"],
                            row["with_genre"],
                            row["completeness_pct"],
                        ),
                    )
        logger.info("💾 Data completeness stored", count=len(results))
        await _log_computation(pool, "data_completeness", "completed", started_at, len(results))
        return len(results)
    except Exception as e:
        logger.error("❌ Data completeness computation failed", error=describe_exception(e))
        try:
            await _log_computation(pool, "data_completeness", "failed", started_at, error_message=describe_exception(e))
        except Exception as log_err:
            logger.warning("⚠️ Failed to log computation error", error=describe_exception(log_err))
        raise


async def compute_and_store_community_enrichment(client: httpx.AsyncClient, pool: Any) -> int:
    """Trigger community enrichment via the API internal endpoint."""
    started_at = datetime.now(UTC)
    try:
        path = COMMUNITY_ENRICHMENT_PATH
        response = await client.get(path, timeout=endpoint_timeout(path))
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        enriched = int(data.get("enriched", 0))
        logger.info("📊 Community enrichment complete", enriched=enriched)
        await _log_computation(pool, "community_enrichment", "completed", started_at, enriched)
        return enriched
    except Exception as e:
        logger.error("❌ Community enrichment failed", error=describe_exception(e))
        try:
            await _log_computation(pool, "community_enrichment", "failed", started_at, error_message=describe_exception(e))
        except Exception as log_err:
            logger.warning("⚠️ Failed to log computation error", error=describe_exception(log_err))
        raise


async def compute_and_store_rarity(client: httpx.AsyncClient, pool: Any) -> int:
    """Compute release rarity scores and store results."""
    started_at = datetime.now(UTC)
    try:
        # The API runs the rarity signal scans chunked and sequentially (to cap
        # transaction memory) — see ENDPOINT_READ_TIMEOUTS for the budget.
        results = await _fetch_from_api(client, RARITY_SCORES_PATH)
        if not results:
            logger.info("📊 No rarity score results to store")
            await _log_computation(pool, "release_rarity", "completed", started_at, 0)
            return 0

        async with pool.connection() as conn:
            await conn.set_autocommit(False)
            async with conn.transaction(), conn.cursor() as cursor:
                cursor = cast("Any", cursor)
                await cursor.execute("DELETE FROM insights.release_rarity")
                for row in results:
                    await cursor.execute(
                        """
                            INSERT INTO insights.release_rarity
                                (release_id, title, artist_name, year, rarity_score, tier,
                                 hidden_gem_score, pressing_scarcity, label_catalog,
                                 format_rarity, temporal_scarcity, graph_isolation,
                                 collection_prevalence)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                        (
                            row["release_id"],
                            row.get("title", ""),
                            row.get("artist_name", ""),
                            row.get("year"),
                            row["rarity_score"],
                            row["tier"],
                            row.get("hidden_gem_score"),
                            row.get("pressing_scarcity"),
                            row.get("label_catalog"),
                            row.get("format_rarity"),
                            row.get("temporal_scarcity"),
                            row.get("graph_isolation"),
                            row.get("collection_prevalence"),
                        ),
                    )
        logger.info("💾 Release rarity scores stored", count=len(results))
        await _log_computation(pool, "release_rarity", "completed", started_at, len(results))
        return len(results)
    except Exception as e:
        logger.error("❌ Release rarity computation failed", error=describe_exception(e))
        try:
            await _log_computation(pool, "release_rarity", "failed", started_at, error_message=describe_exception(e))
        except Exception as log_err:
            logger.warning("⚠️ Failed to log computation error", error=describe_exception(log_err))
        raise


async def run_all_computations(
    client: httpx.AsyncClient,
    pool: Any,
    *,
    milestone_years: list[int] | None = None,
) -> dict[str, int]:
    """Run all insight computations and return row counts per type."""
    logger.info("🔄 Starting all insight computations...")
    results: dict[str, int] = {}
    errors: dict[str, str] = {}

    computations: list[tuple[str, Callable[[], Coroutine[Any, Any, int]]]] = [
        ("artist_centrality", lambda: compute_and_store_artist_centrality(client, pool)),
        ("genre_trends", lambda: compute_and_store_genre_trends(client, pool)),
        ("label_longevity", lambda: compute_and_store_label_longevity(client, pool)),
        (
            "anniversaries",
            lambda: compute_and_store_anniversaries(client, pool, milestone_years=milestone_years),
        ),
        ("data_completeness", lambda: compute_and_store_data_completeness(client, pool)),
        ("community_enrichment", lambda: compute_and_store_community_enrichment(client, pool)),
        ("release_rarity", lambda: compute_and_store_rarity(client, pool)),
    ]

    for name, factory in computations:
        try:
            results[name] = await factory()
        except Exception as e:
            logger.error("❌ Computation failed — continuing with remaining computations", computation=name, error=describe_exception(e))
            errors[name] = describe_exception(e)

    total = sum(results.values())
    logger.info("✅ All insight computations complete", total_rows=total, breakdown=results, failed=list(errors.keys()) or None)
    return results

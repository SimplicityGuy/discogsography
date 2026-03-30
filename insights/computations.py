"""Computation orchestration for insights.

Each compute_and_store_* function:
1. Fetches raw query results from the API service over HTTP
2. Clears the previous results from the insights table
3. Inserts the new results
4. Returns the number of rows written
"""

from datetime import UTC, datetime
from typing import Any, cast

import httpx
import structlog


logger = structlog.get_logger(__name__)


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
    timeout: float | None = None,
) -> list[dict[str, Any]]:
    """Fetch computation data from the API service."""
    kwargs: dict[str, Any] = {}
    if params:
        kwargs["params"] = params
    if timeout is not None:
        kwargs["timeout"] = timeout
    response = await client.get(path, **kwargs)
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    items: list[dict[str, Any]] = data.get("items", [])
    return items


async def compute_and_store_artist_centrality(client: httpx.AsyncClient, pool: Any, limit: int = 100) -> int:
    """Compute artist centrality and store results."""
    started_at = datetime.now(UTC)
    try:
        results = await _fetch_from_api(client, "/api/internal/insights/artist-centrality", {"limit": limit})
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

        async with pool.connection() as conn, conn.cursor() as cursor:
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
        logger.error("❌ Artist centrality computation failed", error=str(e))
        try:
            await _log_computation(pool, "artist_centrality", "failed", started_at, error_message=str(e))
        except Exception as log_err:
            logger.warning("⚠️ Failed to log computation error", error=str(log_err))
        raise


async def compute_and_store_genre_trends(client: httpx.AsyncClient, pool: Any) -> int:
    """Compute genre trends and store results."""
    started_at = datetime.now(UTC)
    try:
        results = await _fetch_from_api(client, "/api/internal/insights/genre-trends")
        if not results:
            await _log_computation(pool, "genre_trends", "completed", started_at, 0)
            return 0

        async with pool.connection() as conn, conn.cursor() as cursor:
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
        logger.error("❌ Genre trends computation failed", error=str(e))
        try:
            await _log_computation(pool, "genre_trends", "failed", started_at, error_message=str(e))
        except Exception as log_err:
            logger.warning("⚠️ Failed to log computation error", error=str(log_err))
        raise


async def compute_and_store_label_longevity(client: httpx.AsyncClient, pool: Any, limit: int = 50) -> int:
    """Compute label longevity and store results."""
    started_at = datetime.now(UTC)
    try:
        results = await _fetch_from_api(client, "/api/internal/insights/label-longevity", {"limit": limit})
        if not results:
            await _log_computation(pool, "label_longevity", "completed", started_at, 0)
            return 0

        current_year = datetime.now(UTC).year
        async with pool.connection() as conn, conn.cursor() as cursor:
            cursor = cast("Any", cursor)
            await cursor.execute("DELETE FROM insights.label_longevity")
            for rank, row in enumerate(results, 1):
                still_active = row["last_year"] >= current_year - 2
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
        logger.error("❌ Label longevity computation failed", error=str(e))
        try:
            await _log_computation(pool, "label_longevity", "failed", started_at, error_message=str(e))
        except Exception as log_err:
            logger.warning("⚠️ Failed to log computation error", error=str(log_err))
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
            "/api/internal/insights/anniversaries",
            {"year": year, "month": month, "milestones": milestones_str},
        )
        if not results:
            await _log_computation(pool, "anniversaries", "completed", started_at, 0)
            return 0
        rows_written = 0
        async with pool.connection() as conn, conn.cursor() as cursor:
            cursor = cast("Any", cursor)
            await cursor.execute(
                "DELETE FROM insights.monthly_anniversaries WHERE computed_year = %s AND computed_month = %s",
                (year, month),
            )
            for row in results:
                anniversary = year - row["release_year"]
                if anniversary in milestone_years:
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
                        (row["master_id"], row["title"], row.get("artist_name"), row["release_year"], anniversary, month, year),
                    )
                    rows_written += 1
        logger.info("💾 Monthly anniversaries stored", count=rows_written, year=year, month=month)
        await _log_computation(pool, "anniversaries", "completed", started_at, rows_written)
        return rows_written
    except Exception as e:
        logger.error("❌ Anniversaries computation failed", error=str(e))
        try:
            await _log_computation(pool, "anniversaries", "failed", started_at, error_message=str(e))
        except Exception as log_err:
            logger.warning("⚠️ Failed to log computation error", error=str(log_err))
        raise


async def compute_and_store_data_completeness(client: httpx.AsyncClient, pool: Any) -> int:
    """Compute data completeness and store results."""
    started_at = datetime.now(UTC)
    try:
        # Data completeness does full sequential scans (~400s for releases table alone);
        # use a longer timeout than the client default to avoid ReadTimeout errors.
        results = await _fetch_from_api(client, "/api/internal/insights/data-completeness", timeout=600.0)
        if not results:
            await _log_computation(pool, "data_completeness", "completed", started_at, 0)
            return 0

        async with pool.connection() as conn, conn.cursor() as cursor:
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
        logger.error("❌ Data completeness computation failed", error=str(e))
        try:
            await _log_computation(pool, "data_completeness", "failed", started_at, error_message=str(e))
        except Exception as log_err:
            logger.warning("⚠️ Failed to log computation error", error=str(log_err))
        raise


async def compute_and_store_rarity(client: httpx.AsyncClient, pool: Any) -> int:
    """Compute release rarity scores and store results."""
    started_at = datetime.now(UTC)
    try:
        results = await _fetch_from_api(client, "/api/internal/insights/rarity-scores", timeout=600.0)
        if not results:
            logger.info("📊 No rarity score results to store")
            await _log_computation(pool, "release_rarity", "completed", started_at, 0)
            return 0

        async with pool.connection() as conn, conn.cursor() as cursor:
            cursor = cast("Any", cursor)
            await cursor.execute("DELETE FROM insights.release_rarity")
            for row in results:
                await cursor.execute(
                    """
                    INSERT INTO insights.release_rarity
                        (release_id, title, artist_name, year, rarity_score, tier,
                         hidden_gem_score, pressing_scarcity, label_catalog,
                         format_rarity, temporal_scarcity, graph_isolation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    ),
                )
        logger.info("💾 Release rarity scores stored", count=len(results))
        await _log_computation(pool, "release_rarity", "completed", started_at, len(results))
        return len(results)
    except Exception as e:
        logger.error("❌ Release rarity computation failed", error=str(e))
        try:
            await _log_computation(pool, "release_rarity", "failed", started_at, error_message=str(e))
        except Exception as log_err:
            logger.warning("⚠️ Failed to log computation error", error=str(log_err))
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

    results["artist_centrality"] = await compute_and_store_artist_centrality(client, pool)
    results["genre_trends"] = await compute_and_store_genre_trends(client, pool)
    results["label_longevity"] = await compute_and_store_label_longevity(client, pool)
    results["anniversaries"] = await compute_and_store_anniversaries(
        client,
        pool,
        milestone_years=milestone_years,
    )
    results["data_completeness"] = await compute_and_store_data_completeness(client, pool)
    results["release_rarity"] = await compute_and_store_rarity(client, pool)

    total = sum(results.values())
    logger.info("✅ All insight computations complete", total_rows=total, breakdown=results)
    return results

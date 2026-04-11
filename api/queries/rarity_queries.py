"""Rarity scoring queries and computation logic.

Computes a 5-signal rarity index (0-100) for releases using Neo4j graph data,
and provides PostgreSQL lookup functions for precomputed scores.

Graph model:
  (Release)-[:BY]->(Artist)
  (Release)-[:ON]->(Label)
  (Release)-[:IS]->(Genre)
  (Release)-[:IS]->(Style)
  (Release)-[:DERIVED_FROM]->(Master)
"""

import asyncio
import bisect
from datetime import UTC, datetime
from typing import Any

from psycopg.rows import dict_row
import structlog

from api.queries.helpers import run_query


logger = structlog.get_logger(__name__)

# ── Signal weights (must sum to 1.0) ────────────────────────────────

SIGNAL_WEIGHTS: dict[str, float] = {
    "pressing_scarcity": 0.25,
    "label_catalog": 0.10,
    "format_rarity": 0.10,
    "temporal_scarcity": 0.20,
    "graph_isolation": 0.15,
    "collection_prevalence": 0.20,
}

# ── Format rarity lookup ────────────────────────────────────────────

FORMAT_RARITY_SCORES: dict[str, float] = {
    "Test Pressing": 100.0,
    "Lathe Cut": 98.0,
    "Flexi-disc": 95.0,
    "Shellac": 90.0,
    "Blu-spec CD": 80.0,
    "Box Set": 70.0,
    '10"': 65.0,
    "8-Track Cartridge": 60.0,
    "CDr": 50.0,
    "Vinyl": 40.0,
    "Cassette": 35.0,
    "LP": 30.0,
    "CD": 10.0,
    "File": 5.0,
}

_DEFAULT_FORMAT_SCORE = 50.0

# ── Rarity tiers ────────────────────────────────────────────────────

RARITY_TIERS: list[tuple[float, str]] = [
    (80.0, "ultra-rare"),
    (60.0, "rare"),
    (40.0, "scarce"),
    (20.0, "uncommon"),
    (0.0, "common"),
]


# ── Pure scoring functions ──────────────────────────────────────────


def compute_pressing_scarcity_score(pressing_count: int) -> float:
    """Score based on number of pressings of the same master."""
    if pressing_count <= 0:
        return 90.0  # Standalone release (no master link)
    if pressing_count == 1:
        return 100.0
    if pressing_count == 2:
        return 85.0
    if pressing_count <= 5:
        return 60.0
    if pressing_count <= 10:
        return 35.0
    return 10.0


def compute_label_catalog_score(catalog_size: int) -> float:
    """Score based on label catalog size (smaller = rarer)."""
    if catalog_size < 10:
        return 100.0
    if catalog_size <= 50:
        return 75.0
    if catalog_size <= 200:
        return 50.0
    if catalog_size <= 1000:
        return 25.0
    return 10.0


def compute_format_rarity_score(formats: list[Any]) -> float:
    """Score based on rarest format. Takes max across all formats."""
    if not formats:
        return _DEFAULT_FORMAT_SCORE
    scores = [FORMAT_RARITY_SCORES.get(str(f), _DEFAULT_FORMAT_SCORE) for f in formats if f is not None]
    return max(scores) if scores else _DEFAULT_FORMAT_SCORE


def compute_temporal_scarcity_score(
    release_year: int | None,
    latest_sibling_year: int | None,
    current_year: int,
) -> float:
    """Score based on age and reissue status."""
    if release_year is None:
        return 50.0
    age = current_year - release_year
    base = min(100.0, age * 1.5)
    if latest_sibling_year is not None and latest_sibling_year >= current_year - 10:
        base = max(0.0, base - 40.0)
    return base


def compute_graph_isolation_score(degree: int) -> float:
    """Score based on graph node degree (fewer connections = rarer)."""
    if degree <= 2:
        return 90.0
    if degree <= 4:
        return 70.0
    if degree <= 7:
        return 50.0
    if degree <= 12:
        return 30.0
    return 10.0


def compute_collection_prevalence_score(have_count: int, want_count: int) -> float:
    """Score based on community ownership rarity (inverse of prevalence).

    Uses log-scale thresholds since community counts follow power-law distribution.
    Want > have adds a +5 bonus (capped at 100) indicating scarcity pressure.
    """
    if have_count <= 0:
        base = 95.0
    elif have_count <= 10:
        base = 85.0
    elif have_count <= 100:
        base = 70.0
    elif have_count <= 1000:
        base = 50.0
    elif have_count <= 10000:
        base = 25.0
    else:
        base = 10.0

    if want_count > have_count:
        base = min(100.0, base + 5.0)

    return base


def compute_rarity_tier(score: float) -> str:
    """Map composite score to rarity tier label."""
    for threshold, tier in RARITY_TIERS:
        if score >= threshold:
            return tier
    return "common"


# ── Neo4j batch signal queries ──────────────────────────────────────


async def fetch_all_rarity_signals(driver: Any) -> list[dict[str, Any]]:
    """Fetch all rarity signals from Neo4j and compute scores.

    Executes 8 batch Cypher queries (5 signal queries + 3 quality queries),
    joins by release_id, and computes composite rarity + hidden gem scores.

    Returns a list of dicts ready for PostgreSQL insertion.
    """
    current_year = datetime.now(UTC).year

    # 1. Pressing scarcity: count siblings per master
    pressing_query = """
    MATCH (r:Release)
    OPTIONAL MATCH (r)-[:DERIVED_FROM]->(m:Master)<-[:DERIVED_FROM]-(sibling:Release)
    WHERE sibling <> r
    WITH r, m, count(DISTINCT sibling) + 1 AS pressing_count_with_master
    WITH r, CASE WHEN m IS NULL THEN 0 ELSE pressing_count_with_master END AS pressing_count
    OPTIONAL MATCH (r)-[:BY]->(a:Artist)
    WITH r, pressing_count, collect(DISTINCT a.name)[0] AS artist_name
    RETURN r.id AS release_id, pressing_count,
           r.title AS title, artist_name, r.year AS year
    """

    # 2. Label catalog size per release
    label_query = """
    MATCH (r:Release)-[:ON]->(l:Label)
    WITH r.id AS release_id, min(COALESCE(l.release_count, 0)) AS label_catalog_size
    RETURN release_id, label_catalog_size
    """

    # 3. Formats per release
    format_query = """
    MATCH (r:Release)
    WHERE r.formats IS NOT NULL
    RETURN r.id AS release_id, r.formats AS formats
    """

    # 4. Temporal: release year + latest sibling year
    temporal_query = """
    MATCH (r:Release)
    OPTIONAL MATCH (r)-[:DERIVED_FROM]->(m:Master)<-[:DERIVED_FROM]-(sibling:Release)
    WHERE sibling.year IS NOT NULL AND sibling <> r
    WITH r.id AS release_id, r.year AS year,
         max(sibling.year) AS latest_sibling_year
    RETURN release_id, year, latest_sibling_year
    """

    # 5. Graph degree per release
    degree_query = """
    MATCH (r:Release)
    WITH r, size([(r)-[]-() | 1]) AS degree
    RETURN r.id AS release_id, degree
    """

    # Quality signals for hidden gem scoring
    # 6. Max artist degree per release
    artist_degree_query = """
    MATCH (r:Release)-[:BY]->(a:Artist)
    WITH r.id AS release_id, max(size([(a)-[]-() | 1])) AS artist_max_degree
    RETURN release_id, artist_max_degree
    """

    # 7. Max label catalog size per release
    label_size_query = """
    MATCH (r:Release)-[:ON]->(l:Label)
    WITH r.id AS release_id, max(COALESCE(l.release_count, 0)) AS label_max_catalog
    RETURN release_id, label_max_catalog
    """

    # 8. Max genre release count per release
    genre_count_query = """
    MATCH (r:Release)-[:IS]->(g:Genre)
    WITH r.id AS release_id, max(COALESCE(g.release_count, 0)) AS genre_max_release_count
    RETURN release_id, genre_max_release_count
    """

    logger.info("🔍 Fetching rarity signals from Neo4j...")

    (
        pressing_rows,
        label_rows,
        format_rows,
        temporal_rows,
        degree_rows,
        artist_degree_rows,
        label_size_rows,
        genre_count_rows,
    ) = await asyncio.gather(
        run_query(driver, pressing_query, database="neo4j"),
        run_query(driver, label_query, database="neo4j"),
        run_query(driver, format_query, database="neo4j"),
        run_query(driver, temporal_query, database="neo4j"),
        run_query(driver, degree_query, database="neo4j"),
        run_query(driver, artist_degree_query, database="neo4j"),
        run_query(driver, label_size_query, database="neo4j"),
        run_query(driver, genre_count_query, database="neo4j"),
    )

    logger.info(
        "📊 Rarity signal data fetched",
        releases=len(pressing_rows),
        labels=len(label_rows),
        formats=len(format_rows),
    )

    # Build lookup dicts keyed by release_id
    label_map = {r["release_id"]: r["label_catalog_size"] for r in label_rows}
    format_map = {r["release_id"]: r["formats"] for r in format_rows}
    temporal_map = {r["release_id"]: r for r in temporal_rows}
    degree_map = {r["release_id"]: r["degree"] for r in degree_rows}
    artist_deg_map = {r["release_id"]: r["artist_max_degree"] for r in artist_degree_rows}
    label_size_map = {r["release_id"]: r["label_max_catalog"] for r in label_size_rows}
    genre_count_map = {r["release_id"]: r["genre_max_release_count"] for r in genre_count_rows}

    # Compute percentile normalization for quality signals
    all_artist_degrees = sorted(r["artist_max_degree"] for r in artist_degree_rows if r["artist_max_degree"])
    all_label_sizes = sorted(r["label_max_catalog"] for r in label_size_rows if r["label_max_catalog"])
    all_genre_counts = sorted(r["genre_max_release_count"] for r in genre_count_rows if r["genre_max_release_count"])

    def _percentile_rank(value: float, sorted_values: list[float]) -> float:
        """Return percentile rank (0.0 to 1.0) of value in sorted list."""
        if not sorted_values or value <= 0:
            return 0.0
        return bisect.bisect_left(sorted_values, value) / len(sorted_values)

    # Score each release
    results: list[dict[str, Any]] = []
    for row in pressing_rows:
        rid = row["release_id"]

        pressing_score = compute_pressing_scarcity_score(row["pressing_count"])
        label_score = compute_label_catalog_score(label_map.get(rid, 0))
        fmt_score = compute_format_rarity_score(format_map.get(rid, []))

        temporal_info = temporal_map.get(rid, {})
        temporal_score = compute_temporal_scarcity_score(
            temporal_info.get("year"),
            temporal_info.get("latest_sibling_year"),
            current_year,
        )

        isolation_score = compute_graph_isolation_score(degree_map.get(rid, 0))

        rarity_score = (
            SIGNAL_WEIGHTS["pressing_scarcity"] * pressing_score
            + SIGNAL_WEIGHTS["label_catalog"] * label_score
            + SIGNAL_WEIGHTS["format_rarity"] * fmt_score
            + SIGNAL_WEIGHTS["temporal_scarcity"] * temporal_score
            + SIGNAL_WEIGHTS["graph_isolation"] * isolation_score
        )

        tier = compute_rarity_tier(rarity_score)

        # Hidden gem: quality multiplier from artist/label/genre prominence
        artist_deg = artist_deg_map.get(rid, 0) or 0
        label_sz = label_size_map.get(rid, 0) or 0
        genre_ct = genre_count_map.get(rid, 0) or 0

        quality_multiplier = (
            0.4 * _percentile_rank(artist_deg, all_artist_degrees)
            + 0.3 * _percentile_rank(label_sz, all_label_sizes)
            + 0.3 * _percentile_rank(genre_ct, all_genre_counts)
        )

        hidden_gem_score = round(rarity_score * quality_multiplier, 1)

        results.append(
            {
                "release_id": rid,
                "title": row.get("title") or "",
                "artist_name": row.get("artist_name") or "",
                "year": row.get("year"),
                "rarity_score": round(rarity_score, 1),
                "tier": tier,
                "hidden_gem_score": hidden_gem_score,
                "pressing_scarcity": pressing_score,
                "label_catalog": label_score,
                "format_rarity": fmt_score,
                "temporal_scarcity": temporal_score,
                "graph_isolation": isolation_score,
            }
        )

    logger.info("✅ Rarity scores computed", total=len(results))
    return results


# ── PostgreSQL lookup functions ─────────────────────────────────────


async def get_rarity_for_release(pool: Any, release_id: int) -> dict[str, Any] | None:
    """Get precomputed rarity breakdown for a single release."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT release_id, title, artist_name, year, rarity_score, tier,
                   hidden_gem_score, pressing_scarcity, label_catalog,
                   format_rarity, temporal_scarcity, graph_isolation
            FROM insights.release_rarity
            WHERE release_id = %s
            """,
            (release_id,),
        )
        row: dict[str, Any] | None = await cur.fetchone()
        return row


async def get_rarity_leaderboard(
    pool: Any,
    page: int = 1,
    page_size: int = 20,
    tier: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Get paginated global rarity leaderboard."""
    offset = (page - 1) * page_size

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        if tier:
            await cur.execute(
                """
                SELECT release_id, title, artist_name, year, rarity_score, tier, hidden_gem_score
                FROM insights.release_rarity
                WHERE tier = %s
                ORDER BY rarity_score DESC
                LIMIT %s OFFSET %s
                """,
                (tier, page_size, offset),
            )
            items = await cur.fetchall()

            await cur.execute(
                "SELECT count(*) AS total FROM insights.release_rarity WHERE tier = %s",
                (tier,),
            )
        else:
            await cur.execute(
                """
                SELECT release_id, title, artist_name, year, rarity_score, tier, hidden_gem_score
                FROM insights.release_rarity
                ORDER BY rarity_score DESC
                LIMIT %s OFFSET %s
                """,
                (page_size, offset),
            )
            items = await cur.fetchall()

            await cur.execute(
                "SELECT count(*) AS total FROM insights.release_rarity",
            )

        count_row = await cur.fetchone()
        total = count_row["total"] if count_row else 0

    return items, total


async def get_rarity_hidden_gems(
    pool: Any,
    page: int = 1,
    page_size: int = 20,
    min_rarity: float = 41.0,
) -> tuple[list[dict[str, Any]], int]:
    """Get paginated hidden gems sorted by hidden_gem_score."""
    offset = (page - 1) * page_size

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT release_id, title, artist_name, year, rarity_score, tier, hidden_gem_score
            FROM insights.release_rarity
            WHERE rarity_score >= %s AND hidden_gem_score IS NOT NULL
            ORDER BY hidden_gem_score DESC
            LIMIT %s OFFSET %s
            """,
            (min_rarity, page_size, offset),
        )
        items = await cur.fetchall()

        await cur.execute(
            "SELECT count(*) AS total FROM insights.release_rarity WHERE rarity_score >= %s AND hidden_gem_score IS NOT NULL",
            (min_rarity,),
        )
        count_row = await cur.fetchone()
        total = count_row["total"] if count_row else 0

    return items, total


async def get_rarity_by_artist(
    driver: Any,
    pool: Any,
    artist_id: str,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int] | None:
    """Get rarest releases by a specific artist.

    First queries Neo4j for release_ids, then fetches from PostgreSQL.
    Returns None if artist not found.
    """
    artist_rows = await run_query(
        driver,
        "MATCH (a:Artist {id: $artist_id}) RETURN a.id AS id, a.name AS name LIMIT 1",
        database="neo4j",
        artist_id=artist_id,
    )
    if not artist_rows:
        return None

    release_rows = await run_query(
        driver,
        "MATCH (a:Artist {id: $artist_id})<-[:BY]-(r:Release) RETURN r.id AS release_id",
        database="neo4j",
        artist_id=artist_id,
    )
    if not release_rows:
        return [], 0

    release_ids = [int(r["release_id"]) for r in release_rows if str(r["release_id"]).isdigit()]
    if not release_ids:
        return [], 0
    offset = (page - 1) * page_size

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT release_id, title, artist_name, year, rarity_score, tier, hidden_gem_score
            FROM insights.release_rarity
            WHERE release_id = ANY(%s)
            ORDER BY rarity_score DESC
            LIMIT %s OFFSET %s
            """,
            (release_ids, page_size, offset),
        )
        items = await cur.fetchall()

        await cur.execute(
            "SELECT count(*) AS total FROM insights.release_rarity WHERE release_id = ANY(%s)",
            (release_ids,),
        )
        count_row = await cur.fetchone()
        total = count_row["total"] if count_row else 0

    return items, total


async def get_rarity_by_label(
    driver: Any,
    pool: Any,
    label_id: str,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int] | None:
    """Get rarest releases on a specific label.

    First queries Neo4j for release_ids, then fetches from PostgreSQL.
    Returns None if label not found.
    """
    label_rows = await run_query(
        driver,
        "MATCH (l:Label {id: $label_id}) RETURN l.id AS id, l.name AS name LIMIT 1",
        database="neo4j",
        label_id=label_id,
    )
    if not label_rows:
        return None

    release_rows = await run_query(
        driver,
        "MATCH (l:Label {id: $label_id})<-[:ON]-(r:Release) RETURN r.id AS release_id",
        database="neo4j",
        label_id=label_id,
    )
    if not release_rows:
        return [], 0

    release_ids = [int(r["release_id"]) for r in release_rows if str(r["release_id"]).isdigit()]
    if not release_ids:
        return [], 0
    offset = (page - 1) * page_size

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT release_id, title, artist_name, year, rarity_score, tier, hidden_gem_score
            FROM insights.release_rarity
            WHERE release_id = ANY(%s)
            ORDER BY rarity_score DESC
            LIMIT %s OFFSET %s
            """,
            (release_ids, page_size, offset),
        )
        items = await cur.fetchall()

        await cur.execute(
            "SELECT count(*) AS total FROM insights.release_rarity WHERE release_id = ANY(%s)",
            (release_ids,),
        )
        count_row = await cur.fetchone()
        total = count_row["total"] if count_row else 0

    return items, total

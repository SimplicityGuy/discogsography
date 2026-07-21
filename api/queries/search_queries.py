"""PostgreSQL full-text search queries for /api/search.

Entity tables all have schema:
    data_id  VARCHAR PRIMARY KEY
    data     JSONB NOT NULL

Name fields: artists/labels → data->>'name', masters/releases → data->>'title'
Genres field (JSONB array): releases.data->'genres'
Year field (text): masters/releases.data->>'year'

Runs 5 concurrent queries per uncached search:
  1. Paginated results
  2. Total result count (unfiltered by pagination)
  3. Per-type counts for facets
  4. Genre facets (from releases matching query)
  5. Decade facets (from masters + releases matching query)
"""

import asyncio
import contextlib
import hashlib
import json
from typing import Any

from psycopg import sql
from psycopg.rows import dict_row
import structlog

from common import AsyncPostgreSQLPool
from common.query_debug import execute_sql


logger = structlog.get_logger(__name__)

ALL_TYPES: list[str] = ["artist", "label", "master", "release"]

# Search cache TTL (1 hour — longer than the old 5 min to reduce cold cache
# frequency for high-cardinality terms like "Rock" that take ~9s to compute)
_SEARCH_CACHE_TTL = 3600

# Maps entity type → (table, name_field, has_year, has_genres)
_ENTITY_CONFIG: dict[str, tuple[str, str, bool, bool]] = {
    "artist": ("artists", "name", False, False),
    "label": ("labels", "name", False, False),
    "master": ("masters", "title", True, False),
    "release": ("releases", "title", True, True),
}


def cache_key(q: str, types: list[str], genres: list[str], year_min: int | None, year_max: int | None, limit: int, offset: int) -> str:
    """Stable Redis cache key for the given search parameters."""
    params = {
        "q": q.lower().strip(),
        "types": sorted(types),
        "genres": sorted(genres),
        "year_min": year_min,
        "year_max": year_max,
        "limit": limit,
        "offset": offset,
    }
    digest = hashlib.md5(json.dumps(params, sort_keys=True).encode(), usedforsecurity=False).hexdigest()
    return f"search:{digest}"


def _year_filter_clause(year_min: int | None, year_max: int | None, column: sql.Composable | None = None) -> tuple[sql.Composable, list[Any]]:
    """Return (SQL_clause, params) for optional year filtering.

    Rows with NULL year (artists, labels) are always included regardless of
    year filter — only rows with a parseable year are filtered.

    ``column`` lets callers point the clause at a raw column expression (e.g.
    ``(data->>'year')``) instead of the default ``year`` identifier — needed
    to push the filter into a per-table subquery *before* its rank LIMIT.
    """
    col = column if column is not None else sql.SQL("year")
    clauses: list[sql.Composable] = []
    params: list[Any] = []
    if year_min is not None:
        clauses.append(sql.SQL("({c} IS NULL OR {c}::int >= %s)").format(c=col))
        params.append(year_min)
    if year_max is not None:
        clauses.append(sql.SQL("({c} IS NULL OR {c}::int <= %s)").format(c=col))
        params.append(year_max)
    return (sql.SQL(" AND ").join(clauses), params) if clauses else (sql.SQL("TRUE"), [])


def _genre_filter_clause(genres: list[str], column: sql.Composable | None = None) -> tuple[sql.Composable, list[Any]]:
    """Return (SQL_clause, params) for optional genre filtering.

    Rows with NULL genres (artists, labels, masters) are always included
    regardless of genre filter — only rows with genre data are filtered.

    ``column`` lets callers point the clause at a raw column expression (e.g.
    ``(data->'genres')``) instead of the default ``genres`` identifier —
    needed to push the filter into a per-table subquery *before* its rank
    LIMIT.
    """
    if not genres:
        return (sql.SQL("TRUE"), [])
    col = column if column is not None else sql.SQL("genres")
    # ?| checks if JSONB array contains any of the given strings
    return (sql.SQL("({c} IS NULL OR {c} ?| %s::text[])").format(c=col), [genres])


def _entity_select(
    entity_type: str,
    name_field: str,
    has_year: bool,
    has_genres: bool,
    *,
    per_table_limit: int | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    genres: list[str] | None = None,
) -> tuple[sql.Composable, list[Any]]:
    """Return a (SELECT fragment, params) for one entity type in the UNION ALL.

    When per_table_limit is set, each entity type returns at most that many
    rows (ordered by ts_rank DESC).  This prevents high-cardinality terms
    like "Rock" from materializing 100K+ rows in the UNION ALL CTE.

    year_min/year_max/genres — when given — are applied INSIDE this subquery's
    WHERE, before its ORDER BY rank LIMIT, so the rank cap is applied to
    already-filtered rows. Applying them only in an outer WHERE (after the
    cap) would silently drop/empty filtered results for high-cardinality
    terms, since rank is uncorrelated with year/genre.
    """
    year_col = sql.SQL("(data->>'year')") if has_year else sql.SQL("NULL::text")
    genres_col = sql.SQL("(data->'genres')") if has_genres else sql.SQL("NULL::jsonb")
    table = sql.Identifier(_ENTITY_CONFIG[entity_type][0])
    name_lit = sql.Literal(name_field)
    # data_id is a unique tiebreaker so the per-table rank cap selects a
    # deterministic subset among tied ts_rank values across page executions.
    limit_clause = sql.SQL(" ORDER BY rank DESC, data_id LIMIT {n}").format(n=sql.Literal(per_table_limit)) if per_table_limit else sql.SQL("")

    year_clause, year_params = _year_filter_clause(year_min, year_max, column=year_col)
    genre_clause, genre_params = _genre_filter_clause(genres or [], column=genres_col)
    filter_params = [*year_params, *genre_params]
    filter_clause = sql.SQL(" AND {y} AND {g}").format(y=year_clause, g=genre_clause) if filter_params else sql.SQL("")

    select_sql = sql.SQL(
        "(SELECT {entity_type}::text AS type, data_id AS id, data->>{name} AS name,"
        " ts_rank(to_tsvector('english', COALESCE(data->>{name}, '')), q.tsq) AS rank,"
        " ts_headline('english', COALESCE(data->>{name}, ''), q.tsq) AS highlight,"
        " {year_col} AS year, {genres_col} AS genres"
        " FROM {table}, q"
        " WHERE to_tsvector('english', COALESCE(data->>{name}, '')) @@ q.tsq"
        "{filter_clause}"
        "{limit_clause})"
    ).format(
        entity_type=sql.Literal(entity_type),
        name=name_lit,
        year_col=year_col,
        genres_col=genres_col,
        table=table,
        filter_clause=filter_clause,
        limit_clause=limit_clause,
    )
    return select_sql, filter_params


def _build_union(
    types: list[str],
    *,
    per_table_limit: int | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    genres: list[str] | None = None,
) -> tuple[sql.Composable, list[Any]]:
    """Build UNION ALL of SELECT fragments for the requested entity types.

    When per_table_limit is set, each entity type returns at most that many
    rows (pre-sorted by rank), preventing high-cardinality term explosion.
    year_min/year_max/genres are pushed into each per-table subquery so the
    rank cap is applied to already-filtered rows (see _entity_select).

    Returns (UNION_ALL SQL fragment, flattened params list in emission order).
    """
    if not types:  # would produce invalid SQL
        raise ValueError("types must not be empty")
    parts: list[sql.Composable] = []
    params: list[Any] = []
    for t in types:
        _table, name_field, has_year, has_genres = _ENTITY_CONFIG[t]
        select_sql, select_params = _entity_select(
            t,
            name_field,
            has_year,
            has_genres,
            per_table_limit=per_table_limit,
            year_min=year_min,
            year_max=year_max,
            genres=genres,
        )
        parts.append(select_sql)
        params.extend(select_params)
    return sql.SQL(" UNION ALL ").join(parts), params


async def _run_results(
    pool: AsyncPostgreSQLPool,
    q: str,
    types: list[str],
    genres: list[str],
    year_min: int | None,
    year_max: int | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    """Fetch paginated search results.

    Uses per-table LIMIT in the UNION ALL to prevent high-cardinality terms
    like "Rock" from materializing 100K+ rows before outer LIMIT/OFFSET.
    Each table returns at most (limit + offset) rows pre-sorted by rank.

    year/genre filters are pushed INTO each per-table subquery (before its
    rank LIMIT) — applying them only in an outer WHERE after the per-table
    cap would silently drop/empty filtered results for high-cardinality
    terms, since rank is uncorrelated with year/genre.
    """
    # Each entity table returns up to per_table_limit rows pre-sorted by rank.
    # Use 2x multiplier to reduce result loss at higher page offsets while
    # keeping the materialisation bounded.
    per_table_limit = (limit + offset) * 2
    union_sql, union_params = _build_union(types, per_table_limit=per_table_limit, year_min=year_min, year_max=year_max, genres=genres)

    query = sql.SQL(
        "WITH q AS (SELECT plainto_tsquery('english', %s) AS tsq),"
        " results AS ({union_sql})"
        " SELECT type, id, name, rank, highlight, year, genres"
        " FROM results"
        " ORDER BY rank DESC, id"
        " LIMIT %s OFFSET %s"
    ).format(union_sql=union_sql)
    params = [q, *union_params, limit, offset]
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, query, params)  # nosemgrep
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


_TOTAL_COUNT_CAP = 10000


async def _run_total(
    pool: AsyncPostgreSQLPool,
    q: str,
    types: list[str],
    genres: list[str],
    year_min: int | None,
    year_max: int | None,
) -> int:
    """Count total matching results (ignoring pagination).

    Each table is capped at _TOTAL_COUNT_CAP rows to prevent full scans
    on high-cardinality terms like "Rock" (18.9M releases).  The reported
    total is an approximate lower bound when capped.

    year/genre filters are pushed INTO each per-table subquery (before its
    rank LIMIT) for the same reason as _run_results — see its docstring.
    """
    union_sql, union_params = _build_union(types, per_table_limit=_TOTAL_COUNT_CAP, year_min=year_min, year_max=year_max, genres=genres)

    query = sql.SQL(
        "WITH q AS (SELECT plainto_tsquery('english', %s) AS tsq), results AS ({union_sql}) SELECT COUNT(*) AS total FROM results"
    ).format(union_sql=union_sql)
    params = [q, *union_params]
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, query, params)  # nosemgrep
        row = await cur.fetchone()
    return int(row["total"]) if row else 0


async def _run_type_counts(pool: AsyncPostgreSQLPool, q: str, types: list[str]) -> dict[str, int]:
    """Count matching records per entity type (for type facet).

    Each table count is capped at _TOTAL_COUNT_CAP to prevent full scans
    on common terms.  Reported counts are approximate when capped.
    """
    union_parts = []
    for t in types:
        table, name_field, _, _ = _ENTITY_CONFIG[t]
        union_parts.append(
            sql.SQL(
                "SELECT {type}::text AS type,"
                " (SELECT COUNT(*) FROM (SELECT 1 FROM {table}, q"
                " WHERE to_tsvector('english', COALESCE(data->>{name}, '')) @@ q.tsq"
                " LIMIT {cap}) sub) AS cnt"
            ).format(
                type=sql.Literal(t),
                table=sql.Identifier(table),
                name=sql.Literal(name_field),
                cap=sql.Literal(_TOTAL_COUNT_CAP),
            )
        )
    union_sql = sql.SQL(" UNION ALL ").join(union_parts)
    query = sql.SQL("WITH q AS (SELECT plainto_tsquery('english', %s) AS tsq) {union_sql}").format(union_sql=union_sql)
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, query, [q])  # nosemgrep
        rows = await cur.fetchall()
    return {row["type"]: int(row["cnt"]) for row in rows}


async def _run_genre_facets(pool: AsyncPostgreSQLPool, q: str) -> dict[str, int]:
    """Count matching releases per genre (for genre facet).

    Caps the release scan to prevent full table traversal on common terms.
    """
    query = sql.SQL(
        "WITH q AS (SELECT plainto_tsquery('english', %s) AS tsq),"
        " matched AS ("
        " SELECT data->'genres' AS genres FROM releases, q"
        " WHERE to_tsvector('english', COALESCE(data->>'title', '')) @@ q.tsq"
        " LIMIT {cap})"
        " SELECT genre, COUNT(*) AS cnt"
        " FROM matched,"
        " jsonb_array_elements_text(genres) AS genre"
        " GROUP BY genre"
        " ORDER BY cnt DESC"
        " LIMIT 20"
    ).format(cap=sql.Literal(_TOTAL_COUNT_CAP))
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, query, [q])
        rows = await cur.fetchall()
    return {row["genre"]: int(row["cnt"]) for row in rows}


async def _run_decade_facets(pool: AsyncPostgreSQLPool, q: str) -> dict[str, int]:
    """Count matching masters+releases per decade (for decade facet).

    Caps each table scan to prevent full traversal on common terms.
    """
    query = sql.SQL(
        "WITH q AS (SELECT plainto_tsquery('english', %s) AS tsq),"
        " matches AS ("
        " (SELECT data->>'year' AS year FROM masters, q"
        " WHERE to_tsvector('english', COALESCE(data->>'title', '')) @@ q.tsq"
        " AND data->>'year' IS NOT NULL"
        " LIMIT {cap})"
        " UNION ALL"
        " (SELECT data->>'year' FROM releases, q"
        " WHERE to_tsvector('english', COALESCE(data->>'title', '')) @@ q.tsq"
        " AND data->>'year' IS NOT NULL"
        " LIMIT {cap}))"
        " SELECT (year::int / 10 * 10)::text || 's' AS decade, COUNT(*) AS cnt"
        " FROM matches"
        " WHERE year ~ '^[0-9]{{4}}$'"
        " GROUP BY decade"
        " ORDER BY decade"
    ).format(cap=sql.Literal(_TOTAL_COUNT_CAP))
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, query, [q])
        rows = await cur.fetchall()
    return {row["decade"]: int(row["cnt"]) for row in rows}


def _format_result(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a DB row into the API result shape."""
    metadata: dict[str, Any] = {}
    if row.get("year"):
        with contextlib.suppress(ValueError, TypeError):
            metadata["year"] = int(row["year"])
    if row.get("genres"):
        genres = row["genres"]
        if isinstance(genres, list):
            metadata["genres"] = genres
    return {
        "type": row["type"],
        "id": row["id"],
        "name": row["name"] or "",
        "highlight": row["highlight"] or row["name"] or "",
        "relevance": round(float(row["rank"]), 4) if row.get("rank") else 0.0,
        "metadata": metadata,
    }


async def execute_search(
    pool: AsyncPostgreSQLPool,
    redis: Any | None,
    q: str,
    types: list[str],
    genres: list[str],
    year_min: int | None,
    year_max: int | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Run full search and return structured response dict.

    Checks Redis cache first (TTL=300s). On miss, runs 5 DB queries
    concurrently, formats response, stores in Redis, and returns.
    """
    if not types:
        raise ValueError("types must not be empty")

    key = cache_key(q, types, genres, year_min, year_max, limit, offset)

    # Cache-aside read — Redis is a pure optimization. A Redis outage (or a
    # corrupt cache entry) must degrade to a fresh PostgreSQL query, never 500.
    if redis is not None:
        try:
            cached = await redis.get(key)
            if cached:
                return json.loads(cached)  # type: ignore[no-any-return]
        except Exception:
            logger.debug("⚠️ Search cache read failed, falling through to DB", key=key)

    logger.debug("🔍 Search cache miss, querying DB", q=q, types=types)

    results_rows, total, type_counts, genre_facets, decade_facets = await asyncio.gather(
        _run_results(pool, q, types, genres, year_min, year_max, limit, offset),
        _run_total(pool, q, types, genres, year_min, year_max),
        _run_type_counts(pool, q, types),
        _run_genre_facets(pool, q),
        _run_decade_facets(pool, q),
    )

    response: dict[str, Any] = {
        "query": q,
        "total": total,
        "facets": {
            "type": type_counts,
            "genre": genre_facets,
            "decade": decade_facets,
        },
        "results": [_format_result(r) for r in results_rows],
        "pagination": {
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(results_rows) < total,
        },
    }

    # Best-effort cache write — a Redis outage must not fail an otherwise
    # successful, fully PostgreSQL-backed search response.
    if redis is not None:
        try:
            await redis.setex(key, _SEARCH_CACHE_TTL, json.dumps(response))
        except Exception:
            logger.debug("⚠️ Search cache write failed", key=key)

    return response

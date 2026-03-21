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


def _entity_select(entity_type: str, name_field: str, has_year: bool, has_genres: bool, *, per_table_limit: int | None = None) -> sql.Composable:
    """Return a SELECT fragment for one entity type in the UNION ALL.

    When per_table_limit is set, each entity type returns at most that many
    rows (ordered by ts_rank DESC).  This prevents high-cardinality terms
    like "Rock" from materializing 100K+ rows in the UNION ALL CTE.
    """
    year_col = sql.SQL("(data->>'year')") if has_year else sql.SQL("NULL::text")
    genres_col = sql.SQL("(data->'genres')") if has_genres else sql.SQL("NULL::jsonb")
    table = sql.Identifier(_ENTITY_CONFIG[entity_type][0])
    name_lit = sql.Literal(name_field)
    limit_clause = sql.SQL(" ORDER BY rank DESC LIMIT {n}").format(n=sql.Literal(per_table_limit)) if per_table_limit else sql.SQL("")
    return sql.SQL(
        "(SELECT {entity_type}::text AS type, data_id AS id, data->>{name} AS name,"
        " ts_rank(to_tsvector('english', COALESCE(data->>{name}, '')), q.tsq) AS rank,"
        " ts_headline('english', COALESCE(data->>{name}, ''), q.tsq) AS highlight,"
        " {year_col} AS year, {genres_col} AS genres"
        " FROM {table}, q"
        " WHERE to_tsvector('english', COALESCE(data->>{name}, '')) @@ q.tsq"
        "{limit_clause})"
    ).format(
        entity_type=sql.Literal(entity_type),
        name=name_lit,
        year_col=year_col,
        genres_col=genres_col,
        table=table,
        limit_clause=limit_clause,
    )


def _build_union(types: list[str], *, per_table_limit: int | None = None) -> sql.Composable:
    """Build UNION ALL of SELECT fragments for the requested entity types.

    When per_table_limit is set, each entity type returns at most that many
    rows (pre-sorted by rank), preventing high-cardinality term explosion.
    """
    if not types:  # would produce invalid SQL
        raise ValueError("types must not be empty")
    parts = []
    for t in types:
        _table, name_field, has_year, has_genres = _ENTITY_CONFIG[t]
        parts.append(_entity_select(t, name_field, has_year, has_genres, per_table_limit=per_table_limit))
    return sql.SQL(" UNION ALL ").join(parts)


def _year_filter_clause(year_min: int | None, year_max: int | None) -> tuple[sql.Composable, list[Any]]:
    """Return (SQL_clause, params) for optional year filtering.

    Rows with NULL year (artists, labels) are always included regardless of
    year filter — only rows with a parseable year are filtered.
    """
    clauses: list[sql.Composable] = []
    params: list[Any] = []
    if year_min is not None:
        clauses.append(sql.SQL("(year IS NULL OR year::int >= %s)"))
        params.append(year_min)
    if year_max is not None:
        clauses.append(sql.SQL("(year IS NULL OR year::int <= %s)"))
        params.append(year_max)
    return (sql.SQL(" AND ").join(clauses), params) if clauses else (sql.SQL("TRUE"), [])


def _genre_filter_clause(genres: list[str]) -> tuple[sql.Composable, list[Any]]:
    """Return (SQL_clause, params) for optional genre filtering.

    Rows with NULL genres (artists, labels, masters) are always included
    regardless of genre filter — only rows with genre data are filtered.
    """
    if not genres:
        return (sql.SQL("TRUE"), [])
    # ?| checks if JSONB array contains any of the given strings
    return (sql.SQL("(genres IS NULL OR genres ?| %s::text[])"), [genres])


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
    """
    per_table_limit = limit + offset
    union_sql = _build_union(types, per_table_limit=per_table_limit)
    year_clause, year_params = _year_filter_clause(year_min, year_max)
    genre_clause, genre_params = _genre_filter_clause(genres)

    query = sql.SQL(
        "WITH q AS (SELECT plainto_tsquery('english', %s) AS tsq),"
        " results AS ({union_sql})"
        " SELECT type, id, name, rank, highlight, year, genres"
        " FROM results"
        " WHERE {year_clause} AND {genre_clause}"
        " ORDER BY rank DESC"
        " LIMIT %s OFFSET %s"
    ).format(
        union_sql=union_sql,
        year_clause=year_clause,
        genre_clause=genre_clause,
    )
    params = [q, *year_params, *genre_params, limit, offset]
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, query, params)  # nosemgrep
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def _run_total(
    pool: AsyncPostgreSQLPool,
    q: str,
    types: list[str],
    genres: list[str],
    year_min: int | None,
    year_max: int | None,
) -> int:
    """Count total matching results (ignoring pagination)."""
    union_sql = _build_union(types)
    year_clause, year_params = _year_filter_clause(year_min, year_max)
    genre_clause, genre_params = _genre_filter_clause(genres)

    query = sql.SQL(
        "WITH q AS (SELECT plainto_tsquery('english', %s) AS tsq),"
        " results AS ({union_sql})"
        " SELECT COUNT(*) AS total FROM results"
        " WHERE {year_clause} AND {genre_clause}"
    ).format(
        union_sql=union_sql,
        year_clause=year_clause,
        genre_clause=genre_clause,
    )
    params = [q, *year_params, *genre_params]
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, query, params)  # nosemgrep
        row = await cur.fetchone()
    return int(row["total"]) if row else 0


async def _run_type_counts(pool: AsyncPostgreSQLPool, q: str, types: list[str]) -> dict[str, int]:
    """Count matching records per entity type (for type facet)."""
    union_parts = []
    for t in types:
        table, name_field, _, _ = _ENTITY_CONFIG[t]
        union_parts.append(
            sql.SQL(
                "SELECT {type}::text AS type, COUNT(*) AS cnt"
                " FROM {table}, q"
                " WHERE to_tsvector('english', COALESCE(data->>{name}, '')) @@ q.tsq"
                " GROUP BY type"
            ).format(
                type=sql.Literal(t),
                table=sql.Identifier(table),
                name=sql.Literal(name_field),
            )
        )
    union_sql = sql.SQL(" UNION ALL ").join(union_parts)
    query = sql.SQL("WITH q AS (SELECT plainto_tsquery('english', %s) AS tsq) {union_sql}").format(union_sql=union_sql)
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, query, [q])  # nosemgrep
        rows = await cur.fetchall()
    return {row["type"]: int(row["cnt"]) for row in rows}


async def _run_genre_facets(pool: AsyncPostgreSQLPool, q: str) -> dict[str, int]:
    """Count matching releases per genre (for genre facet)."""
    query = sql.SQL(
        "WITH q AS (SELECT plainto_tsquery('english', %s) AS tsq)"
        " SELECT genre, COUNT(*) AS cnt"
        " FROM releases, q,"
        " jsonb_array_elements_text(data->'genres') AS genre"
        " WHERE to_tsvector('english', COALESCE(data->>'title', '')) @@ q.tsq"
        " GROUP BY genre"
        " ORDER BY cnt DESC"
        " LIMIT 20"
    )
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, query, [q])
        rows = await cur.fetchall()
    return {row["genre"]: int(row["cnt"]) for row in rows}


async def _run_decade_facets(pool: AsyncPostgreSQLPool, q: str) -> dict[str, int]:
    """Count matching masters+releases per decade (for decade facet)."""
    query = sql.SQL(
        "WITH q AS (SELECT plainto_tsquery('english', %s) AS tsq),"
        " matches AS ("
        " SELECT data->>'year' AS year FROM masters, q"
        " WHERE to_tsvector('english', COALESCE(data->>'title', '')) @@ q.tsq"
        " AND data->>'year' IS NOT NULL"
        " UNION ALL"
        " SELECT data->>'year' FROM releases, q"
        " WHERE to_tsvector('english', COALESCE(data->>'title', '')) @@ q.tsq"
        " AND data->>'year' IS NOT NULL"
        ")"
        " SELECT (year::int / 10 * 10)::text || 's' AS decade, COUNT(*) AS cnt"
        " FROM matches"
        " WHERE year ~ '^[0-9]{{4}}$'"
        " GROUP BY decade"
        " ORDER BY decade"
    )
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

    if redis is not None:
        cached = await redis.get(key)
        if cached:
            return json.loads(cached)  # type: ignore[no-any-return]

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

    if redis is not None:
        await redis.setex(key, 300, json.dumps(response))

    return response

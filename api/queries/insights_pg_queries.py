"""PostgreSQL queries for insights computations.

Each function takes an AsyncPostgreSQLPool, executes queries against
the Discogs entity tables, and returns typed results.

All SQL queries are pre-built as string constants from a hardcoded
allowlist of table names and JSONB keys — no user input is interpolated.
"""

from typing import Any, cast

import structlog


logger = structlog.get_logger(__name__)

# Allowlisted table names — only these are used in queries.
_ALLOWED_TABLES = frozenset({"artists", "labels", "masters", "releases"})

# Fields to check for completeness, per entity type.
_COMPLETENESS_FIELDS: dict[str, list[tuple[str, str]]] = {
    "artists": [("with_image", "images")],
    "labels": [("with_image", "images")],
    "masters": [("with_year", "year"), ("with_genre", "genres"), ("with_image", "images")],
    "releases": [
        ("with_year", "year"),
        ("with_country", "country"),
        ("with_genre", "genres"),
        ("with_image", "images"),
    ],
}

# Pre-built SQL queries from hardcoded allowlist — no runtime interpolation.
_COUNT_QUERIES: dict[str, str] = {
    table: f"SELECT count(*) FROM {table}"  # noqa: S608
    for table in _ALLOWED_TABLES
}

_FIELD_QUERIES: dict[str, dict[str, str]] = {}
for _table, _fields in _COMPLETENESS_FIELDS.items():
    _FIELD_QUERIES[_table] = {}
    for _field_name, _jsonb_key in _fields:
        _FIELD_QUERIES[_table][_field_name] = (
            f"SELECT count(*) FROM {_table} WHERE data->>'{_jsonb_key}' IS NOT NULL AND data->>'{_jsonb_key}' != '' AND data->>'{_jsonb_key}' != '[]'"  # noqa: S608
        )


async def query_data_completeness(pool: Any) -> list[dict[str, Any]]:
    """Compute data completeness scores for each entity type.

    For each entity table, counts total records and how many have
    non-null/non-empty values for key metadata fields.
    """
    results: list[dict[str, Any]] = []

    async with pool.connection() as conn, conn.cursor() as cursor:
        cursor = cast("Any", cursor)

        for entity_type, fields in _COMPLETENESS_FIELDS.items():
            # Get total count using pre-built query
            await cursor.execute(_COUNT_QUERIES[entity_type])
            row = await cursor.fetchall()
            total_count = row[0][0] if row else 0

            item: dict[str, Any] = {
                "entity_type": entity_type,
                "total_count": total_count,
                "with_image": 0,
                "with_year": 0,
                "with_country": 0,
                "with_genre": 0,
            }

            if total_count > 0:
                for field_name, _ in fields:
                    # Use pre-built query from allowlist
                    await cursor.execute(_FIELD_QUERIES[entity_type][field_name])
                    field_row = await cursor.fetchall()
                    item[field_name] = field_row[0][0] if field_row else 0

                field_pcts = []
                for field_name, _ in fields:
                    field_pcts.append(item[field_name] / total_count * 100)
                item["completeness_pct"] = round(sum(field_pcts) / len(field_pcts), 2) if field_pcts else 0.0
            else:
                item["completeness_pct"] = 0.0

            results.append(item)

    logger.info("🔍 Data completeness query complete", entity_count=len(results))
    return results

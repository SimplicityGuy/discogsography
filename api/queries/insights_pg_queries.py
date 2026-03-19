"""PostgreSQL queries for insights computations.

Each function takes an AsyncPostgreSQLPool, executes queries against
the Discogs entity tables, and returns typed results.

All SQL queries are pre-built as string constants from a hardcoded
allowlist of table names and JSONB keys — no user input is interpolated.
"""

from typing import Any, cast

import structlog


logger = structlog.get_logger(__name__)

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

# Pre-built combined queries per entity type — single table scan each.
# Uses count(*) FILTER to compute all field counts in one pass.
_COMBINED_QUERIES: dict[str, str] = {}
for _table, _fields in _COMPLETENESS_FIELDS.items():
    _filter_parts = []
    _aliases = []
    for _field_name, _jsonb_key in _fields:
        _filter_parts.append(
            f"count(*) FILTER (WHERE data->>'{_jsonb_key}' IS NOT NULL"
            f" AND data->>'{_jsonb_key}' != ''"
            f" AND data->>'{_jsonb_key}' != '[]') AS {_field_name}"
        )
        _aliases.append(_field_name)
    _filters_sql = ", ".join(_filter_parts)
    _COMBINED_QUERIES[_table] = f"SELECT count(*) AS total_count, {_filters_sql} FROM {_table}"  # noqa: S608


async def query_data_completeness(pool: Any) -> list[dict[str, Any]]:
    """Compute data completeness scores for each entity type.

    For each entity table, counts total records and how many have
    non-null/non-empty values for key metadata fields in a single
    table scan using FILTER clauses.
    """
    results: list[dict[str, Any]] = []

    async with pool.connection() as conn, conn.cursor() as cursor:
        cursor = cast("Any", cursor)

        for entity_type, fields in _COMPLETENESS_FIELDS.items():
            await cursor.execute(_COMBINED_QUERIES[entity_type])
            row = await cursor.fetchone()

            total_count = row[0] if row else 0
            item: dict[str, Any] = {
                "entity_type": entity_type,
                "total_count": total_count,
                "with_image": 0,
                "with_year": 0,
                "with_country": 0,
                "with_genre": 0,
            }

            if total_count > 0 and row:
                for i, (field_name, _) in enumerate(fields):
                    item[field_name] = row[i + 1]

                field_pcts = [item[field_name] / total_count * 100 for field_name, _ in fields]
                item["completeness_pct"] = round(sum(field_pcts) / len(field_pcts), 2) if field_pcts else 0.0
            else:
                item["completeness_pct"] = 0.0

            results.append(item)

    logger.info("🔍 Data completeness query complete", entity_count=len(results))
    return results

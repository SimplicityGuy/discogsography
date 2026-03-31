"""Query functions for MusicBrainz enrichment data."""

from typing import Any

from psycopg import sql
from psycopg.rows import dict_row

from api.queries.helpers import run_query, run_single
from common.query_debug import execute_sql


async def get_artist_musicbrainz(neo4j_driver: Any, discogs_id: int | str) -> dict[str, Any] | None:
    """Fetch MusicBrainz metadata for a Discogs artist from Neo4j."""
    row = await run_single(
        neo4j_driver,
        """MATCH (a:Artist {id: $discogs_id})
           WHERE a.mbid IS NOT NULL
           RETURN a.mbid AS mbid, a.mb_type AS type, a.mb_gender AS gender,
                  a.mb_begin_date AS begin_date, a.mb_end_date AS end_date,
                  a.mb_area AS area, a.mb_begin_area AS begin_area,
                  a.mb_disambiguation AS disambiguation""",
        discogs_id=discogs_id,
    )
    if not row:
        return None
    return {
        "discogs_id": discogs_id,
        "mbid": row["mbid"],
        "type": row["type"],
        "gender": row["gender"],
        "begin_date": row["begin_date"],
        "end_date": row["end_date"],
        "area": row["area"],
        "begin_area": row["begin_area"],
        "disambiguation": row["disambiguation"],
    }


async def get_artist_mb_relationships(neo4j_driver: Any, discogs_id: int | str) -> list[dict[str, Any]]:
    """Fetch MusicBrainz-sourced relationships for a Discogs artist from Neo4j."""
    return await run_query(
        neo4j_driver,
        """MATCH (a:Artist {id: $discogs_id})-[r]->(target:Artist)
           WHERE r.source = 'musicbrainz'
           RETURN type(r) AS type, target.id AS target_id, target.name AS target_name,
                  'outgoing' AS direction, r.begin_date AS begin_date,
                  r.end_date AS end_date, r.attributes AS attributes
           UNION ALL
           MATCH (source:Artist)-[r]->(a:Artist {id: $discogs_id})
           WHERE r.source = 'musicbrainz'
           RETURN type(r) AS type, source.id AS target_id, source.name AS target_name,
                  'incoming' AS direction, r.begin_date AS begin_date,
                  r.end_date AS end_date, r.attributes AS attributes""",
        discogs_id=discogs_id,
    )


async def get_artist_external_links(pool: Any, discogs_id: int) -> list[dict[str, Any]]:
    """Fetch external links for a Discogs artist from PostgreSQL."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            """SELECT el.service_name AS service, el.url
               FROM musicbrainz.external_links el
               JOIN musicbrainz.artists a ON a.mbid = el.mbid
               WHERE a.discogs_artist_id = %s AND el.entity_type = 'artist'
               ORDER BY el.service_name""",
            (discogs_id,),
        )
        rows: list[dict[str, Any]] = await cur.fetchall()
        return rows


async def get_enrichment_status(pool: Any, neo4j_driver: Any) -> dict[str, Any]:
    """Fetch enrichment coverage statistics from both databases."""
    stats: dict[str, Any] = {"musicbrainz": {}}

    # PostgreSQL counts
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        for entity in ["artists", "labels", "releases"]:
            if entity == "releases":
                discogs_col = "discogs_release_id"
            elif entity == "artists":
                discogs_col = "discogs_artist_id"
            else:
                discogs_col = "discogs_label_id"

            # Safe: entity and discogs_col are from hardcoded lists, not user input.
            # Using sql.Identifier for defense-in-depth.
            total_query = sql.SQL(  # nosemgrep
                "SELECT COUNT(*) AS total FROM {schema}.{table}"
            ).format(schema=sql.Identifier("musicbrainz"), table=sql.Identifier(entity))
            await cur.execute(total_query)  # nosemgrep
            total_row = await cur.fetchone()
            total = total_row["total"] if total_row else 0

            matched_query = sql.SQL(  # nosemgrep
                "SELECT COUNT(*) AS matched FROM {schema}.{table} WHERE {col} IS NOT NULL"
            ).format(schema=sql.Identifier("musicbrainz"), table=sql.Identifier(entity), col=sql.Identifier(discogs_col))
            await cur.execute(matched_query)  # nosemgrep
            matched_row = await cur.fetchone()
            matched = matched_row["matched"] if matched_row else 0

            stats["musicbrainz"][entity] = {"total_mb": total, "matched_to_discogs": matched}

        await execute_sql(cur, "SELECT COUNT(*) AS total FROM musicbrainz.relationships")
        rel_row = await cur.fetchone()
        stats["musicbrainz"]["relationships"] = {"total_in_mb": rel_row["total"] if rel_row else 0}

    # Neo4j enrichment counts
    for entity, label in [("artists", "Artist"), ("labels", "Label"), ("releases", "Release")]:
        row = await run_single(
            neo4j_driver,
            f"MATCH (n:{label}) WHERE n.mbid IS NOT NULL RETURN COUNT(n) AS total",  # nosemgrep
        )
        stats["musicbrainz"][entity]["enriched_in_neo4j"] = row["total"] if row else 0

    row = await run_single(
        neo4j_driver,
        "MATCH ()-[r]->() WHERE r.source = 'musicbrainz' RETURN COUNT(r) AS total",
    )
    stats["musicbrainz"]["relationships"]["created_in_neo4j"] = row["total"] if row else 0

    return stats

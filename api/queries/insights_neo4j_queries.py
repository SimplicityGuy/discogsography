"""Neo4j Cypher queries for insights computations.

Each function takes an AsyncResilientNeo4jDriver (or compatible async driver),
executes a Cypher query, and returns a list of dicts.
"""

from typing import Any

import structlog

from api.queries.helpers import run_query


logger = structlog.get_logger(__name__)


async def query_artist_centrality(driver: Any, limit: int = 100) -> list[dict[str, Any]]:
    """Query top artists by total edge count (degree centrality).

    Counts all relationships connected to each Artist node:
    releases, labels, aliases, groups, and collaborations.
    """
    cypher = """
    MATCH (a:Artist)
    WITH a, size([(a)-[]-() | 1]) AS edge_count
    ORDER BY edge_count DESC
    LIMIT $limit
    RETURN a.id AS artist_id, a.name AS artist_name, edge_count
    """
    results = await run_query(driver, cypher, database="neo4j", limit=limit)
    logger.info("🔍 Artist centrality query complete", count=len(results))
    return results


async def query_genre_trends(driver: Any, genre: str | None = None) -> list[dict[str, Any]]:
    """Query release counts per genre per decade.

    Groups releases by their genres and the decade of release,
    counting how many releases fall into each genre/decade bucket.
    """
    if genre:
        cypher = """
        MATCH (r:Release)-[:IS]->(g:Genre {name: $genre})
        WHERE r.year IS NOT NULL AND r.year > 0
        WITH g.name AS genre, (r.year / 10) * 10 AS decade, count(r) AS release_count
        ORDER BY decade
        RETURN genre, decade, release_count
        """
        results = await run_query(driver, cypher, database="neo4j", genre=genre)
    else:
        cypher = """
        MATCH (r:Release)-[:IS]->(g:Genre)
        WHERE r.year IS NOT NULL AND r.year > 0
        WITH g.name AS genre, (r.year / 10) * 10 AS decade, count(r) AS release_count
        ORDER BY genre, decade
        RETURN genre, decade, release_count
        """
        results = await run_query(driver, cypher, database="neo4j")
    logger.info("🔍 Genre trends query complete", count=len(results), genre=genre)
    return results


async def query_label_longevity(driver: Any, limit: int = 50) -> list[dict[str, Any]]:
    """Query labels ranked by years of active operation.

    For each label, finds the earliest and latest release year,
    calculates years active, total releases, and peak decade.
    """
    cypher = """
    MATCH (r:Release)-[:ON]->(l:Label)
    WHERE r.year IS NOT NULL AND r.year > 0
    WITH l,
         min(r.year) AS first_year,
         max(r.year) AS last_year,
         count(r) AS total_releases,
         collect(r.year) AS years
    WITH l, first_year, last_year, total_releases, years,
         last_year - first_year + 1 AS years_active
    UNWIND years AS y
    WITH l, first_year, last_year, total_releases, years_active,
         (y / 10) * 10 AS decade, count(*) AS decade_count
    ORDER BY decade_count DESC
    WITH l, first_year, last_year, total_releases, years_active,
         collect({decade: decade, count: decade_count})[0].decade AS peak_decade
    ORDER BY years_active DESC
    LIMIT $limit
    RETURN l.id AS label_id, l.name AS label_name,
           first_year, last_year, years_active,
           total_releases, peak_decade
    """
    results = await run_query(driver, cypher, database="neo4j", limit=limit)
    logger.info("🔍 Label longevity query complete", count=len(results))
    return results


async def query_monthly_anniversaries(
    driver: Any,
    current_year: int,
    current_month: int,
    milestone_years: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Query releases with notable anniversaries this month.

    Finds Master releases whose release year creates a milestone
    anniversary (25, 30, 40, 50, 75, 100 years) in the current year.
    """
    if milestone_years is None:
        milestone_years = [25, 30, 40, 50, 75, 100]

    target_years = [current_year - m for m in milestone_years]

    cypher = """
    UNWIND $target_years AS target_year
    MATCH (m:Master {year: target_year})
    OPTIONAL MATCH (r:Release)-[:DERIVED_FROM]->(m)
    OPTIONAL MATCH (r)-[:BY]->(a:Artist)
    WITH m, collect(DISTINCT a.name)[0] AS artist_name
    RETURN m.id AS master_id, m.title AS title, artist_name,
           m.year AS release_year
    ORDER BY m.year ASC
    """
    results = await run_query(driver, cypher, database="neo4j", target_years=target_years)
    logger.info(
        "🔍 Monthly anniversaries query complete",
        count=len(results),
        month=current_month,
        year=current_year,
    )
    return results

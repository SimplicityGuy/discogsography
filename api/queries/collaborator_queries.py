"""Neo4j Cypher queries for the Collaborators endpoint.

Finds artists who share releases with a given artist, along with
temporal collaboration data (yearly counts, first/last year).
"""

from typing import Any

from api.queries.helpers import run_count, run_query, run_single
from common import AsyncResilientNeo4jDriver


async def get_artist_identity(driver: AsyncResilientNeo4jDriver, artist_id: str) -> dict[str, Any] | None:
    """Get basic artist info (id, name) for existence check."""
    cypher = """
    MATCH (a:Artist {id: $artist_id})
    RETURN a.id AS artist_id, a.name AS artist_name
    """
    return await run_single(driver, cypher, artist_id=artist_id)


async def get_collaborators(driver: AsyncResilientNeo4jDriver, artist_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Get collaborating artists with release counts and yearly breakdown."""
    cypher = """
    MATCH (r:Release)-[:BY]->(a:Artist {id: $artist_id}),
          (r)-[:BY]->(other:Artist)
    WHERE other.id <> $artist_id AND r.year > 0
    WITH other, r.year AS year, count(DISTINCT r) AS year_count
    ORDER BY other.id, year
    WITH other,
         sum(year_count) AS release_count,
         min(year) AS first_year,
         max(year) AS last_year,
         collect({year: year, count: year_count}) AS yearly_counts
    ORDER BY release_count DESC
    LIMIT $limit
    RETURN other.id AS artist_id, other.name AS artist_name,
           release_count, first_year, last_year, yearly_counts
    """
    return await run_query(driver, cypher, artist_id=artist_id, limit=limit)


async def count_collaborators(driver: AsyncResilientNeo4jDriver, artist_id: str) -> int:
    """Count total distinct collaborators for an artist."""
    cypher = """
    MATCH (r:Release)-[:BY]->(a:Artist {id: $artist_id}),
          (r)-[:BY]->(other:Artist)
    WHERE other.id <> $artist_id AND r.year > 0
    RETURN count(DISTINCT other) AS total
    """
    return await run_count(driver, cypher, artist_id=artist_id)

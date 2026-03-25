"""Neo4j Cypher queries for the Genre Tree endpoint.

Derives a genre/style hierarchy from release co-occurrence — each genre
contains the styles that appear on releases tagged with that genre.
"""

from typing import Any

from api.queries.helpers import run_query
from common import AsyncResilientNeo4jDriver


_GENRE_TREE_CYPHER = """
MATCH (r:Release)-[:IS]->(g:Genre)
WITH g.name AS genre, count(DISTINCT r) AS genre_count
ORDER BY genre_count DESC
WITH collect({name: genre, count: genre_count}) AS genres
UNWIND genres AS gi
OPTIONAL MATCH (r2:Release)-[:IS]->(g2:Genre {name: gi.name}),
               (r2)-[:IS]->(s:Style)
WITH gi, s.name AS style, count(DISTINCT r2) AS style_count
ORDER BY gi.name, style_count DESC
WITH gi,
     CASE WHEN style IS NOT NULL
       THEN collect({name: style, release_count: style_count})
       ELSE [] END AS styles
RETURN gi.name AS name, gi.count AS release_count, styles
ORDER BY gi.count DESC
"""


async def get_genre_tree(driver: AsyncResilientNeo4jDriver) -> list[dict[str, Any]]:
    """Return the full genre tree with nested styles.

    Each row contains ``name``, ``release_count``, and ``styles`` (a list of
    dicts with ``name`` and ``release_count``).
    """
    return await run_query(driver, _GENRE_TREE_CYPHER, timeout=30.0)

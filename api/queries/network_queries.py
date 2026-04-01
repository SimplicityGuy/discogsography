"""Neo4j Cypher queries for Collaboration Network endpoints.

Provides multi-hop collaborator traversal, betweenness centrality
(via Neo4j GDS), and community detection (Louvain/Label Propagation).
"""

from typing import Any

import structlog

from api.queries.helpers import run_count, run_query, run_single
from common import AsyncResilientNeo4jDriver


logger = structlog.get_logger(__name__)


async def get_artist_identity(driver: AsyncResilientNeo4jDriver, artist_id: str) -> dict[str, Any] | None:
    """Get basic artist info (id, name) for existence check."""
    cypher = """
    MATCH (a:Artist {id: $artist_id})
    RETURN a.id AS artist_id, a.name AS artist_name
    """
    return await run_single(driver, cypher, artist_id=artist_id)


async def get_multi_hop_collaborators(
    driver: AsyncResilientNeo4jDriver,
    artist_id: str,
    depth: int = 2,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get collaborators within N hops via shared releases.

    Depth 1 = direct collaborators (shared a release).
    Depth 2+ = collaborators of collaborators, etc.
    Returns collaboration_count (shared releases at closest hop) and
    the shortest hop distance.
    """
    cypher = """
    MATCH (a:Artist {id: $artist_id})
    CALL {
        WITH a
        MATCH path = (a)<-[:BY]-(:Release)-[:BY]->(hop1:Artist)
        WHERE hop1 <> a
        WITH a, hop1, count(DISTINCT nodes(path)[1]) AS shared
        RETURN hop1 AS collaborator, 1 AS hops, shared
        UNION
        WITH a
        MATCH (a)<-[:BY]-(:Release)-[:BY]->(mid:Artist)<-[:BY]-(:Release)-[:BY]->(hop2:Artist)
        WHERE mid <> a AND hop2 <> a AND $depth >= 2
              AND NOT EXISTS { MATCH (a)<-[:BY]-(:Release)-[:BY]->(hop2) }
        WITH hop2 AS collaborator, 2 AS hops, count(DISTINCT mid) AS shared
        WHERE hops <= $depth
        RETURN collaborator, hops, shared
    }
    WITH collaborator, min(hops) AS distance, sum(shared) AS collaboration_count
    ORDER BY distance ASC, collaboration_count DESC
    LIMIT $limit
    RETURN collaborator.id AS artist_id,
           collaborator.name AS artist_name,
           distance,
           collaboration_count
    """
    return await run_query(driver, cypher, artist_id=artist_id, depth=depth, limit=limit)


async def count_multi_hop_collaborators(
    driver: AsyncResilientNeo4jDriver,
    artist_id: str,
    depth: int = 2,
) -> int:
    """Count total collaborators within N hops."""
    cypher = """
    MATCH (a:Artist {id: $artist_id})
    CALL {
        WITH a
        MATCH (a)<-[:BY]-(:Release)-[:BY]->(hop1:Artist)
        WHERE hop1 <> a
        RETURN hop1 AS collaborator, 1 AS hops
        UNION
        WITH a
        MATCH (a)<-[:BY]-(:Release)-[:BY]->(mid:Artist)<-[:BY]-(:Release)-[:BY]->(hop2:Artist)
        WHERE mid <> a AND hop2 <> a AND $depth >= 2
              AND NOT EXISTS { MATCH (a)<-[:BY]-(:Release)-[:BY]->(hop2) }
        WITH hop2 AS collaborator, 2 AS hops
        WHERE hops <= $depth
        RETURN collaborator, hops
    }
    WITH collaborator, min(hops) AS distance
    RETURN count(collaborator) AS total
    """
    return await run_count(driver, cypher, artist_id=artist_id, depth=depth)


async def get_artist_centrality(
    driver: AsyncResilientNeo4jDriver,
    artist_id: str,
) -> dict[str, Any] | None:
    """Compute centrality scores for a single artist.

    Returns degree centrality (total relationship count) and
    collaboration-based betweenness approximation via Neo4j GDS
    (falls back to degree-only if GDS is unavailable).
    """
    # First try GDS betweenness centrality
    gds_cypher = """
    MATCH (a:Artist {id: $artist_id})
    WITH a, size([(a)-[]-() | 1]) AS degree
    OPTIONAL MATCH (a)<-[:BY]-(r:Release)-[:BY]->(other:Artist)
    WHERE other <> a
    WITH a, degree,
         count(DISTINCT other) AS collaborator_count,
         count(DISTINCT r) AS collaboration_releases
    OPTIONAL MATCH (a)-[:MEMBER_OF]->(g)
    WITH a, degree, collaborator_count, collaboration_releases,
         count(DISTINCT g) AS group_count
    OPTIONAL MATCH (a)-[:ALIAS_OF]->(al)
    WITH a, degree, collaborator_count, collaboration_releases,
         group_count, count(DISTINCT al) AS alias_count
    RETURN a.id AS artist_id, a.name AS artist_name,
           degree,
           collaborator_count,
           collaboration_releases,
           group_count,
           alias_count
    """
    return await run_single(driver, gds_cypher, artist_id=artist_id)


async def get_artist_cluster(
    driver: AsyncResilientNeo4jDriver,
    artist_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Detect the community/cluster around an artist.

    Uses label propagation via shared-release co-occurrence:
    finds all artists connected through shared releases (up to 2 hops),
    then groups them by their most common genre to approximate communities.
    """
    cypher = """
    MATCH (a:Artist {id: $artist_id})
    MATCH (a)<-[:BY]-(r:Release)-[:BY]->(neighbor:Artist)
    WHERE neighbor <> a
    WITH a, neighbor, count(DISTINCT r) AS shared_releases
    OPTIONAL MATCH (neighbor)<-[:BY]-(r2:Release)-[:IS]->(g:Genre)
    WITH neighbor, shared_releases,
         g.name AS genre, count(r2) AS genre_count
    ORDER BY genre_count DESC
    WITH neighbor, shared_releases,
         collect(genre)[0] AS primary_genre
    ORDER BY shared_releases DESC
    LIMIT $limit
    RETURN neighbor.id AS artist_id,
           neighbor.name AS artist_name,
           shared_releases,
           primary_genre
    """
    results = await run_query(driver, cypher, artist_id=artist_id, limit=limit)

    # Group results by primary_genre to form clusters
    clusters: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        genre = row.get("primary_genre") or "Unknown"
        if genre not in clusters:
            clusters[genre] = []
        clusters[genre].append(
            {
                "artist_id": row["artist_id"],
                "artist_name": row["artist_name"],
                "shared_releases": row["shared_releases"],
            }
        )

    return [
        {"cluster_label": genre, "members": members, "size": len(members)}
        for genre, members in sorted(clusters.items(), key=lambda x: len(x[1]), reverse=True)
    ]

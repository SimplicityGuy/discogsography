"""Neo4j Cypher queries for Label DNA fingerprinting.

Computes multi-dimensional fingerprints for record labels from graph data:
genre/style profiles, era distribution, artist diversity, format preference,
and label-to-label similarity via cosine similarity on genre vectors.
"""

from typing import Any

from api.queries.helpers import run_query, run_single
from api.queries.similarity import cosine_similarity, to_genre_vector
from common import AsyncResilientNeo4jDriver


# Minimum releases for a label to have a meaningful fingerprint
MIN_RELEASES = 5


async def get_label_identity(driver: AsyncResilientNeo4jDriver, label_id: str) -> dict[str, Any] | None:
    """Get basic label info and release/artist counts.

    Single traversal from label to releases, with OPTIONAL MATCH for artists.
    """
    cypher = """
    MATCH (l:Label {id: $label_id})
    OPTIONAL MATCH (l)<-[:ON]-(r:Release)
    OPTIONAL MATCH (r)-[:BY]->(a:Artist)
    RETURN l.id AS label_id, l.name AS label_name,
           count(DISTINCT r) AS release_count,
           count(DISTINCT a) AS artist_count
    """
    return await run_single(driver, cypher, label_id=label_id)


async def get_label_genre_profile(driver: AsyncResilientNeo4jDriver, label_id: str) -> list[dict[str, Any]]:
    """Get genre distribution for a label's releases."""
    cypher = """
    MATCH (r:Release)-[:ON]->(l:Label {id: $label_id}), (r)-[:IS]->(g:Genre)
    WITH g.name AS name, count(DISTINCT r) AS count
    RETURN name, count
    ORDER BY count DESC
    """
    return await run_query(driver, cypher, label_id=label_id)


async def get_label_style_profile(driver: AsyncResilientNeo4jDriver, label_id: str) -> list[dict[str, Any]]:
    """Get style distribution for a label's releases."""
    cypher = """
    MATCH (r:Release)-[:ON]->(l:Label {id: $label_id}), (r)-[:IS]->(s:Style)
    WITH s.name AS name, count(DISTINCT r) AS count
    RETURN name, count
    ORDER BY count DESC
    """
    return await run_query(driver, cypher, label_id=label_id)


async def get_label_decade_profile(driver: AsyncResilientNeo4jDriver, label_id: str) -> list[dict[str, Any]]:
    """Get release count by decade for a label."""
    cypher = """
    MATCH (r:Release)-[:ON]->(l:Label {id: $label_id})
    WHERE r.year > 0
    WITH (r.year / 10) * 10 AS decade, count(DISTINCT r) AS count
    RETURN decade, count
    ORDER BY decade
    """
    return await run_query(driver, cypher, label_id=label_id)


async def get_label_active_years(driver: AsyncResilientNeo4jDriver, label_id: str) -> list[int]:
    """Get sorted list of years in which a label had releases."""
    cypher = """
    MATCH (r:Release)-[:ON]->(l:Label {id: $label_id})
    WHERE r.year > 0
    RETURN DISTINCT r.year AS year
    ORDER BY year
    """
    rows = await run_query(driver, cypher, label_id=label_id)
    return [row["year"] for row in rows]


async def get_label_format_profile(driver: AsyncResilientNeo4jDriver, label_id: str) -> list[dict[str, Any]]:
    """Get format distribution for a label's releases."""
    cypher = """
    MATCH (r:Release)-[:ON]->(l:Label {id: $label_id})
    WHERE r.formats IS NOT NULL
    UNWIND r.formats AS fmt
    WITH fmt AS name, count(DISTINCT r) AS count
    RETURN name, count
    ORDER BY count DESC
    """
    return await run_query(driver, cypher, label_id=label_id)


async def get_candidate_labels_genre_vectors(driver: AsyncResilientNeo4jDriver, label_id: str) -> list[dict[str, Any]]:
    """Get genre vectors for labels sharing genres with the target label.

    Returns each candidate label with its genre distribution,
    filtered to labels with at least MIN_RELEASES releases.

    Optimizations:
    - Limits genre expansion to the label's top 5 genres (avoids exploding
      through mega-genres like "Rock" / "Electronic" with millions of releases).
    - Two-phase approach: first find candidate IDs (fast), then batch-fetch
      genre profiles for the top 100 candidates only.
    - Timeout protection on each phase.
    """
    # Phase 1: Find candidate label IDs via genre overlap (top 5 genres only)
    candidates_cypher = """
    MATCH (l:Label {id: $label_id})<-[:ON]-(r:Release)-[:IS]->(g:Genre)
    WITH l, g, count(DISTINCT r) AS genre_count
    ORDER BY genre_count DESC
    LIMIT 5
    WITH l, collect(g.name) AS target_genres
    UNWIND target_genres AS genre_name
    MATCH (g2:Genre {name: genre_name})<-[:IS]-(r2:Release)-[:ON]->(l2:Label)
    WHERE l2 <> l
    WITH l2, count(DISTINCT r2) AS total_shared
    WHERE total_shared >= $min_releases
    RETURN l2.id AS label_id, l2.name AS label_name, total_shared
    ORDER BY total_shared DESC
    LIMIT 100
    """
    candidates = await run_query(
        driver,
        candidates_cypher,
        timeout=60,
        label_id=label_id,
        min_releases=MIN_RELEASES,
    )

    if not candidates:
        return []

    # Phase 2: Batch-fetch genre profiles + release counts for candidates
    candidate_ids = [c["label_id"] for c in candidates]
    profile_cypher = """
    UNWIND $label_ids AS lid
    MATCH (l:Label {id: lid})<-[:ON]-(r:Release)
    WITH l, count(DISTINCT r) AS release_count
    CALL {
        WITH l
        MATCH (l)<-[:ON]-(r2:Release)-[:IS]->(g:Genre)
        WITH g.name AS genre, count(DISTINCT r2) AS genre_count
        RETURN collect({name: genre, count: genre_count}) AS genres
    }
    RETURN l.id AS label_id, l.name AS label_name, release_count, genres
    """
    return await run_query(driver, profile_cypher, timeout=60, label_ids=candidate_ids)


def compute_similar_labels(
    target_genres: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Rank candidate labels by cosine similarity to the target's genre vector."""
    target_vec = to_genre_vector(target_genres)
    if not target_vec:
        return []

    target_genre_names = set(target_vec)
    results = []
    for candidate in candidates:
        cand_vec = to_genre_vector(candidate["genres"])
        sim = cosine_similarity(target_vec, cand_vec)
        if sim > 0.0:
            shared = sorted(set(cand_vec) & target_genre_names)
            results.append(
                {
                    "label_id": candidate["label_id"],
                    "label_name": candidate["label_name"],
                    "similarity": round(sim, 4),
                    "release_count": candidate["release_count"],
                    "shared_genres": shared,
                }
            )

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:limit]

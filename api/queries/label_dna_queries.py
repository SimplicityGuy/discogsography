"""Neo4j Cypher queries for Label DNA fingerprinting.

Computes multi-dimensional fingerprints for record labels from graph data:
genre/style profiles, era distribution, artist diversity, format preference,
and label-to-label similarity via cosine similarity on genre vectors.
"""

import asyncio
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


async def get_label_full_profile(
    driver: AsyncResilientNeo4jDriver,
    label_id: str,
) -> dict[str, Any] | None:
    """Get identity, genre, style, and decade profiles in parallel.

    Runs 4 lightweight queries concurrently instead of 6 sequential ones.
    The identity query includes artist counts; genre, style, and decade
    profiles are fetched in parallel with asyncio.gather.
    """
    identity = await get_label_identity(driver, label_id)
    if not identity:
        return None

    # Return identity early if release count is below threshold —
    # avoids running 3 parallel profile queries for labels that will
    # be rejected by _build_dna anyway.
    if identity["release_count"] < MIN_RELEASES:
        return {
            "label_id": identity["label_id"],
            "label_name": identity["label_name"],
            "release_count": identity["release_count"],
            "artist_count": identity["artist_count"],
            "genres": [],
            "styles": [],
            "decades": [],
        }

    genres, styles, decades = await asyncio.gather(
        get_label_genre_profile(driver, label_id),
        get_label_style_profile(driver, label_id),
        get_label_decade_profile(driver, label_id),
    )

    return {
        "label_id": identity["label_id"],
        "label_name": identity["label_name"],
        "release_count": identity["release_count"],
        "artist_count": identity["artist_count"],
        "genres": genres,
        "styles": styles,
        "decades": decades,
    }


async def get_candidate_labels_genre_vectors(driver: AsyncResilientNeo4jDriver, label_id: str) -> list[dict[str, Any]]:
    """Get genre vectors for labels sharing styles with the target label.

    Returns each candidate label with its genre distribution,
    filtered to labels with at least MIN_RELEASES releases.

    Optimizations:
    - Uses style-based similarity instead of genre-based.  Styles are far
      more specific than genres (757 styles vs 16 genres), so each style
      traversal processes 5-10x fewer releases.  e.g. Trance (~671K releases)
      vs Electronic (~4.9M releases).
    - Two-phase approach: first find candidate IDs (fast), then batch-fetch
      genre profiles for the top 100 candidates only.
    - Uses CALL {} per-style to prevent cross-style row explosion.
    - Phase 2 splits into 25-label batches with 2 lightweight queries each.
    - Timeout protection on each phase.
    """
    # Phase 1: Find candidate label IDs via style overlap (top 5 styles).
    # Styles are more specific than genres (757 styles vs 16 genres), so each
    # style traversal processes 5-10x fewer releases.  e.g. Trance (~671K
    # releases) vs Electronic (~4.9M releases).
    # Uses CALL {} per-style to prevent cross-style row explosion.
    candidates_cypher = """
    MATCH (l:Label {id: $label_id})<-[:ON]-(r:Release)-[:IS]->(s:Style)
    WITH l, s, count(DISTINCT r) AS style_count
    ORDER BY style_count DESC
    LIMIT 5
    WITH l, collect(s) AS top_styles
    UNWIND top_styles AS s2
    CALL {
        With s2, l
        MATCH (s2)<-[:IS]-(r2:Release)-[:ON]->(l2:Label)
        WHERE l2 <> l
        RETURN l2, count(DISTINCT r2) AS shared_in_style
    }
    WITH l2, sum(shared_in_style) AS total_shared
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

    # Phase 2: Batch-fetch genre profiles + release counts for candidates.
    # Split into 2 lightweight queries per batch (release counts + genre
    # distribution), run concurrently.  Batches of 25 labels keep peak
    # memory low (~60-75MB per batch vs 585MB for 100 labels in one query).
    candidate_ids = [c["label_id"] for c in candidates]

    batch_size = 25
    batches = [candidate_ids[i : i + batch_size] for i in range(0, len(candidate_ids), batch_size)]

    async def _fetch_batch(batch_ids: list[str]) -> list[dict[str, Any]]:
        count_cypher = """
        UNWIND $label_ids AS lid
        MATCH (l:Label {id: lid})<-[:ON]-(r:Release)
        RETURN l.id AS label_id, l.name AS label_name, count(DISTINCT r) AS release_count
        """
        genre_cypher = """
        UNWIND $label_ids AS lid
        MATCH (l:Label {id: lid})<-[:ON]-(r:Release)-[:IS]->(g:Genre)
        WITH l, g.name AS genre, count(DISTINCT r) AS genre_count
        RETURN l.id AS label_id,
               collect({name: genre, count: genre_count}) AS genres
        """
        counts, genres = await asyncio.gather(
            run_query(driver, count_cypher, timeout=60, label_ids=batch_ids),
            run_query(driver, genre_cypher, timeout=60, label_ids=batch_ids),
        )

        genre_map: dict[str, list[dict[str, Any]]] = {row["label_id"]: row["genres"] for row in genres}
        results: list[dict[str, Any]] = []
        for row in counts:
            lid = row["label_id"]
            results.append(
                {
                    "label_id": lid,
                    "label_name": row["label_name"],
                    "release_count": row["release_count"],
                    "genres": genre_map.get(lid, []),
                }
            )
        return results

    batch_results = await asyncio.gather(*[_fetch_batch(batch) for batch in batches])
    return [item for batch in batch_results for item in batch]


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

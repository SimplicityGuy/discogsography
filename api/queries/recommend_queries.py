"""Neo4j Cypher queries and scoring logic for recommendations.

Artist similarity: multi-dimensional cosine scoring (genre, style, label, collaborator).
Enhanced recommendations: multi-signal merging with weighted scoring.
Explore From Here: personalized traversal with taste-based ranking.
"""

import asyncio
from typing import Any

from api.queries.helpers import run_query, run_single
from api.queries.similarity import cosine_similarity, to_genre_vector
from common import AsyncResilientNeo4jDriver


# Minimum releases for an artist to have a meaningful fingerprint
MIN_ARTIST_RELEASES = 3

# Dimension weights for artist similarity
_WEIGHTS = {
    "genre": 0.35,
    "style": 0.25,
    "label": 0.25,
    "collaborator": 0.15,
}

# Signal weights for enhanced recommendations
_SIGNAL_WEIGHTS = {
    "artist": 0.35,
    "label": 0.25,
    "blindspot": 0.25,
    "obscurity": 0.15,
}


async def get_artist_identity(driver: AsyncResilientNeo4jDriver, artist_id: str) -> dict[str, Any] | None:
    """Get basic artist info and release count."""
    cypher = """
    MATCH (a:Artist {id: $artist_id})
    OPTIONAL MATCH (r:Release)-[:BY]->(a)
    RETURN a.id AS artist_id, a.name AS artist_name,
           count(DISTINCT r) AS release_count
    """
    return await run_single(driver, cypher, artist_id=artist_id)


async def get_artist_profile(driver: AsyncResilientNeo4jDriver, artist_id: str) -> dict[str, Any]:
    """Get an artist's full profile across all similarity dimensions."""
    genre_cypher = """
    MATCH (r:Release)-[:BY]->(a:Artist {id: $artist_id}), (r)-[:IS]->(g:Genre)
    RETURN g.name AS name, count(DISTINCT r) AS count
    ORDER BY count DESC
    """
    style_cypher = """
    MATCH (r:Release)-[:BY]->(a:Artist {id: $artist_id}), (r)-[:IS]->(s:Style)
    RETURN s.name AS name, count(DISTINCT r) AS count
    ORDER BY count DESC
    """
    label_cypher = """
    MATCH (r:Release)-[:BY]->(a:Artist {id: $artist_id}), (r)-[:ON]->(l:Label)
    RETURN l.name AS name, count(DISTINCT r) AS count
    ORDER BY count DESC
    """
    collab_cypher = """
    MATCH (r:Release)-[:BY]->(a:Artist {id: $artist_id}), (r)-[:BY]->(other:Artist)
    WHERE other.id <> $artist_id
    RETURN other.name AS name, count(DISTINCT r) AS count
    ORDER BY count DESC
    """
    genres, styles, labels, collaborators = await asyncio.gather(
        run_query(driver, genre_cypher, artist_id=artist_id),
        run_query(driver, style_cypher, artist_id=artist_id),
        run_query(driver, label_cypher, artist_id=artist_id),
        run_query(driver, collab_cypher, artist_id=artist_id),
    )
    return {
        "genres": genres,
        "styles": styles,
        "labels": labels,
        "collaborators": collaborators,
    }


async def _batch_artist_profiles(
    driver: AsyncResilientNeo4jDriver,
    candidate_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Fetch profiles for many artists in 4 batch queries (one per dimension).

    Returns a dict mapping artist_id to {genres, styles, labels, collaborators}.
    This replaces the N+1 pattern of calling get_artist_profile() per candidate.
    """
    genre_cypher = """
    UNWIND $ids AS aid
    MATCH (r:Release)-[:BY]->(a:Artist {id: aid}), (r)-[:IS]->(g:Genre)
    WITH a.id AS artist_id, g.name AS name, count(DISTINCT r) AS count
    RETURN artist_id, collect({name: name, count: count}) AS items
    """
    style_cypher = """
    UNWIND $ids AS aid
    MATCH (r:Release)-[:BY]->(a:Artist {id: aid}), (r)-[:IS]->(s:Style)
    WITH a.id AS artist_id, s.name AS name, count(DISTINCT r) AS count
    RETURN artist_id, collect({name: name, count: count}) AS items
    """
    label_cypher = """
    UNWIND $ids AS aid
    MATCH (r:Release)-[:BY]->(a:Artist {id: aid}), (r)-[:ON]->(l:Label)
    WITH a.id AS artist_id, l.name AS name, count(DISTINCT r) AS count
    RETURN artist_id, collect({name: name, count: count}) AS items
    """
    collab_cypher = """
    UNWIND $ids AS aid
    MATCH (r:Release)-[:BY]->(a:Artist {id: aid}), (r)-[:BY]->(other:Artist)
    WHERE other.id <> aid
    WITH a.id AS artist_id, other.name AS name, count(DISTINCT r) AS count
    RETURN artist_id, collect({name: name, count: count}) AS items
    """
    genre_rows, style_rows, label_rows, collab_rows = await asyncio.gather(
        run_query(driver, genre_cypher, ids=candidate_ids),
        run_query(driver, style_cypher, ids=candidate_ids),
        run_query(driver, label_cypher, ids=candidate_ids),
        run_query(driver, collab_cypher, ids=candidate_ids),
    )

    profiles: dict[str, dict[str, Any]] = {}
    for aid in candidate_ids:
        profiles[aid] = {"genres": [], "styles": [], "labels": [], "collaborators": []}

    for row in genre_rows:
        if row["artist_id"] in profiles:
            profiles[row["artist_id"]]["genres"] = row["items"]
    for row in style_rows:
        if row["artist_id"] in profiles:
            profiles[row["artist_id"]]["styles"] = row["items"]
    for row in label_rows:
        if row["artist_id"] in profiles:
            profiles[row["artist_id"]]["labels"] = row["items"]
    for row in collab_rows:
        if row["artist_id"] in profiles:
            profiles[row["artist_id"]]["collaborators"] = row["items"]

    return profiles


async def get_candidate_artists(driver: AsyncResilientNeo4jDriver, artist_id: str) -> list[dict[str, Any]]:
    """Get candidate artists sharing genres with the target, with their full profiles.

    Returns each candidate with actual release counts per genre/style/label/collaborator
    (not just presence), so cosine similarity on the vectors is meaningful.

    Optimizations over the naive approach:
    - Limits genre expansion to the artist's top 5 genres (avoids exploding
      through mega-genres like "Rock" with 6M+ releases).
    - Uses shared_count for ordering instead of re-traversing all releases
      per candidate (eliminates an extra MATCH per candidate).
    - Profiles only the top 50 candidates instead of 200 (since the final
      result is limited to 20 after cosine scoring).
    - Batch queries for profiles (4 queries total, not 200x4).
    - CALL {} per-genre prevents cross-genre row explosion (157M → ~20-30M
      DB hits for Johnny Cash; 1GB → ~300MB memory).
    - Per-genre LIMIT 500 caps broad genres like Rock (7M+ releases).
    """
    candidates_cypher = """
    MATCH (a:Artist {id: $artist_id})<-[:BY]-(r:Release)-[:IS]->(g:Genre)
    WITH a, g, count(DISTINCT r) AS genre_count
    ORDER BY genre_count DESC
    LIMIT 5
    WITH a, collect(g) AS top_genres
    UNWIND top_genres AS g2
    CALL {
        WITH g2, a
        MATCH (g2)<-[:IS]-(r2:Release)-[:BY]->(a2:Artist)
        WHERE a2 <> a AND a2.name IS NOT NULL
        WITH a2, count(DISTINCT r2) AS shared_in_genre
        ORDER BY shared_in_genre DESC
        LIMIT 500
        RETURN a2, shared_in_genre
    }
    WITH a2, sum(shared_in_genre) AS shared_count
    WHERE shared_count >= $min_releases
    RETURN a2.id AS artist_id, a2.name AS artist_name,
           shared_count AS release_count
    ORDER BY shared_count DESC
    LIMIT 200
    """
    candidates = await run_query(
        driver,
        candidates_cypher,
        timeout=60,
        artist_id=artist_id,
        min_releases=MIN_ARTIST_RELEASES,
    )

    if not candidates:
        return []

    # Profile only top 50 candidates (final result is limited to 20 after scoring)
    profile_candidates = candidates[:50]
    candidate_ids = [c["artist_id"] for c in profile_candidates]
    profiles = await _batch_artist_profiles(driver, candidate_ids)

    return [{**cand, **profiles.get(cand["artist_id"], {})} for cand in profile_candidates]


def compute_similar_artists(
    target_profile: dict[str, Any],
    candidates: list[dict[str, Any]],
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Rank candidate artists by weighted cosine similarity to the target."""
    target_vecs = {
        "genre": to_genre_vector(target_profile.get("genres", [])),
        "style": to_genre_vector(target_profile.get("styles", [])),
        "label": to_genre_vector(target_profile.get("labels", [])),
        "collaborator": to_genre_vector(target_profile.get("collaborators", [])),
    }

    if not any(target_vecs.values()):
        return []

    target_genre_names = set(target_vecs["genre"])
    target_label_names = set(target_vecs["label"])

    results = []
    for candidate in candidates:
        # Skip candidates with missing names (NULL in Neo4j)
        if not candidate.get("artist_name"):
            continue
        cand_vecs = {
            "genre": to_genre_vector(candidate.get("genres", [])),
            "style": to_genre_vector(candidate.get("styles", [])),
            "label": to_genre_vector(candidate.get("labels", [])),
            "collaborator": to_genre_vector(candidate.get("collaborators", [])),
        }

        breakdown = {}
        weighted_sum = 0.0
        for dim, weight in _WEIGHTS.items():
            sim = cosine_similarity(target_vecs[dim], cand_vecs[dim])
            breakdown[dim] = round(sim, 4)
            weighted_sum += sim * weight

        if weighted_sum <= 0.0:
            continue

        shared_genres = sorted(set(cand_vecs["genre"]) & target_genre_names)
        shared_labels = sorted(set(cand_vecs["label"]) & target_label_names)

        results.append(
            {
                "artist_id": candidate["artist_id"],
                "artist_name": candidate["artist_name"],
                "similarity": round(weighted_sum, 4),
                "breakdown": breakdown,
                "release_count": candidate.get("release_count", 0),
                "shared_genres": shared_genres,
                "shared_labels": shared_labels,
            }
        )

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:limit]


def _normalize_scores(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize candidate scores to 0-1 range (max normalization)."""
    if not candidates:
        return candidates
    max_score = max(c.get("score", 0) for c in candidates)
    if max_score <= 0:
        return candidates
    return [{**c, "score": c.get("score", 0) / max_score} for c in candidates]


def merge_recommendation_candidates(
    artist_candidates: list[dict[str, Any]],
    label_candidates: list[dict[str, Any]],
    blindspot_candidates: list[dict[str, Any]],
    collector_counts: dict[str, int] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Merge recommendation candidates from multiple signals by release ID.

    Scores are normalized to 0-1 per signal before weighting.
    Obscurity bonus is applied based on collector counts (fewer collectors = higher).
    """
    merged: dict[str, dict[str, Any]] = {}

    norm_artist = _normalize_scores(artist_candidates)
    norm_label = _normalize_scores(label_candidates)
    norm_blindspot = _normalize_scores(blindspot_candidates)

    for candidates, weight in [
        (norm_artist, _SIGNAL_WEIGHTS["artist"]),
        (norm_label, _SIGNAL_WEIGHTS["label"]),
        (norm_blindspot, _SIGNAL_WEIGHTS["blindspot"]),
    ]:
        for c in candidates:
            rid = c["id"]
            if rid not in merged:
                merged[rid] = {
                    "id": rid,
                    "title": c.get("title"),
                    "artist": c.get("artist"),
                    "label": c.get("label"),
                    "year": c.get("year"),
                    "genres": c.get("genres", []),
                    "score": 0.0,
                    "reasons": [],
                }
            merged[rid]["score"] += c.get("score", 0.0) * weight
            merged[rid]["reasons"].append(c.get("source", "unknown"))

    if collector_counts:
        max_collectors = max(collector_counts.values()) if collector_counts else 1
        for rid, entry in merged.items():
            collectors = collector_counts.get(rid, max_collectors)
            obscurity = 1.0 - (collectors / max_collectors) if max_collectors > 0 else 0.0
            entry["score"] += obscurity * _SIGNAL_WEIGHTS["obscurity"]

    results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    for r in results:
        r["score"] = round(r["score"], 4)
    return results[:limit]


async def get_collector_counts(driver: AsyncResilientNeo4jDriver, release_ids: list[str]) -> dict[str, int]:
    """Get collector counts for a set of release IDs (for obscurity scoring)."""
    if not release_ids:
        return {}
    cypher = """
    UNWIND $release_ids AS rid
    MATCH (r:Release {id: rid})
    OPTIONAL MATCH (u:User)-[:COLLECTED]->(r)
    RETURN r.id AS id, count(u) AS collectors
    """
    rows = await run_query(driver, cypher, release_ids=release_ids)
    return {row["id"]: row["collectors"] for row in rows}


async def get_label_affinity_candidates(driver: AsyncResilientNeo4jDriver, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get releases from the user's top labels that they don't own."""
    cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)-[:ON]->(l:Label)
    WITH u, l, count(r) AS label_count
    ORDER BY label_count DESC
    LIMIT 10
    MATCH (rec:Release)-[:ON]->(l)
    WHERE NOT (u)-[:COLLECTED]->(rec)
      AND NOT (u)-[:WANTS]->(rec)
    WITH rec, l, label_count
    OPTIONAL MATCH (rec)-[:BY]->(a:Artist)
    OPTIONAL MATCH (rec)-[:IS]->(g:Genre)
    RETURN rec.id AS id, rec.title AS title,
           collect(DISTINCT a.name)[0] AS artist,
           l.name AS label, rec.year AS year,
           collect(DISTINCT g.name) AS genres,
           label_count AS score
    ORDER BY score DESC
    LIMIT $limit
    """
    rows = await run_query(driver, cypher, user_id=user_id, limit=limit)
    return [{**row, "source": f"label: {row['label']} (top label)", "score": row["score"]} for row in rows]


async def get_blindspot_candidates(driver: AsyncResilientNeo4jDriver, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get releases in the user's blind-spot genres."""
    cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)-[:BY]->(a:Artist)
    WITH u, a, count(r) AS artist_releases
    ORDER BY artist_releases DESC
    LIMIT 20
    MATCH (a)<-[:BY]-(other:Release)-[:IS]->(g:Genre)
    WHERE NOT (u)-[:COLLECTED]->(other)
    WITH u, g.name AS genre, count(DISTINCT a) AS artist_overlap, collect(DISTINCT other)[0..5] AS sample
    OPTIONAL MATCH (u)-[:COLLECTED]->(cr:Release)-[:IS]->(cg:Genre)
    WHERE cg.name = genre
    WITH genre, artist_overlap, sample, count(cr) AS already_have
    WHERE already_have = 0
    UNWIND sample AS rec
    OPTIONAL MATCH (rec)-[:BY]->(ra:Artist)
    OPTIONAL MATCH (rec)-[:ON]->(rl:Label)
    RETURN rec.id AS id, rec.title AS title,
           collect(DISTINCT ra.name)[0] AS artist,
           collect(DISTINCT rl.name)[0] AS label,
           rec.year AS year,
           [genre] AS genres,
           artist_overlap AS score
    ORDER BY score DESC
    LIMIT $limit
    """
    rows = await run_query(driver, cypher, user_id=user_id, limit=limit)
    return [{**row, "source": f"blind_spot: {row['genres'][0] if row.get('genres') else 'unknown'}"} for row in rows]


async def get_explore_traversal(
    driver: AsyncResilientNeo4jDriver,
    entity_type: str,
    entity_id: str,
    hops: int = 2,
) -> list[dict[str, Any]]:
    """Perform variable-length traversal from an entity and return discovered nodes with paths."""
    if not (1 <= hops <= 3):
        hops = 2

    if entity_type in ("genre", "style"):
        node_label = entity_type.capitalize()
        match_clause = f"(start:{node_label} {{name: $entity_id}})"
    else:
        node_label = entity_type.capitalize()
        match_clause = f"(start:{node_label} {{id: $entity_id}})"

    cypher = f"""
    MATCH {match_clause}
    MATCH path = (start)-[*1..{hops}]-(discovered)
    WHERE discovered <> start
      AND (discovered:Artist OR discovered:Label OR discovered:Genre OR discovered:Style)
    WITH DISTINCT discovered,
         [n IN nodes(path) | coalesce(n.name, n.title, n.id)] AS path_names,
         [r IN relationships(path) | type(r)] AS rel_types,
         length(path) AS dist
    ORDER BY dist
    RETURN discovered.id AS id,
           coalesce(discovered.name, discovered.id) AS name,
           CASE
             WHEN discovered:Artist THEN 'artist'
             WHEN discovered:Label THEN 'label'
             WHEN discovered:Genre THEN 'genre'
             WHEN discovered:Style THEN 'style'
           END AS type,
           path_names, rel_types, dist
    LIMIT 100
    """
    return await run_query(driver, cypher, entity_id=entity_id)


def score_discoveries(
    discoveries: list[dict[str, Any]],
    user_genre_vector: dict[str, float],
    blind_spot_genres: set[str],
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Score discovered nodes against user taste and blind spots."""
    scored = []
    for d in discoveries:
        node_type = d.get("type", "")
        base_score = 0.0

        if node_type == "genre":
            if d["name"] in blind_spot_genres:
                base_score = 1.0
            elif d["name"] in user_genre_vector:
                base_score = user_genre_vector[d["name"]]
        elif node_type == "style":
            if d["name"] in blind_spot_genres:
                base_score = 1.0
        elif node_type in ("artist", "label"):
            dist = d.get("dist", 2)
            base_score = 1.0 / dist if dist > 0 else 0.5

        reason = "graph_proximity"
        if node_type in ("genre", "style") and d["name"] in blind_spot_genres:
            base_score *= 1.5
            reason = "blind_spot_boost"

        path_names = d.get("path_names", [])
        rel_types = d.get("rel_types", [])
        display_path = []
        for i, name in enumerate(path_names):
            display_path.append(str(name))
            if i < len(rel_types):
                display_path.append(f"\u2014{rel_types[i]}\u2192")

        scored.append(
            {
                "id": d.get("id", d.get("name", "")),
                "name": d["name"],
                "type": node_type,
                "score": round(base_score, 4),
                "path": display_path,
                "reason": reason,
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]

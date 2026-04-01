"""Neo4j Cypher queries for personalized user endpoints in the Explore service.

Queries the User node and its COLLECTED / WANTS relationships that are written
by the curator service when a user syncs their Discogs account.

Graph model additions (curator):
  (User)-[:COLLECTED {rating, folder_id, date_added, synced_at}]->(Release)
  (User)-[:WANTS    {rating, date_added, synced_at}]->(Release)
  (User)-[:COLLECTED]->(Release)-[:BY]->(Artist)
  (User)-[:COLLECTED]->(Release)-[:IS]->(Genre)
"""

import asyncio
import math
from typing import Any

from api.queries.helpers import run_count, run_query
from common import AsyncResilientNeo4jDriver


async def get_user_collection(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Get releases in user's Discogs collection from Neo4j.

    Returns (results, total_count).
    """
    cypher = """
    MATCH (u:User {id: $user_id})-[c:COLLECTED]->(r:Release)
    OPTIONAL MATCH (r)-[:BY]->(a:Artist)
    OPTIONAL MATCH (r)-[:ON]->(l:Label)
    OPTIONAL MATCH (r)-[:IS]->(g:Genre)
    OPTIONAL MATCH (r)-[:IS]->(s:Style)
    WITH r, c,
         collect(DISTINCT a.name)[0] AS artist_name,
         collect(DISTINCT l.name)[0] AS label_name,
         collect(DISTINCT g.name) AS genres,
         collect(DISTINCT s.name) AS styles
    RETURN r.id AS id, r.title AS title, r.year AS year,
           artist_name AS artist, label_name AS label,
           genres, styles,
           c.rating AS rating, c.date_added AS date_added,
           c.folder_id AS folder_id
    ORDER BY c.date_added DESC
    SKIP $offset LIMIT $limit
    """
    count_cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)
    RETURN count(r) AS total
    """
    results, total = await asyncio.gather(
        run_query(driver, cypher, user_id=user_id, limit=limit, offset=offset),
        run_count(driver, count_cypher, user_id=user_id),
    )
    return results, total


async def get_user_wantlist(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Get releases in user's Discogs wantlist from Neo4j.

    Returns (results, total_count).
    """
    cypher = """
    MATCH (u:User {id: $user_id})-[w:WANTS]->(r:Release)
    OPTIONAL MATCH (r)-[:BY]->(a:Artist)
    OPTIONAL MATCH (r)-[:ON]->(l:Label)
    OPTIONAL MATCH (r)-[:IS]->(g:Genre)
    OPTIONAL MATCH (r)-[:IS]->(s:Style)
    WITH r, w,
         collect(DISTINCT a.name)[0] AS artist_name,
         collect(DISTINCT l.name)[0] AS label_name,
         collect(DISTINCT g.name) AS genres,
         collect(DISTINCT s.name) AS styles
    RETURN r.id AS id, r.title AS title, r.year AS year,
           artist_name AS artist, label_name AS label,
           genres, styles,
           w.rating AS rating, w.date_added AS date_added
    ORDER BY w.date_added DESC
    SKIP $offset LIMIT $limit
    """
    count_cypher = """
    MATCH (u:User {id: $user_id})-[:WANTS]->(r:Release)
    RETURN count(r) AS total
    """
    results, total = await asyncio.gather(
        run_query(driver, cypher, user_id=user_id, limit=limit, offset=offset),
        run_count(driver, count_cypher, user_id=user_id),
    )
    return results, total


async def get_user_recommendations(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Recommend releases based on artists already in user's collection.

    Finds artists with the most collected releases, then surfaces other
    releases by those artists that the user hasn't collected or wanted yet.
    """
    cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)-[:BY]->(a:Artist)
    WITH u, a, count(r) AS collected_count
    ORDER BY collected_count DESC
    LIMIT 10
    MATCH (a)<-[:BY]-(rec:Release)
    WHERE NOT (u)-[:COLLECTED]->(rec)
      AND NOT (u)-[:WANTS]->(rec)
    WITH rec, sum(collected_count) AS score
    OPTIONAL MATCH (rec)-[:BY]->(artist:Artist)
    OPTIONAL MATCH (rec)-[:ON]->(lbl:Label)
    OPTIONAL MATCH (rec)-[:IS]->(g:Genre)
    WITH rec, score,
         collect(DISTINCT artist.name)[0] AS artist_name,
         collect(DISTINCT lbl.name)[0] AS label_name,
         collect(DISTINCT g.name) AS genres
    RETURN rec.id AS id, rec.title AS title, rec.year AS year,
           artist_name AS artist, label_name AS label,
           genres, score
    ORDER BY score DESC
    LIMIT $limit
    """
    return await run_query(driver, cypher, user_id=user_id, limit=limit)


async def get_user_collection_stats(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
) -> dict[str, Any]:
    """Get collection statistics grouped by genre, decade, and label."""
    genre_cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)-[:IS]->(g:Genre)
    RETURN g.name AS name, count(r) AS count
    ORDER BY count DESC
    LIMIT 20
    """
    decade_cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)
    WHERE r.year IS NOT NULL
    WITH (r.year / 10) * 10 AS decade, count(r) AS count
    RETURN decade, count
    ORDER BY decade
    """
    label_cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)-[:ON]->(l:Label)
    RETURN l.name AS name, count(r) AS count
    ORDER BY count DESC
    LIMIT 20
    """
    total_cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)
    RETURN count(r) AS total
    """
    artists_cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)-[:BY]->(a:Artist)
    RETURN count(DISTINCT a) AS total
    """
    unique_labels_cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)-[:ON]->(l:Label)
    RETURN count(DISTINCT l) AS total
    """
    avg_rating_cypher = """
    MATCH (u:User {id: $user_id})-[c:COLLECTED]->(r:Release)
    WHERE c.rating > 0
    RETURN avg(c.rating) AS average
    """

    _results: list[Any] = list(
        await asyncio.gather(
            run_query(driver, genre_cypher, user_id=user_id),
            run_query(driver, decade_cypher, user_id=user_id),
            run_query(driver, label_cypher, user_id=user_id),
            run_count(driver, total_cypher, user_id=user_id),
            run_count(driver, artists_cypher, user_id=user_id),
            run_count(driver, unique_labels_cypher, user_id=user_id),
            run_query(driver, avg_rating_cypher, user_id=user_id),
        )
    )
    genres, decades, labels = _results[0], _results[1], _results[2]
    total, unique_artists, unique_labels = _results[3], _results[4], _results[5]
    avg_rating_rows = _results[6]

    avg_rating = avg_rating_rows[0]["average"] if avg_rating_rows and avg_rating_rows[0]["average"] is not None else None

    return {
        "total": total,
        "unique_artists": unique_artists,
        "unique_labels": unique_labels,
        "average_rating": avg_rating,
        "by_genre": [{"name": r["name"], "count": r["count"]} for r in genres],
        "by_decade": [{"decade": r["decade"], "count": r["count"]} for r in decades],
        "by_label": [{"name": r["name"], "count": r["count"]} for r in labels],
    }


async def get_user_collection_timeline(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
    bucket: str = "year",
) -> dict[str, Any]:
    """Get collection timeline grouped by release year with genre/style/label breakdowns.

    Returns timeline data and computed insights (peak year, dominant genre,
    genre diversity via Shannon entropy, style drift rate).
    """
    multiplier = 10 if bucket == "decade" else 1

    # Main query: per-bucket counts with genre, style, and label breakdowns
    timeline_cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)
    WHERE r.year IS NOT NULL AND r.year > 0
    WITH r, (r.year / $multiplier) * $multiplier AS bucket
    OPTIONAL MATCH (r)-[:IS]->(g:Genre)
    OPTIONAL MATCH (r)-[:IS]->(s:Style)
    OPTIONAL MATCH (r)-[:ON]->(l:Label)
    WITH bucket, r, collect(DISTINCT g.name) AS rg,
         collect(DISTINCT s.name) AS rs, collect(DISTINCT l.name) AS rl
    WITH bucket, count(DISTINCT r) AS count,
         collect(DISTINCT rg) AS genre_lists,
         collect(DISTINCT rs) AS style_lists,
         collect(DISTINCT rl) AS label_lists
    RETURN bucket AS year, count,
           reduce(acc = [], lst IN genre_lists | acc + lst) AS genres,
           reduce(acc = [], lst IN style_lists | acc + lst) AS styles,
           reduce(acc = [], lst IN label_lists | acc + lst) AS labels
    ORDER BY bucket
    """
    rows = await run_query(driver, timeline_cypher, user_id=user_id, multiplier=multiplier)

    # Aggregate per-bucket data
    timeline: list[dict[str, Any]] = []
    genre_totals: dict[str, int] = {}
    all_styles_per_bucket: list[set[str]] = []

    for row in rows:
        # Count genre/style/label occurrences across releases in this bucket
        genre_counts: dict[str, int] = {}
        for g in row["genres"]:
            if g:
                genre_counts[g] = genre_counts.get(g, 0) + 1
                genre_totals[g] = genre_totals.get(g, 0) + 1

        style_set: set[str] = set()
        for s in row["styles"]:
            if s:
                style_set.add(s)

        label_counts: dict[str, int] = {}
        for lb in row["labels"]:
            if lb:
                label_counts[lb] = label_counts.get(lb, 0) + 1

        # Sort labels by count, take top 5
        top_labels = sorted(label_counts, key=label_counts.get, reverse=True)[:5]  # type: ignore[arg-type]
        top_styles = sorted(style_set)[:10]

        all_styles_per_bucket.append(style_set)

        timeline.append(
            {
                "year": row["year"],
                "count": row["count"],
                "genres": genre_counts,
                "top_labels": top_labels,
                "top_styles": top_styles,
            }
        )

    # Compute insights
    peak_year = max(timeline, key=lambda t: t["count"])["year"] if timeline else None
    dominant_genre = max(genre_totals, key=genre_totals.get) if genre_totals else None  # type: ignore[arg-type]

    # Shannon entropy for genre diversity (0 = one genre, higher = more diverse)
    total_genre_count = sum(genre_totals.values())
    genre_diversity_score = 0.0
    if total_genre_count > 0:
        for count in genre_totals.values():
            p = count / total_genre_count
            if p > 0:
                genre_diversity_score -= p * math.log2(p)
        # Normalize to 0-1 range (divide by max possible entropy)
        max_entropy = math.log2(len(genre_totals)) if len(genre_totals) > 1 else 1.0
        genre_diversity_score = round(genre_diversity_score / max_entropy, 2) if max_entropy > 0 else 0.0

    # Style drift rate: average Jaccard distance between consecutive buckets
    style_drift_rate = 0.0
    if len(all_styles_per_bucket) > 1:
        distances = []
        for i in range(1, len(all_styles_per_bucket)):
            prev, curr = all_styles_per_bucket[i - 1], all_styles_per_bucket[i]
            union = prev | curr
            if union:
                distances.append(1.0 - len(prev & curr) / len(union))
        style_drift_rate = round(sum(distances) / len(distances), 2) if distances else 0.0

    return {
        "timeline": timeline,
        "insights": {
            "peak_year": peak_year,
            "dominant_genre": dominant_genre,
            "genre_diversity_score": genre_diversity_score,
            "style_drift_rate": style_drift_rate,
        },
    }


async def get_user_collection_evolution(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
    metric: str = "genre",
) -> dict[str, Any]:
    """Get how a specific metric (genre/style/label) distribution shifts across release years.

    Returns per-year value counts and a summary.
    """
    _ALLOWED_METRICS = {"genre", "style", "label"}
    if metric not in _ALLOWED_METRICS:
        raise ValueError(f"Invalid metric: {metric!r}. Must be one of {_ALLOWED_METRICS}")

    if metric == "style":
        rel_type = "IS"
        node_label = "Style"
    elif metric == "label":
        rel_type = "ON"
        node_label = "Label"
    else:
        rel_type = "IS"
        node_label = "Genre"

    cypher = f"""
    MATCH (u:User {{id: $user_id}})-[:COLLECTED]->(r:Release)-[:{rel_type}]->(v:{node_label})
    WHERE r.year IS NOT NULL AND r.year > 0
    RETURN r.year AS year, v.name AS value, count(r) AS count
    ORDER BY year, count DESC
    """
    rows = await run_query(driver, cypher, user_id=user_id)

    # Group by year
    year_data: dict[int, dict[str, int]] = {}
    unique_values: set[str] = set()
    for row in rows:
        year = row["year"]
        if year not in year_data:
            year_data[year] = {}
        year_data[year][row["value"]] = row["count"]
        unique_values.add(row["value"])

    data = [{"year": y, "values": v} for y, v in sorted(year_data.items())]

    return {
        "metric": metric,
        "data": data,
        "summary": {
            "total_years": len(year_data),
            "unique_values": len(unique_values),
        },
    }


async def check_releases_user_status(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
    release_ids: list[str],
) -> dict[str, dict[str, bool]]:
    """Check which release IDs are in user's collection or wantlist.

    Returns a dict mapping release_id -> {in_collection, in_wantlist}.
    """
    if not release_ids:
        return {}

    cypher = """
    MATCH (u:User {id: $user_id})
    UNWIND $release_ids AS rid
    OPTIONAL MATCH (u)-[:COLLECTED]->(c:Release {id: rid})
    OPTIONAL MATCH (u)-[:WANTS]->(w:Release {id: rid})
    RETURN rid AS release_id,
           c IS NOT NULL AS in_collection,
           w IS NOT NULL AS in_wantlist
    """
    rows = await run_query(driver, cypher, user_id=user_id, release_ids=release_ids)
    return {
        row["release_id"]: {
            "in_collection": row["in_collection"],
            "in_wantlist": row["in_wantlist"],
        }
        for row in rows
    }

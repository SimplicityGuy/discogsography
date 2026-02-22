"""Neo4j Cypher queries for personalized user endpoints in the Explore service.

Queries the User node and its COLLECTED / WANTS relationships that are written
by the collector service when a user syncs their Discogs account.

Graph model additions (collector):
  (User)-[:COLLECTED {rating, folder_id, date_added, synced_at}]->(Release)
  (User)-[:WANTS    {rating, date_added, synced_at}]->(Release)
  (User)-[:COLLECTED]->(Release)-[:BY]->(Artist)
  (User)-[:COLLECTED]->(Release)-[:IS]->(Genre)
"""

from typing import Any

from common import AsyncResilientNeo4jDriver


async def _run_query(driver: AsyncResilientNeo4jDriver, cypher: str, **params: Any) -> list[dict[str, Any]]:
    """Execute a Cypher query and return all results as a list of dicts."""
    async with await driver.session() as session:
        result = await session.run(cypher, params)
        return [dict(record) async for record in result]


async def _run_count(driver: AsyncResilientNeo4jDriver, cypher: str, **params: Any) -> int:
    """Execute a count Cypher query and return the integer result."""
    async with await driver.session() as session:
        result = await session.run(cypher, params)
        record = await result.single()
        return int(record["total"]) if record else 0


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
    WITH r, c,
         collect(DISTINCT a.name)[0] AS artist_name,
         collect(DISTINCT l.name)[0] AS label_name
    RETURN r.id AS id, r.title AS title, r.year AS year,
           artist_name AS artist, label_name AS label,
           c.rating AS rating, c.date_added AS date_added,
           c.folder_id AS folder_id
    ORDER BY c.date_added DESC
    SKIP $offset LIMIT $limit
    """
    count_cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)
    RETURN count(r) AS total
    """
    results, total = (
        await _run_query(driver, cypher, user_id=user_id, limit=limit, offset=offset),
        await _run_count(driver, count_cypher, user_id=user_id),
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
    WITH r, w,
         collect(DISTINCT a.name)[0] AS artist_name,
         collect(DISTINCT l.name)[0] AS label_name
    RETURN r.id AS id, r.title AS title, r.year AS year,
           artist_name AS artist, label_name AS label,
           w.rating AS rating, w.date_added AS date_added
    ORDER BY w.date_added DESC
    SKIP $offset LIMIT $limit
    """
    count_cypher = """
    MATCH (u:User {id: $user_id})-[:WANTS]->(r:Release)
    RETURN count(r) AS total
    """
    results, total = (
        await _run_query(driver, cypher, user_id=user_id, limit=limit, offset=offset),
        await _run_count(driver, count_cypher, user_id=user_id),
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
    return await _run_query(driver, cypher, user_id=user_id, limit=limit)


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

    genres, decades, labels, total = (
        await _run_query(driver, genre_cypher, user_id=user_id),
        await _run_query(driver, decade_cypher, user_id=user_id),
        await _run_query(driver, label_cypher, user_id=user_id),
        await _run_count(driver, total_cypher, user_id=user_id),
    )

    return {
        "total": total,
        "by_genre": [{"name": r["name"], "count": r["count"]} for r in genres],
        "by_decade": [{"decade": r["decade"], "count": r["count"]} for r in decades],
        "by_label": [{"name": r["name"], "count": r["count"]} for r in labels],
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
    rows = await _run_query(driver, cypher, user_id=user_id, release_ids=release_ids)
    return {
        row["release_id"]: {
            "in_collection": row["in_collection"],
            "in_wantlist": row["in_wantlist"],
        }
        for row in rows
    }

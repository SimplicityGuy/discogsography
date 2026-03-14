"""Neo4j Cypher queries for taste fingerprint endpoints.

Analyses a user's COLLECTED relationships to build genre x decade heatmaps,
obscurity scores, taste drift timelines, blind spots, and top labels.
"""

import asyncio
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


async def get_collection_count(driver: AsyncResilientNeo4jDriver, user_id: str) -> int:
    """Return the number of releases in a user's collection."""
    cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)
    RETURN count(r) AS total
    """
    return await _run_count(driver, cypher, user_id=user_id)


async def get_taste_heatmap(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
) -> tuple[list[dict[str, Any]], int]:
    """Return genre x decade heatmap cells and total collection size.

    Returns (cells, total) where each cell has genre, decade, count.
    """
    cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)-[:IS]->(g:Genre)
    WHERE r.year IS NOT NULL
    WITH g.name AS genre, (r.year / 10) * 10 AS decade, count(*) AS count
    RETURN genre, decade, count
    ORDER BY count DESC
    """
    count_cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)
    RETURN count(r) AS total
    """
    cells, total = await asyncio.gather(
        _run_query(driver, cypher, user_id=user_id),
        _run_count(driver, count_cypher, user_id=user_id),
    )
    return cells, total


async def get_obscurity_score(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
) -> dict[str, Any]:
    """Calculate how obscure a user's collection is.

    For each release, counts how many *other* users also collected it.
    Zero collectors means maximally obscure (score = 1.0).
    Score = 1 - (median_collectors / max_collectors) clamped to [0, 1].
    """
    cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)
    OPTIONAL MATCH (other:User)-[:COLLECTED]->(r)
    WHERE other <> u
    WITH r, count(other) AS collectors
    RETURN collectors
    ORDER BY collectors
    """
    count_cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)
    RETURN count(r) AS total
    """
    rows, total = await asyncio.gather(
        _run_query(driver, cypher, user_id=user_id),
        _run_count(driver, count_cypher, user_id=user_id),
    )

    if not rows:
        return {"score": 1.0, "median_collectors": 0.0, "total_releases": 0}

    collector_counts = [r["collectors"] for r in rows]
    n = len(collector_counts)
    mid = n // 2
    median = (collector_counts[mid - 1] + collector_counts[mid]) / 2.0 if n % 2 == 0 else float(collector_counts[mid])

    max_collectors = max(collector_counts) if collector_counts else 0
    score = 1.0 if max_collectors == 0 else max(0.0, min(1.0, 1.0 - (median / max_collectors)))

    return {"score": round(score, 4), "median_collectors": median, "total_releases": total}


async def get_taste_drift(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
) -> list[dict[str, Any]]:
    """Return top genre per year based on date_added.

    Buckets by year using substring(c.date_added, 0, 4).
    """
    cypher = """
    MATCH (u:User {id: $user_id})-[c:COLLECTED]->(r:Release)-[:IS]->(g:Genre)
    WHERE c.date_added IS NOT NULL
    WITH substring(c.date_added, 0, 4) AS year, g.name AS genre, count(*) AS count
    ORDER BY year, count DESC
    WITH year, collect({genre: genre, count: count})[0] AS top
    RETURN year, top.genre AS top_genre, top.count AS count
    ORDER BY year
    """
    return await _run_query(driver, cypher, user_id=user_id)


async def get_blind_spots(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Find genres the user's favourite artists release in but the user hasn't collected.

    Carries `u` through WITH clauses (no re-lookup). Scores by artist_overlap.
    """
    cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)-[:BY]->(a:Artist)
    WITH u, a, count(r) AS artist_releases
    ORDER BY artist_releases DESC
    LIMIT 20
    MATCH (a)<-[:BY]-(other:Release)-[:IS]->(g:Genre)
    WHERE NOT (u)-[:COLLECTED]->(other)
    WITH u, g.name AS genre, count(DISTINCT a) AS artist_overlap,
         collect(DISTINCT other.title)[0] AS example_release
    OPTIONAL MATCH (u)-[:COLLECTED]->(cr:Release)-[:IS]->(cg:Genre)
    WHERE cg.name = genre
    WITH genre, artist_overlap, example_release, count(cr) AS already_have
    WHERE already_have = 0
    RETURN genre, artist_overlap, example_release
    ORDER BY artist_overlap DESC
    LIMIT $limit
    """
    return await _run_query(driver, cypher, user_id=user_id, limit=limit)


async def get_top_labels(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return the user's most collected labels."""
    cypher = """
    MATCH (u:User {id: $user_id})-[:COLLECTED]->(r:Release)-[:ON]->(l:Label)
    RETURN l.name AS label, count(r) AS count
    ORDER BY count DESC
    LIMIT $limit
    """
    return await _run_query(driver, cypher, user_id=user_id, limit=limit)

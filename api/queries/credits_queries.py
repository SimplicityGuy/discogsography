"""Neo4j Cypher queries for the credits & provenance feature.

All queries target Person nodes and CREDITED_ON relationships created
by the graphinator from Discogs release extraartists data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from api.queries.helpers import run_query, run_single


if TYPE_CHECKING:
    from common import AsyncResilientNeo4jDriver


async def get_person_credits(
    driver: AsyncResilientNeo4jDriver,
    name: str,
) -> list[dict[str, Any]]:
    """Return all releases a person is credited on, grouped by role."""
    cypher = """
    MATCH (p:Person {name: $name})-[c:CREDITED_ON]->(r:Release)
    OPTIONAL MATCH (r)-[:BY]->(a:Artist)
    OPTIONAL MATCH (r)-[:ON]->(l:Label)
    RETURN r.id AS release_id,
           r.title AS title,
           r.year AS year,
           c.role AS role,
           c.category AS category,
           collect(DISTINCT a.name)[..3] AS artists,
           collect(DISTINCT l.name)[..1] AS labels
    ORDER BY r.year DESC, r.title
    """
    return await run_query(driver, cypher, name=name)


async def get_person_timeline(
    driver: AsyncResilientNeo4jDriver,
    name: str,
) -> list[dict[str, Any]]:
    """Return year-by-year credit activity for a person."""
    cypher = """
    MATCH (p:Person {name: $name})-[c:CREDITED_ON]->(r:Release)
    WHERE r.year IS NOT NULL
    RETURN r.year AS year,
           c.category AS category,
           count(*) AS count
    ORDER BY r.year
    """
    return await run_query(driver, cypher, name=name)


async def get_release_credits(
    driver: AsyncResilientNeo4jDriver,
    release_id: str,
) -> list[dict[str, Any]]:
    """Return full credits breakdown for a release."""
    cypher = """
    MATCH (p:Person)-[c:CREDITED_ON]->(r:Release {id: $release_id})
    OPTIONAL MATCH (p)-[:SAME_AS]->(a:Artist)
    RETURN p.name AS name,
           c.role AS role,
           c.category AS category,
           a.id AS artist_id,
           a.name AS artist_name
    ORDER BY c.category, p.name
    """
    return await run_query(driver, cypher, release_id=release_id)


async def get_role_leaderboard(
    driver: AsyncResilientNeo4jDriver,
    category: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return most prolific people in a given role category."""
    cypher = """
    MATCH (p:Person)-[c:CREDITED_ON]->(r:Release)
    WHERE c.category = $category
    WITH p, count(DISTINCT r) AS credit_count
    RETURN p.name AS name, credit_count
    ORDER BY credit_count DESC
    LIMIT $limit
    """
    return await run_query(driver, cypher, category=category, limit=limit)


async def get_shared_credits(
    driver: AsyncResilientNeo4jDriver,
    person1: str,
    person2: str,
) -> list[dict[str, Any]]:
    """Find releases where two people are both credited."""
    cypher = """
    MATCH (p1:Person {name: $person1})-[c1:CREDITED_ON]->(r:Release)<-[c2:CREDITED_ON]-(p2:Person {name: $person2})
    OPTIONAL MATCH (r)-[:BY]->(a:Artist)
    RETURN r.id AS release_id,
           r.title AS title,
           r.year AS year,
           c1.role AS person1_role,
           c2.role AS person2_role,
           collect(DISTINCT a.name)[..3] AS artists
    ORDER BY r.year DESC
    """
    return await run_query(driver, cypher, person1=person1, person2=person2)


async def get_person_connections(
    driver: AsyncResilientNeo4jDriver,
    name: str,
    depth: int = 2,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Find people connected through shared releases (collaboration graph).

    Returns edges: each row is a pair of connected people with the count
    of shared releases between them.
    """
    if depth < 1:
        depth = 1
    if depth > 3:
        depth = 3

    cypher = """
    MATCH (start:Person {name: $name})-[:CREDITED_ON]->(r:Release)<-[:CREDITED_ON]-(connected:Person)
    WHERE connected.name <> $name
    WITH connected, count(DISTINCT r) AS shared_count
    ORDER BY shared_count DESC
    LIMIT $limit
    RETURN connected.name AS name, shared_count
    """
    if depth >= 2:
        cypher = """
        MATCH path = (start:Person {name: $name})-[:CREDITED_ON]->(:Release)<-[:CREDITED_ON]-(hop1:Person)
        WHERE hop1.name <> $name
        WITH DISTINCT hop1, count(DISTINCT nodes(path)[1]) AS direct_shared
        ORDER BY direct_shared DESC
        LIMIT $limit
        OPTIONAL MATCH (hop1)-[:CREDITED_ON]->(r2:Release)<-[:CREDITED_ON]-(hop2:Person)
        WHERE hop2.name <> $name AND hop2.name <> hop1.name
        WITH hop1, direct_shared,
             CASE WHEN hop2 IS NOT NULL
                  THEN collect(DISTINCT {name: hop2.name, via: hop1.name, shared: count(DISTINCT r2)})[..10]
                  ELSE []
             END AS second_hops
        RETURN hop1.name AS name, direct_shared AS shared_count, second_hops
        """
    return await run_query(driver, cypher, name=name, limit=limit)


async def autocomplete_person(
    driver: AsyncResilientNeo4jDriver,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search credited people by name using fulltext index."""
    # Build autocomplete query: add wildcard for partial matching
    search_query = query.strip()
    if search_query and not search_query.endswith("*"):
        search_query = search_query + "*"

    cypher = """
    CALL db.index.fulltext.queryNodes('person_name_fulltext', $query)
    YIELD node, score
    RETURN node.name AS name, score
    ORDER BY score DESC
    LIMIT $limit
    """
    return await run_query(driver, cypher, query=search_query, limit=limit)


async def get_person_profile(
    driver: AsyncResilientNeo4jDriver,
    name: str,
) -> dict[str, Any] | None:
    """Get summary profile for a person: total credits, role breakdown, active years."""
    cypher = """
    MATCH (p:Person {name: $name})-[c:CREDITED_ON]->(r:Release)
    WITH p, count(c) AS total_credits,
         collect(DISTINCT c.category) AS categories,
         min(r.year) AS first_year,
         max(r.year) AS last_year
    OPTIONAL MATCH (p)-[:SAME_AS]->(a:Artist)
    RETURN p.name AS name,
           total_credits,
           categories,
           first_year,
           last_year,
           a.id AS artist_id,
           a.name AS artist_name
    """
    return await run_single(driver, cypher, name=name)


async def get_person_role_breakdown(
    driver: AsyncResilientNeo4jDriver,
    name: str,
) -> list[dict[str, Any]]:
    """Get count of credits per role category for a person."""
    cypher = """
    MATCH (p:Person {name: $name})-[c:CREDITED_ON]->(r:Release)
    RETURN c.category AS category, count(*) AS count
    ORDER BY count DESC
    """
    return await run_query(driver, cypher, name=name)

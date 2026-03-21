"""Neo4j Cypher queries for collection gap analysis.

Finds releases that a user does NOT own for a given label, artist, or master,
enabling "Complete My Collection" functionality.

Graph model used:
  (User)-[:COLLECTED]->(Release)-[:BY]->(Artist)
  (User)-[:COLLECTED]->(Release)-[:ON]->(Label)
  (User)-[:WANTS]->(Release)
  (Release)-[:DERIVED_FROM]->(Master)
  Release nodes have: id, title, year, formats (list of strings), sha256
"""

from typing import Any

from api.queries.helpers import run_count, run_query
from common import AsyncResilientNeo4jDriver


def _build_filters(exclude_wantlist: bool, formats: list[str] | None) -> str:
    """Build optional WHERE clause fragments for gap queries."""
    clauses: list[str] = []
    if exclude_wantlist:
        clauses.append("AND NOT (u)-[:WANTS]->(r)")
    if formats:
        clauses.append("AND ANY(f IN r.formats WHERE f IN $formats)")
    return "\n    ".join(clauses)


async def get_label_gaps(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
    label_id: str,
    limit: int = 50,
    offset: int = 0,
    exclude_wantlist: bool = False,
    formats: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Get releases on a label that the user does not own."""
    extra = _build_filters(exclude_wantlist, formats)
    cypher = f"""
    MATCH (u:User {{id: $user_id}})
    MATCH (l:Label {{id: $label_id}})<-[:ON]-(r:Release)
    WHERE NOT (u)-[:COLLECTED]->(r)
    {extra}
    OPTIONAL MATCH (r)-[:BY]->(a:Artist)
    OPTIONAL MATCH (r)-[:IS]->(g:Genre)
    OPTIONAL MATCH (u)-[w:WANTS]->(r)
    WITH r,
         collect(DISTINCT a.name)[0] AS artist_name,
         collect(DISTINCT g.name) AS genres,
         w IS NOT NULL AS on_wantlist
    RETURN r.id AS id, r.title AS title, r.year AS year,
           r.formats AS formats, artist_name AS artist, genres, on_wantlist
    ORDER BY r.year DESC, r.title
    SKIP $offset LIMIT $limit
    """
    count_cypher = f"""
    MATCH (u:User {{id: $user_id}})
    MATCH (l:Label {{id: $label_id}})<-[:ON]-(r:Release)
    WHERE NOT (u)-[:COLLECTED]->(r)
    {extra}
    RETURN count(r) AS total
    """
    params: dict[str, Any] = {"user_id": user_id, "label_id": label_id, "limit": limit, "offset": offset}
    if formats:
        params["formats"] = formats
    results = await run_query(driver, cypher, **params)
    total = await run_count(driver, count_cypher, **params)
    return results, total


async def get_label_gap_summary(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
    label_id: str,
) -> dict[str, Any]:
    """Get summary counts for a label: total releases, owned, missing."""
    cypher = """
    MATCH (l:Label {id: $label_id})<-[:ON]-(r:Release)
    WITH count(r) AS total_releases
    OPTIONAL MATCH (u:User {id: $user_id})-[:COLLECTED]->(c:Release)-[:ON]->(l2:Label {id: $label_id})
    WITH total_releases, count(c) AS owned
    RETURN total_releases AS total, owned, total_releases - owned AS missing
    """
    rows = await run_query(driver, cypher, user_id=user_id, label_id=label_id)
    if rows:
        return {"total": rows[0]["total"], "owned": rows[0]["owned"], "missing": rows[0]["missing"]}
    return {"total": 0, "owned": 0, "missing": 0}


async def get_label_metadata(
    driver: AsyncResilientNeo4jDriver,
    label_id: str,
) -> dict[str, Any] | None:
    """Get label name and ID."""
    rows = await run_query(driver, "MATCH (l:Label {id: $label_id}) RETURN l.id AS id, l.name AS name", label_id=label_id)
    return rows[0] if rows else None


async def get_artist_gaps(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
    artist_id: str,
    limit: int = 50,
    offset: int = 0,
    exclude_wantlist: bool = False,
    formats: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Get releases by an artist that the user does not own."""
    extra = _build_filters(exclude_wantlist, formats)
    cypher = f"""
    MATCH (u:User {{id: $user_id}})
    MATCH (a:Artist {{id: $artist_id}})<-[:BY]-(r:Release)
    WHERE NOT (u)-[:COLLECTED]->(r)
    {extra}
    OPTIONAL MATCH (r)-[:ON]->(l:Label)
    OPTIONAL MATCH (r)-[:IS]->(g:Genre)
    OPTIONAL MATCH (u)-[w:WANTS]->(r)
    WITH r,
         collect(DISTINCT l.name)[0] AS label_name,
         collect(DISTINCT g.name) AS genres,
         w IS NOT NULL AS on_wantlist
    RETURN r.id AS id, r.title AS title, r.year AS year,
           r.formats AS formats, label_name AS label, genres, on_wantlist
    ORDER BY r.year DESC, r.title
    SKIP $offset LIMIT $limit
    """
    count_cypher = f"""
    MATCH (u:User {{id: $user_id}})
    MATCH (a:Artist {{id: $artist_id}})<-[:BY]-(r:Release)
    WHERE NOT (u)-[:COLLECTED]->(r)
    {extra}
    RETURN count(r) AS total
    """
    params: dict[str, Any] = {"user_id": user_id, "artist_id": artist_id, "limit": limit, "offset": offset}
    if formats:
        params["formats"] = formats
    results = await run_query(driver, cypher, **params)
    total = await run_count(driver, count_cypher, **params)
    return results, total


async def get_artist_gap_summary(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
    artist_id: str,
) -> dict[str, Any]:
    """Get summary counts for an artist: total releases, owned, missing."""
    cypher = """
    MATCH (a:Artist {id: $artist_id})<-[:BY]-(r:Release)
    WITH count(r) AS total_releases
    OPTIONAL MATCH (u:User {id: $user_id})-[:COLLECTED]->(c:Release)-[:BY]->(a2:Artist {id: $artist_id})
    WITH total_releases, count(c) AS owned
    RETURN total_releases AS total, owned, total_releases - owned AS missing
    """
    rows = await run_query(driver, cypher, user_id=user_id, artist_id=artist_id)
    if rows:
        return {"total": rows[0]["total"], "owned": rows[0]["owned"], "missing": rows[0]["missing"]}
    return {"total": 0, "owned": 0, "missing": 0}


async def get_artist_metadata(
    driver: AsyncResilientNeo4jDriver,
    artist_id: str,
) -> dict[str, Any] | None:
    """Get artist name and ID."""
    rows = await run_query(driver, "MATCH (a:Artist {id: $artist_id}) RETURN a.id AS id, a.name AS name", artist_id=artist_id)
    return rows[0] if rows else None


async def get_master_gaps(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
    master_id: str,
    limit: int = 50,
    offset: int = 0,
    exclude_wantlist: bool = False,
    formats: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Get pressings of a master release that the user does not own."""
    extra = _build_filters(exclude_wantlist, formats)
    cypher = f"""
    MATCH (u:User {{id: $user_id}})
    MATCH (m:Master {{id: $master_id}})<-[:DERIVED_FROM]-(r:Release)
    WHERE NOT (u)-[:COLLECTED]->(r)
    {extra}
    OPTIONAL MATCH (r)-[:BY]->(a:Artist)
    OPTIONAL MATCH (r)-[:ON]->(l:Label)
    OPTIONAL MATCH (r)-[:IS]->(g:Genre)
    OPTIONAL MATCH (u)-[w:WANTS]->(r)
    WITH r,
         collect(DISTINCT a.name)[0] AS artist_name,
         collect(DISTINCT l.name)[0] AS label_name,
         collect(DISTINCT g.name) AS genres,
         w IS NOT NULL AS on_wantlist
    RETURN r.id AS id, r.title AS title, r.year AS year,
           r.formats AS formats, artist_name AS artist, label_name AS label,
           genres, on_wantlist
    ORDER BY r.year DESC, r.title
    SKIP $offset LIMIT $limit
    """
    count_cypher = f"""
    MATCH (u:User {{id: $user_id}})
    MATCH (m:Master {{id: $master_id}})<-[:DERIVED_FROM]-(r:Release)
    WHERE NOT (u)-[:COLLECTED]->(r)
    {extra}
    RETURN count(r) AS total
    """
    params: dict[str, Any] = {"user_id": user_id, "master_id": master_id, "limit": limit, "offset": offset}
    if formats:
        params["formats"] = formats
    results = await run_query(driver, cypher, **params)
    total = await run_count(driver, count_cypher, **params)
    return results, total


async def get_master_gap_summary(
    driver: AsyncResilientNeo4jDriver,
    user_id: str,
    master_id: str,
) -> dict[str, Any]:
    """Get summary counts for a master: total pressings, owned, missing."""
    cypher = """
    MATCH (m:Master {id: $master_id})<-[:DERIVED_FROM]-(r:Release)
    WITH count(r) AS total_releases
    OPTIONAL MATCH (u:User {id: $user_id})-[:COLLECTED]->(c:Release)-[:DERIVED_FROM]->(m2:Master {id: $master_id})
    WITH total_releases, count(c) AS owned
    RETURN total_releases AS total, owned, total_releases - owned AS missing
    """
    rows = await run_query(driver, cypher, user_id=user_id, master_id=master_id)
    if rows:
        return {"total": rows[0]["total"], "owned": rows[0]["owned"], "missing": rows[0]["missing"]}
    return {"total": 0, "owned": 0, "missing": 0}


async def get_master_metadata(
    driver: AsyncResilientNeo4jDriver,
    master_id: str,
) -> dict[str, Any] | None:
    """Get master title and ID."""
    rows = await run_query(driver, "MATCH (m:Master {id: $master_id}) RETURN m.id AS id, m.title AS name", master_id=master_id)
    return rows[0] if rows else None

"""Neo4j Cypher queries for Explore service.

All database queries are defined here to keep the API layer thin.

Graph model reference:
  (Release)-[:BY]->(Artist)         Release is by Artist
  (Release)-[:ON]->(Label)          Release is on Label
  (Release)-[:IS]->(Genre)          Release is genre
  (Release)-[:IS]->(Style)          Release is style
  (Release)-[:DERIVED_FROM]->(Master)  Release derived from Master
  (Artist)-[:ALIAS_OF]->(Artist)    Artist alias
  (Artist)-[:MEMBER_OF]->(Artist)   Artist is member of group

Note: Release.year is denormalised from the release's own 'released' date at
ingest time, so queries can use r.year directly without joining to Master.
The release_year_index on Release.year makes ORDER BY year efficient.
"""

import re
from typing import Any

from common import AsyncResilientNeo4jDriver


# Lucene special characters that must be escaped in fulltext queries
_LUCENE_SPECIAL_RE = re.compile(r'([+\-&|!(){}[\]^"~*?:\\/])')


def _escape_lucene_query(query: str) -> str:
    """Escape Lucene special characters in a fulltext search query."""
    return _LUCENE_SPECIAL_RE.sub(r"\\\1", query)


def _build_autocomplete_query(query: str) -> str:
    """Build a Lucene fulltext query with wildcard on each term for prefix matching."""
    terms = query.split()
    return " AND ".join(_escape_lucene_query(term) + "*" for term in terms)


# --- Query execution helpers ---


async def _run_query(driver: AsyncResilientNeo4jDriver, cypher: str, **params: Any) -> list[dict[str, Any]]:
    """Execute a Cypher query and return all results as a list of dicts."""
    async with await driver.session() as session:
        result = await session.run(cypher, params)
        return [dict(record) async for record in result]


async def _run_single(driver: AsyncResilientNeo4jDriver, cypher: str, **params: Any) -> dict[str, Any] | None:
    """Execute a Cypher query and return a single result, or None if not found."""
    async with await driver.session() as session:
        result = await session.run(cypher, params)
        record = await result.single()
        return dict(record) if record else None


async def _run_count(driver: AsyncResilientNeo4jDriver, cypher: str, **params: Any) -> int:
    """Execute a count Cypher query and return the integer result."""
    async with await driver.session() as session:
        result = await session.run(cypher, params)
        record = await result.single()
        return int(record["total"]) if record else 0


async def find_shortest_path(
    driver: AsyncResilientNeo4jDriver,
    from_id: str,
    to_id: str,
    max_depth: int = 10,
) -> dict[str, Any] | None:
    """Find the shortest path between two nodes by their string IDs.

    Returns a dict with keys ``nodes`` (list of node property dicts) and
    ``rels`` (list of relationship type strings), or None if no path exists.
    Each node dict has: id, name, labels.

    ``max_depth`` is interpolated as an integer literal in Cypher (it cannot
    be a query parameter). The caller is responsible for validating the range.
    """
    depth = int(max_depth)
    cypher = f"""
    MATCH (a {{id: $from_id}}), (b {{id: $to_id}})
    MATCH p = shortestPath((a)-[*..{depth}]-(b))
    RETURN [node IN nodes(p) | {{
               id: node.id,
               name: coalesce(node.name, node.title, ''),
               labels: labels(node)
           }}] AS nodes,
           [rel IN relationships(p) | type(rel)] AS rels
    """
    return await _run_single(driver, cypher, from_id=from_id, to_id=to_id)


# --- Autocomplete ---


async def autocomplete_artist(driver: AsyncResilientNeo4jDriver, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search artists by name using fulltext index."""
    cypher = """
    CALL db.index.fulltext.queryNodes('artist_name_fulltext', $query)
    YIELD node, score
    RETURN node.id AS id, node.name AS name, score
    ORDER BY score DESC
    LIMIT $limit
    """
    return await _run_query(driver, cypher, query=_build_autocomplete_query(query), limit=limit)


async def autocomplete_label(driver: AsyncResilientNeo4jDriver, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search labels by name using fulltext index."""
    cypher = """
    CALL db.index.fulltext.queryNodes('label_name_fulltext', $query)
    YIELD node, score
    RETURN node.id AS id, node.name AS name, score
    ORDER BY score DESC
    LIMIT $limit
    """
    return await _run_query(driver, cypher, query=_build_autocomplete_query(query), limit=limit)


async def autocomplete_genre(driver: AsyncResilientNeo4jDriver, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search genres by name using fulltext index."""
    cypher = """
    CALL db.index.fulltext.queryNodes('genre_name_fulltext', $query)
    YIELD node, score
    RETURN node.name AS id, node.name AS name, score
    ORDER BY score DESC
    LIMIT $limit
    """
    return await _run_query(driver, cypher, query=_build_autocomplete_query(query), limit=limit)


async def autocomplete_style(driver: AsyncResilientNeo4jDriver, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search styles by name using fulltext index."""
    cypher = """
    CALL db.index.fulltext.queryNodes('style_name_fulltext', $query)
    YIELD node, score
    RETURN node.name AS id, node.name AS name, score
    ORDER BY score DESC
    LIMIT $limit
    """
    return await _run_query(driver, cypher, query=_build_autocomplete_query(query), limit=limit)


# --- Explore (center node + category nodes) ---


async def explore_artist(driver: AsyncResilientNeo4jDriver, name: str) -> dict[str, Any] | None:
    """Get artist center node with category counts."""
    cypher = """
    MATCH (a:Artist {name: $name})
    RETURN a.id AS id, a.name AS name,
           COUNT { MATCH (r:Release)-[:BY]->(a) RETURN DISTINCT r } AS release_count,
           COUNT { MATCH (r:Release)-[:BY]->(a), (r)-[:ON]->(l:Label) RETURN DISTINCT l } AS label_count,
           COUNT { (a)-[:ALIAS_OF]->(:Artist) }
               + COUNT { (a)-[:MEMBER_OF]->(:Artist) }
               + COUNT { (:Artist)-[:MEMBER_OF]->(a) } AS alias_count
    """
    return await _run_single(driver, cypher, name=name)


async def explore_genre(driver: AsyncResilientNeo4jDriver, name: str) -> dict[str, Any] | None:
    """Get genre center node with category counts."""
    cypher = """
    MATCH (g:Genre {name: $name})
    RETURN g.name AS id, g.name AS name,
           COUNT { MATCH (r:Release)-[:IS]->(g) RETURN DISTINCT r } AS release_count,
           COUNT { MATCH (r:Release)-[:IS]->(g), (r)-[:BY]->(a:Artist) RETURN DISTINCT a } AS artist_count,
           COUNT { MATCH (r:Release)-[:IS]->(g), (r)-[:ON]->(l:Label) RETURN DISTINCT l } AS label_count,
           COUNT { MATCH (r:Release)-[:IS]->(g), (r)-[:IS]->(s:Style) RETURN DISTINCT s } AS style_count
    """
    return await _run_single(driver, cypher, name=name)


async def explore_label(driver: AsyncResilientNeo4jDriver, name: str) -> dict[str, Any] | None:
    """Get label center node with category counts."""
    cypher = """
    MATCH (l:Label {name: $name})
    RETURN l.id AS id, l.name AS name,
           COUNT { MATCH (r:Release)-[:ON]->(l) RETURN DISTINCT r } AS release_count,
           COUNT { MATCH (r:Release)-[:ON]->(l), (r)-[:BY]->(a:Artist) RETURN DISTINCT a } AS artist_count,
           COUNT { MATCH (r:Release)-[:ON]->(l), (r)-[:IS]->(g:Genre) RETURN DISTINCT g } AS genre_count
    """
    return await _run_single(driver, cypher, name=name)


async def explore_style(driver: AsyncResilientNeo4jDriver, name: str) -> dict[str, Any] | None:
    """Get style center node with category counts."""
    cypher = """
    MATCH (s:Style {name: $name})
    RETURN s.name AS id, s.name AS name,
           COUNT { MATCH (r:Release)-[:IS]->(s) RETURN DISTINCT r } AS release_count,
           COUNT { MATCH (r:Release)-[:IS]->(s), (r)-[:BY]->(a:Artist) RETURN DISTINCT a } AS artist_count,
           COUNT { MATCH (r:Release)-[:IS]->(s), (r)-[:ON]->(l:Label) RETURN DISTINCT l } AS label_count,
           COUNT { MATCH (r:Release)-[:IS]->(s), (r)-[:IS]->(g:Genre) RETURN DISTINCT g } AS genre_count
    """
    return await _run_single(driver, cypher, name=name)


# --- Expand (populate category children) ---


async def _expand_releases(
    driver: AsyncResilientNeo4jDriver, match_clause: str, name: str, limit: int, offset: int, *, before_year: int | None = None
) -> list[dict[str, Any]]:
    """Get paginated releases matching a MATCH clause (shared by artist/genre/label/style)."""
    year_filter = "\n    WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"""
    MATCH {match_clause}{year_filter}
    RETURN r.id AS id, r.title AS name, 'release' AS type,
           CASE WHEN r.year > 0 THEN r.year ELSE null END AS year
    ORDER BY year DESC
    SKIP $offset
    LIMIT $limit
    """
    params: dict[str, Any] = {"name": name, "limit": limit, "offset": offset}
    if before_year:
        params["before_year"] = before_year
    return await _run_query(driver, cypher, **params)


async def expand_artist_releases(
    driver: AsyncResilientNeo4jDriver, artist_name: str, limit: int = 50, offset: int = 0, *, before_year: int | None = None
) -> list[dict[str, Any]]:
    """Get releases by an artist."""
    return await _expand_releases(driver, "(r:Release)-[:BY]->(a:Artist {name: $name})", artist_name, limit, offset, before_year=before_year)


async def expand_artist_labels(
    driver: AsyncResilientNeo4jDriver, artist_name: str, limit: int = 50, offset: int = 0, *, before_year: int | None = None
) -> list[dict[str, Any]]:
    """Get labels associated with an artist via their releases."""
    year_filter = "\n    WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"""
    MATCH (r:Release)-[:BY]->(a:Artist {{name: $name}}), (r)-[:ON]->(l:Label){year_filter}
    RETURN l.id AS id, l.name AS name, 'label' AS type, count(DISTINCT r) AS release_count
    ORDER BY release_count DESC
    SKIP $offset
    LIMIT $limit
    """
    params: dict[str, Any] = {"name": artist_name, "limit": limit, "offset": offset}
    if before_year:
        params["before_year"] = before_year
    return await _run_query(driver, cypher, **params)


async def expand_artist_aliases(
    driver: AsyncResilientNeo4jDriver,
    artist_name: str,
    limit: int = 50,
    offset: int = 0,
    *,
    before_year: int | None = None,  # noqa: ARG001
) -> list[dict[str, Any]]:
    """Get aliases, group memberships, and members for an artist.

    Note: before_year is accepted for API consistency but intentionally ignored —
    aliases are timeless relationships, not bound to release years.
    """
    cypher = """
    MATCH (a:Artist {name: $name})
    OPTIONAL MATCH (a)-[:ALIAS_OF]->(alias:Artist)
    WITH a, collect(DISTINCT {id: alias.id, name: alias.name, type: 'artist'}) AS aliases
    OPTIONAL MATCH (a)-[:MEMBER_OF]->(grp:Artist)
    WITH a, aliases, collect(DISTINCT {id: grp.id, name: grp.name, type: 'artist'}) AS groups
    OPTIONAL MATCH (m:Artist)-[:MEMBER_OF]->(a)
    WITH aliases, groups, collect(DISTINCT {id: m.id, name: m.name, type: 'artist'}) AS members
    UNWIND (aliases + groups + members) AS item
    WITH item WHERE item.id IS NOT NULL
    RETURN DISTINCT item.id AS id, item.name AS name, item.type AS type
    ORDER BY id
    SKIP $offset
    LIMIT $limit
    """
    return await _run_query(driver, cypher, name=artist_name, limit=limit, offset=offset)


async def expand_genre_releases(
    driver: AsyncResilientNeo4jDriver, genre_name: str, limit: int = 50, offset: int = 0, *, before_year: int | None = None
) -> list[dict[str, Any]]:
    """Get releases in a genre."""
    return await _expand_releases(driver, "(r:Release)-[:IS]->(g:Genre {name: $name})", genre_name, limit, offset, before_year=before_year)


async def expand_genre_artists(
    driver: AsyncResilientNeo4jDriver, genre_name: str, limit: int = 50, offset: int = 0, *, before_year: int | None = None
) -> list[dict[str, Any]]:
    """Get artists in a genre (via releases), ordered by release count."""
    year_filter = "\n    WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"""
    MATCH (r:Release)-[:IS]->(g:Genre {{name: $name}}), (r)-[:BY]->(a:Artist){year_filter}
    RETURN a.id AS id, a.name AS name, 'artist' AS type, count(r) AS release_count
    ORDER BY release_count DESC
    SKIP $offset
    LIMIT $limit
    """
    params: dict[str, Any] = {"name": genre_name, "limit": limit, "offset": offset}
    if before_year:
        params["before_year"] = before_year
    return await _run_query(driver, cypher, **params)


async def expand_genre_labels(
    driver: AsyncResilientNeo4jDriver, genre_name: str, limit: int = 50, offset: int = 0, *, before_year: int | None = None
) -> list[dict[str, Any]]:
    """Get labels associated with a genre via releases."""
    year_filter = "\n    WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"""
    MATCH (r:Release)-[:IS]->(g:Genre {{name: $name}}), (r)-[:ON]->(l:Label){year_filter}
    RETURN l.id AS id, l.name AS name, 'label' AS type, count(DISTINCT r) AS release_count
    ORDER BY release_count DESC
    SKIP $offset
    LIMIT $limit
    """
    params: dict[str, Any] = {"name": genre_name, "limit": limit, "offset": offset}
    if before_year:
        params["before_year"] = before_year
    return await _run_query(driver, cypher, **params)


async def expand_genre_styles(driver: AsyncResilientNeo4jDriver, genre_name: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get styles (subgenres) associated with a genre via releases."""
    cypher = """
    MATCH (r:Release)-[:IS]->(g:Genre {name: $name}), (r)-[:IS]->(s:Style)
    RETURN s.name AS id, s.name AS name, 'style' AS type, count(DISTINCT r) AS release_count
    ORDER BY release_count DESC
    SKIP $offset
    LIMIT $limit
    """
    return await _run_query(driver, cypher, name=genre_name, limit=limit, offset=offset)


async def expand_label_releases(driver: AsyncResilientNeo4jDriver, label_name: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get releases on a label."""
    return await _expand_releases(driver, "(r:Release)-[:ON]->(l:Label {name: $name})", label_name, limit, offset)


async def expand_label_artists(driver: AsyncResilientNeo4jDriver, label_name: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get artists on a label."""
    cypher = """
    MATCH (r:Release)-[:ON]->(l:Label {name: $name}), (r)-[:BY]->(a:Artist)
    RETURN a.id AS id, a.name AS name, 'artist' AS type, count(DISTINCT r) AS release_count
    ORDER BY release_count DESC
    SKIP $offset
    LIMIT $limit
    """
    return await _run_query(driver, cypher, name=label_name, limit=limit, offset=offset)


async def expand_label_genres(driver: AsyncResilientNeo4jDriver, label_name: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get genres associated with a label via releases."""
    cypher = """
    MATCH (r:Release)-[:ON]->(l:Label {name: $name}), (r)-[:IS]->(g:Genre)
    RETURN g.name AS id, g.name AS name, 'genre' AS type, count(DISTINCT r) AS release_count
    ORDER BY release_count DESC
    SKIP $offset
    LIMIT $limit
    """
    return await _run_query(driver, cypher, name=label_name, limit=limit, offset=offset)


async def expand_style_releases(driver: AsyncResilientNeo4jDriver, style_name: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get releases in a style."""
    return await _expand_releases(driver, "(r:Release)-[:IS]->(s:Style {name: $name})", style_name, limit, offset)


async def expand_style_artists(driver: AsyncResilientNeo4jDriver, style_name: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get artists in a style (via releases), ordered by release count."""
    cypher = """
    MATCH (r:Release)-[:IS]->(s:Style {name: $name}), (r)-[:BY]->(a:Artist)
    RETURN a.id AS id, a.name AS name, 'artist' AS type, count(r) AS release_count
    ORDER BY release_count DESC
    SKIP $offset
    LIMIT $limit
    """
    return await _run_query(driver, cypher, name=style_name, limit=limit, offset=offset)


async def expand_style_labels(driver: AsyncResilientNeo4jDriver, style_name: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get labels associated with a style via releases."""
    cypher = """
    MATCH (r:Release)-[:IS]->(s:Style {name: $name}), (r)-[:ON]->(l:Label)
    RETURN l.id AS id, l.name AS name, 'label' AS type, count(DISTINCT r) AS release_count
    ORDER BY release_count DESC
    SKIP $offset
    LIMIT $limit
    """
    return await _run_query(driver, cypher, name=style_name, limit=limit, offset=offset)


async def expand_style_genres(driver: AsyncResilientNeo4jDriver, style_name: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get genres associated with a style via releases."""
    cypher = """
    MATCH (r:Release)-[:IS]->(s:Style {name: $name}), (r)-[:IS]->(g:Genre)
    RETURN g.name AS id, g.name AS name, 'genre' AS type, count(DISTINCT r) AS release_count
    ORDER BY release_count DESC
    SKIP $offset
    LIMIT $limit
    """
    return await _run_query(driver, cypher, name=style_name, limit=limit, offset=offset)


# --- Expand counts (for pagination totals) ---


async def count_artist_releases(driver: AsyncResilientNeo4jDriver, artist_name: str, *, before_year: int | None = None) -> int:
    """Count total releases by an artist."""
    year_filter = " WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"MATCH (r:Release)-[:BY]->(a:Artist {{name: $name}}){year_filter} RETURN count(DISTINCT r) AS total"
    params: dict[str, Any] = {"name": artist_name}
    if before_year:
        params["before_year"] = before_year
    return await _run_count(driver, cypher, **params)


async def count_artist_labels(driver: AsyncResilientNeo4jDriver, artist_name: str, *, before_year: int | None = None) -> int:
    """Count total distinct labels associated with an artist."""
    year_filter = "\n    WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"""
    MATCH (r:Release)-[:BY]->(a:Artist {{name: $name}}), (r)-[:ON]->(l:Label){year_filter}
    RETURN count(DISTINCT l) AS total
    """
    params: dict[str, Any] = {"name": artist_name}
    if before_year:
        params["before_year"] = before_year
    return await _run_count(driver, cypher, **params)


async def count_artist_aliases(driver: AsyncResilientNeo4jDriver, artist_name: str, *, before_year: int | None = None) -> int:  # noqa: ARG001
    """Count total aliases, group memberships, and members for an artist."""
    cypher = """
    MATCH (a:Artist {name: $name})
    OPTIONAL MATCH (a)-[:ALIAS_OF]->(alias:Artist)
    WITH a, count(DISTINCT alias) AS alias_count
    OPTIONAL MATCH (a)-[:MEMBER_OF]->(grp:Artist)
    WITH a, alias_count, count(DISTINCT grp) AS group_count
    OPTIONAL MATCH (m:Artist)-[:MEMBER_OF]->(a)
    WITH alias_count, group_count, count(DISTINCT m) AS member_count
    RETURN alias_count + group_count + member_count AS total
    """
    return await _run_count(driver, cypher, name=artist_name)


async def count_genre_releases(driver: AsyncResilientNeo4jDriver, genre_name: str, *, before_year: int | None = None) -> int:
    """Count total releases in a genre."""
    year_filter = " WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"MATCH (r:Release)-[:IS]->(g:Genre {{name: $name}}){year_filter} RETURN count(DISTINCT r) AS total"
    params: dict[str, Any] = {"name": genre_name}
    if before_year:
        params["before_year"] = before_year
    return await _run_count(driver, cypher, **params)


async def count_genre_artists(driver: AsyncResilientNeo4jDriver, genre_name: str, *, before_year: int | None = None) -> int:
    """Count total distinct artists in a genre."""
    year_filter = "\n    WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"""
    MATCH (r:Release)-[:IS]->(g:Genre {{name: $name}}), (r)-[:BY]->(a:Artist){year_filter}
    RETURN count(DISTINCT a) AS total
    """
    params: dict[str, Any] = {"name": genre_name}
    if before_year:
        params["before_year"] = before_year
    return await _run_count(driver, cypher, **params)


async def count_genre_labels(driver: AsyncResilientNeo4jDriver, genre_name: str, *, before_year: int | None = None) -> int:
    """Count total distinct labels associated with a genre."""
    year_filter = "\n    WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"""
    MATCH (r:Release)-[:IS]->(g:Genre {{name: $name}}), (r)-[:ON]->(l:Label){year_filter}
    RETURN count(DISTINCT l) AS total
    """
    params: dict[str, Any] = {"name": genre_name}
    if before_year:
        params["before_year"] = before_year
    return await _run_count(driver, cypher, **params)


async def count_genre_styles(driver: AsyncResilientNeo4jDriver, genre_name: str, *, before_year: int | None = None) -> int:
    """Count total distinct styles associated with a genre."""
    year_filter = "\n    WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"""
    MATCH (r:Release)-[:IS]->(g:Genre {{name: $name}}), (r)-[:IS]->(s:Style){year_filter}
    RETURN count(DISTINCT s) AS total
    """
    params: dict[str, Any] = {"name": genre_name}
    if before_year:
        params["before_year"] = before_year
    return await _run_count(driver, cypher, **params)


async def count_label_releases(driver: AsyncResilientNeo4jDriver, label_name: str, *, before_year: int | None = None) -> int:
    """Count total releases on a label."""
    year_filter = " WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"MATCH (r:Release)-[:ON]->(l:Label {{name: $name}}){year_filter} RETURN count(DISTINCT r) AS total"
    params: dict[str, Any] = {"name": label_name}
    if before_year:
        params["before_year"] = before_year
    return await _run_count(driver, cypher, **params)


async def count_label_artists(driver: AsyncResilientNeo4jDriver, label_name: str, *, before_year: int | None = None) -> int:
    """Count total distinct artists on a label."""
    year_filter = "\n    WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"""
    MATCH (r:Release)-[:ON]->(l:Label {{name: $name}}), (r)-[:BY]->(a:Artist){year_filter}
    RETURN count(DISTINCT a) AS total
    """
    params: dict[str, Any] = {"name": label_name}
    if before_year:
        params["before_year"] = before_year
    return await _run_count(driver, cypher, **params)


async def count_label_genres(driver: AsyncResilientNeo4jDriver, label_name: str, *, before_year: int | None = None) -> int:
    """Count total distinct genres associated with a label."""
    year_filter = "\n    WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"""
    MATCH (r:Release)-[:ON]->(l:Label {{name: $name}}), (r)-[:IS]->(g:Genre){year_filter}
    RETURN count(DISTINCT g) AS total
    """
    params: dict[str, Any] = {"name": label_name}
    if before_year:
        params["before_year"] = before_year
    return await _run_count(driver, cypher, **params)


async def count_style_releases(driver: AsyncResilientNeo4jDriver, style_name: str, *, before_year: int | None = None) -> int:
    """Count total releases in a style."""
    year_filter = " WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"MATCH (r:Release)-[:IS]->(s:Style {{name: $name}}){year_filter} RETURN count(DISTINCT r) AS total"
    params: dict[str, Any] = {"name": style_name}
    if before_year:
        params["before_year"] = before_year
    return await _run_count(driver, cypher, **params)


async def count_style_artists(driver: AsyncResilientNeo4jDriver, style_name: str, *, before_year: int | None = None) -> int:
    """Count total distinct artists in a style."""
    year_filter = "\n    WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"""
    MATCH (r:Release)-[:IS]->(s:Style {{name: $name}}), (r)-[:BY]->(a:Artist){year_filter}
    RETURN count(DISTINCT a) AS total
    """
    params: dict[str, Any] = {"name": style_name}
    if before_year:
        params["before_year"] = before_year
    return await _run_count(driver, cypher, **params)


async def count_style_labels(driver: AsyncResilientNeo4jDriver, style_name: str, *, before_year: int | None = None) -> int:
    """Count total distinct labels associated with a style."""
    year_filter = "\n    WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"""
    MATCH (r:Release)-[:IS]->(s:Style {{name: $name}}), (r)-[:ON]->(l:Label){year_filter}
    RETURN count(DISTINCT l) AS total
    """
    params: dict[str, Any] = {"name": style_name}
    if before_year:
        params["before_year"] = before_year
    return await _run_count(driver, cypher, **params)


async def count_style_genres(driver: AsyncResilientNeo4jDriver, style_name: str, *, before_year: int | None = None) -> int:
    """Count total distinct genres associated with a style."""
    year_filter = "\n    WHERE r.year <= $before_year AND r.year > 0" if before_year else ""
    cypher = f"""
    MATCH (r:Release)-[:IS]->(s:Style {{name: $name}}), (r)-[:IS]->(g:Genre){year_filter}
    RETURN count(DISTINCT g) AS total
    """
    params: dict[str, Any] = {"name": style_name}
    if before_year:
        params["before_year"] = before_year
    return await _run_count(driver, cypher, **params)


# --- Node Details ---


async def get_artist_details(driver: AsyncResilientNeo4jDriver, node_id: str) -> dict[str, Any] | None:
    """Get full details for an artist node."""
    cypher = """
    MATCH (a:Artist {id: $id})
    OPTIONAL MATCH (r:Release)-[:BY]->(a)
    OPTIONAL MATCH (r)-[:IS]->(g:Genre)
    OPTIONAL MATCH (r)-[:IS]->(s:Style)
    WITH a, count(DISTINCT r) AS release_count,
         collect(DISTINCT g.name) AS genres,
         collect(DISTINCT s.name) AS styles
    OPTIONAL MATCH (a)-[:MEMBER_OF]->(grp:Artist)
    RETURN a.id AS id, a.name AS name, genres, styles, release_count,
           collect(DISTINCT grp.name) AS groups
    """
    return await _run_single(driver, cypher, id=node_id)


async def get_release_details(driver: AsyncResilientNeo4jDriver, node_id: str) -> dict[str, Any] | None:
    """Get full details for a release node."""
    cypher = """
    MATCH (r:Release {id: $id})
    OPTIONAL MATCH (r)-[:BY]->(a:Artist)
    WITH r, collect(DISTINCT a.name) AS artists
    OPTIONAL MATCH (r)-[:ON]->(l:Label)
    WITH r, artists, collect(DISTINCT l.name) AS labels
    OPTIONAL MATCH (r)-[:IS]->(g:Genre)
    WITH r, artists, labels, collect(DISTINCT g.name) AS genres
    OPTIONAL MATCH (r)-[:IS]->(s:Style)
    WITH r, artists, labels, genres, collect(DISTINCT s.name) AS styles
    RETURN r.id AS id, r.title AS name,
           CASE WHEN r.year > 0 THEN r.year ELSE null END AS year,
           artists, labels, genres, styles
    """
    return await _run_single(driver, cypher, id=node_id)


async def get_label_details(driver: AsyncResilientNeo4jDriver, node_id: str) -> dict[str, Any] | None:
    """Get full details for a label node."""
    cypher = """
    MATCH (l:Label {id: $id})
    OPTIONAL MATCH (r:Release)-[:ON]->(l)
    WITH l, count(DISTINCT r) AS release_count
    RETURN l.id AS id, l.name AS name, release_count
    """
    return await _run_single(driver, cypher, id=node_id)


async def get_genre_details(driver: AsyncResilientNeo4jDriver, node_id: str) -> dict[str, Any] | None:
    """Get full details for a genre node."""
    cypher = """
    MATCH (g:Genre {name: $id})
    OPTIONAL MATCH (r:Release)-[:IS]->(g), (r)-[:BY]->(a:Artist)
    WITH g, count(DISTINCT a) AS artist_count
    RETURN g.name AS id, g.name AS name, artist_count
    """
    return await _run_single(driver, cypher, id=node_id)


async def get_style_details(driver: AsyncResilientNeo4jDriver, node_id: str) -> dict[str, Any] | None:
    """Get full details for a style node."""
    cypher = """
    MATCH (s:Style {name: $id})
    OPTIONAL MATCH (r:Release)-[:IS]->(s), (r)-[:BY]->(a:Artist)
    WITH s, count(DISTINCT a) AS artist_count
    RETURN s.name AS id, s.name AS name, artist_count
    """
    return await _run_single(driver, cypher, id=node_id)


# --- Trends (time-series) ---


async def trends_artist(driver: AsyncResilientNeo4jDriver, name: str) -> list[dict[str, Any]]:
    """Get release count by year for an artist."""
    cypher = """
    MATCH (r:Release)-[:BY]->(a:Artist {name: $name})
    WHERE r.year > 0
    WITH r.year AS year, count(DISTINCT r) AS count
    RETURN year, count
    ORDER BY year
    """
    return await _run_query(driver, cypher, name=name)


async def trends_genre(driver: AsyncResilientNeo4jDriver, name: str) -> list[dict[str, Any]]:
    """Get release count by year for a genre."""
    cypher = """
    MATCH (r:Release)-[:IS]->(g:Genre {name: $name})
    WHERE r.year > 0
    WITH r.year AS year, count(DISTINCT r) AS count
    RETURN year, count
    ORDER BY year
    """
    return await _run_query(driver, cypher, name=name)


async def trends_label(driver: AsyncResilientNeo4jDriver, name: str) -> list[dict[str, Any]]:
    """Get release count by year for a label."""
    cypher = """
    MATCH (r:Release)-[:ON]->(l:Label {name: $name})
    WHERE r.year > 0
    WITH r.year AS year, count(DISTINCT r) AS count
    RETURN year, count
    ORDER BY year
    """
    return await _run_query(driver, cypher, name=name)


async def trends_style(driver: AsyncResilientNeo4jDriver, name: str) -> list[dict[str, Any]]:
    """Get release count by year for a style."""
    cypher = """
    MATCH (r:Release)-[:IS]->(s:Style {name: $name})
    WHERE r.year > 0
    WITH r.year AS year, count(DISTINCT r) AS count
    RETURN year, count
    ORDER BY year
    """
    return await _run_query(driver, cypher, name=name)


# --- Year range and genre emergence ---


async def get_year_range(driver: AsyncResilientNeo4jDriver) -> dict[str, int] | None:
    """Get min/max release year across all Release nodes."""
    cypher = """
    MATCH (r:Release) WHERE r.year > 0
    RETURN min(r.year) AS min_year, max(r.year) AS max_year
    """
    return await _run_single(driver, cypher)


async def get_genre_emergence(driver: AsyncResilientNeo4jDriver, before_year: int) -> dict[str, list[dict[str, Any]]]:
    """Get genres and styles with their first appearance year, up to before_year."""
    genre_cypher = """
    MATCH (r:Release)-[:IS]->(g:Genre)
    WHERE r.year > 0 AND r.year <= $before_year
    WITH g.name AS name, min(r.year) AS first_year
    RETURN name, first_year
    ORDER BY first_year
    """
    style_cypher = """
    MATCH (r:Release)-[:IS]->(s:Style)
    WHERE r.year > 0 AND r.year <= $before_year
    WITH s.name AS name, min(r.year) AS first_year
    RETURN name, first_year
    ORDER BY first_year
    """
    genres = await _run_query(driver, genre_cypher, before_year=before_year)
    styles = await _run_query(driver, style_cypher, before_year=before_year)
    return {"genres": genres, "styles": styles}


# --- Dispatch helpers ---

EXPLORE_DISPATCH: dict[str, Any] = {
    "artist": explore_artist,
    "genre": explore_genre,
    "label": explore_label,
    "style": explore_style,
}

AUTOCOMPLETE_DISPATCH: dict[str, Any] = {
    "artist": autocomplete_artist,
    "genre": autocomplete_genre,
    "label": autocomplete_label,
    "style": autocomplete_style,
}

EXPAND_DISPATCH: dict[str, dict[str, Any]] = {
    "artist": {
        "releases": expand_artist_releases,
        "labels": expand_artist_labels,
        "aliases": expand_artist_aliases,
    },
    "genre": {
        "releases": expand_genre_releases,
        "artists": expand_genre_artists,
        "labels": expand_genre_labels,
        "styles": expand_genre_styles,
    },
    "label": {
        "releases": expand_label_releases,
        "artists": expand_label_artists,
        "genres": expand_label_genres,
    },
    "style": {
        "releases": expand_style_releases,
        "artists": expand_style_artists,
        "labels": expand_style_labels,
        "genres": expand_style_genres,
    },
}

COUNT_DISPATCH: dict[str, dict[str, Any]] = {
    "artist": {
        "releases": count_artist_releases,
        "labels": count_artist_labels,
        "aliases": count_artist_aliases,
    },
    "genre": {
        "releases": count_genre_releases,
        "artists": count_genre_artists,
        "labels": count_genre_labels,
        "styles": count_genre_styles,
    },
    "label": {
        "releases": count_label_releases,
        "artists": count_label_artists,
        "genres": count_label_genres,
    },
    "style": {
        "releases": count_style_releases,
        "artists": count_style_artists,
        "labels": count_style_labels,
        "genres": count_style_genres,
    },
}

DETAILS_DISPATCH: dict[str, Any] = {
    "artist": get_artist_details,
    "release": get_release_details,
    "label": get_label_details,
    "genre": get_genre_details,
    "style": get_style_details,
}

TRENDS_DISPATCH: dict[str, Any] = {
    "artist": trends_artist,
    "genre": trends_genre,
    "label": trends_label,
    "style": trends_style,
}

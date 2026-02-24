"""Neo4j Cypher queries for Explore service.

All database queries are defined here to keep the API layer thin.

Graph model reference:
  (Release)-[:BY]->(Artist)         Release is by Artist
  (Release)-[:ON]->(Label)          Release is on Label
  (Release)-[:IS]->(Genre)          Release is genre
  (Release)-[:IS]->(Style)          Release is style
  (Release)-[:DERIVED_FROM]->(Master)  Release derived from Master (Master has year)
  (Artist)-[:ALIAS_OF]->(Artist)    Artist alias
  (Artist)-[:MEMBER_OF]->(Artist)   Artist is member of group
"""

import re
from typing import Any

from common import AsyncResilientNeo4jDriver


# Lucene special characters that must be escaped in fulltext queries
_LUCENE_SPECIAL_RE = re.compile(r'([+\-&|!(){}[\]^"~*?:\\/ ])')


def _escape_lucene_query(query: str) -> str:
    """Escape Lucene special characters in a fulltext search query."""
    return _LUCENE_SPECIAL_RE.sub(r"\\\1", query)


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


# --- Autocomplete ---


async def autocomplete_artist(driver: AsyncResilientNeo4jDriver, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search artists by name using fulltext index."""
    escaped = _escape_lucene_query(query)
    cypher = """
    CALL db.index.fulltext.queryNodes('artist_name_fulltext', $query)
    YIELD node, score
    RETURN node.id AS id, node.name AS name, score
    ORDER BY score DESC
    LIMIT $limit
    """
    return await _run_query(driver, cypher, query=escaped + "*", limit=limit)


async def autocomplete_label(driver: AsyncResilientNeo4jDriver, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search labels by name using fulltext index."""
    escaped = _escape_lucene_query(query)
    cypher = """
    CALL db.index.fulltext.queryNodes('label_name_fulltext', $query)
    YIELD node, score
    RETURN node.id AS id, node.name AS name, score
    ORDER BY score DESC
    LIMIT $limit
    """
    return await _run_query(driver, cypher, query=escaped + "*", limit=limit)


async def _autocomplete_prefix(driver: AsyncResilientNeo4jDriver, label: str, query: str, limit: int) -> list[dict[str, Any]]:
    """Search nodes by name prefix (used for Genre and Style which lack fulltext indexes)."""
    cypher = f"""
    MATCH (n:{label})
    WHERE toLower(n.name) STARTS WITH toLower($query)
    RETURN n.name AS id, n.name AS name, 1.0 AS score
    ORDER BY n.name
    LIMIT $limit
    """
    return await _run_query(driver, cypher, query=query, limit=limit)


async def autocomplete_genre(driver: AsyncResilientNeo4jDriver, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search genres by name prefix."""
    return await _autocomplete_prefix(driver, "Genre", query, limit)


async def autocomplete_style(driver: AsyncResilientNeo4jDriver, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search styles by name prefix."""
    return await _autocomplete_prefix(driver, "Style", query, limit)


# --- Explore (center node + category nodes) ---


async def explore_artist(driver: AsyncResilientNeo4jDriver, name: str) -> dict[str, Any] | None:
    """Get artist center node with category counts."""
    cypher = """
    MATCH (a:Artist {name: $name})
    OPTIONAL MATCH (r:Release)-[:BY]->(a)
    WITH a, count(DISTINCT r) AS release_count
    OPTIONAL MATCH (r2:Release)-[:BY]->(a), (r2)-[:ON]->(l:Label)
    WITH a, release_count, count(DISTINCT l) AS label_count
    OPTIONAL MATCH (a)-[:ALIAS_OF]->(alias:Artist)
    WITH a, release_count, label_count, count(DISTINCT alias) AS alias_count
    OPTIONAL MATCH (a)-[:MEMBER_OF]->(grp:Artist)
    WITH a, release_count, label_count, alias_count, count(DISTINCT grp) AS group_count
    OPTIONAL MATCH (m:Artist)-[:MEMBER_OF]->(a)
    WITH a, release_count, label_count, alias_count, group_count, count(DISTINCT m) AS member_count
    RETURN a.id AS id, a.name AS name,
           release_count, label_count, alias_count + group_count + member_count AS alias_count
    """
    return await _run_single(driver, cypher, name=name)


async def explore_genre(driver: AsyncResilientNeo4jDriver, name: str) -> dict[str, Any] | None:
    """Get genre center node with category counts."""
    cypher = """
    MATCH (g:Genre {name: $name})
    OPTIONAL MATCH (r:Release)-[:IS]->(g)
    WITH g, count(DISTINCT r) AS release_count
    OPTIONAL MATCH (r2:Release)-[:IS]->(g), (r2)-[:BY]->(a:Artist)
    WITH g, release_count, count(DISTINCT a) AS artist_count
    OPTIONAL MATCH (r3:Release)-[:IS]->(g), (r3)-[:ON]->(l:Label)
    WITH g, release_count, artist_count, count(DISTINCT l) AS label_count
    OPTIONAL MATCH (r4:Release)-[:IS]->(g), (r4)-[:IS]->(s:Style)
    WITH g, release_count, artist_count, label_count, count(DISTINCT s) AS style_count
    RETURN g.name AS id, g.name AS name,
           release_count, artist_count, label_count, style_count
    """
    return await _run_single(driver, cypher, name=name)


async def explore_label(driver: AsyncResilientNeo4jDriver, name: str) -> dict[str, Any] | None:
    """Get label center node with category counts."""
    cypher = """
    MATCH (l:Label {name: $name})
    OPTIONAL MATCH (r:Release)-[:ON]->(l)
    WITH l, count(DISTINCT r) AS release_count
    OPTIONAL MATCH (r2:Release)-[:ON]->(l), (r2)-[:BY]->(a:Artist)
    WITH l, release_count, count(DISTINCT a) AS artist_count
    OPTIONAL MATCH (r3:Release)-[:ON]->(l), (r3)-[:IS]->(g:Genre)
    WITH l, release_count, artist_count, count(DISTINCT g) AS genre_count
    RETURN l.id AS id, l.name AS name,
           release_count, artist_count, genre_count
    """
    return await _run_single(driver, cypher, name=name)


async def explore_style(driver: AsyncResilientNeo4jDriver, name: str) -> dict[str, Any] | None:
    """Get style center node with category counts."""
    cypher = """
    MATCH (s:Style {name: $name})
    OPTIONAL MATCH (r:Release)-[:IS]->(s)
    WITH s, count(DISTINCT r) AS release_count
    OPTIONAL MATCH (r2:Release)-[:IS]->(s), (r2)-[:BY]->(a:Artist)
    WITH s, release_count, count(DISTINCT a) AS artist_count
    OPTIONAL MATCH (r3:Release)-[:IS]->(s), (r3)-[:ON]->(l:Label)
    WITH s, release_count, artist_count, count(DISTINCT l) AS label_count
    OPTIONAL MATCH (r4:Release)-[:IS]->(s), (r4)-[:IS]->(g:Genre)
    WITH s, release_count, artist_count, label_count, count(DISTINCT g) AS genre_count
    RETURN s.name AS id, s.name AS name,
           release_count, artist_count, label_count, genre_count
    """
    return await _run_single(driver, cypher, name=name)


# --- Expand (populate category children) ---


async def _expand_releases(driver: AsyncResilientNeo4jDriver, match_clause: str, name: str, limit: int, offset: int) -> list[dict[str, Any]]:
    """Get paginated releases matching a MATCH clause (shared by artist/genre/label/style)."""
    cypher = f"""
    MATCH {match_clause}
    OPTIONAL MATCH (r)-[:DERIVED_FROM]->(m:Master)
    WITH r, m.year AS year
    RETURN r.id AS id, r.title AS name, 'release' AS type,
           CASE WHEN toInteger(year) > 0 THEN toInteger(year) ELSE null END AS year
    ORDER BY year DESC
    SKIP $offset
    LIMIT $limit
    """
    return await _run_query(driver, cypher, name=name, limit=limit, offset=offset)


async def expand_artist_releases(driver: AsyncResilientNeo4jDriver, artist_name: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get releases by an artist."""
    return await _expand_releases(driver, "(r:Release)-[:BY]->(a:Artist {name: $name})", artist_name, limit, offset)


async def expand_artist_labels(driver: AsyncResilientNeo4jDriver, artist_name: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get labels associated with an artist via their releases."""
    cypher = """
    MATCH (r:Release)-[:BY]->(a:Artist {name: $name}), (r)-[:ON]->(l:Label)
    RETURN l.id AS id, l.name AS name, 'label' AS type, count(DISTINCT r) AS release_count
    ORDER BY release_count DESC
    SKIP $offset
    LIMIT $limit
    """
    return await _run_query(driver, cypher, name=artist_name, limit=limit, offset=offset)


async def expand_artist_aliases(driver: AsyncResilientNeo4jDriver, artist_name: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get aliases, group memberships, and members for an artist."""
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


async def expand_genre_releases(driver: AsyncResilientNeo4jDriver, genre_name: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get releases in a genre."""
    return await _expand_releases(driver, "(r:Release)-[:IS]->(g:Genre {name: $name})", genre_name, limit, offset)


async def expand_genre_artists(driver: AsyncResilientNeo4jDriver, genre_name: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get artists in a genre (via releases)."""
    cypher = """
    MATCH (r:Release)-[:IS]->(g:Genre {name: $name}), (r)-[:BY]->(a:Artist)
    RETURN DISTINCT a.id AS id, a.name AS name, 'artist' AS type
    ORDER BY a.name
    SKIP $offset
    LIMIT $limit
    """
    return await _run_query(driver, cypher, name=genre_name, limit=limit, offset=offset)


async def expand_genre_labels(driver: AsyncResilientNeo4jDriver, genre_name: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get labels associated with a genre via releases."""
    cypher = """
    MATCH (r:Release)-[:IS]->(g:Genre {name: $name}), (r)-[:ON]->(l:Label)
    RETURN l.id AS id, l.name AS name, 'label' AS type, count(DISTINCT r) AS release_count
    ORDER BY release_count DESC
    SKIP $offset
    LIMIT $limit
    """
    return await _run_query(driver, cypher, name=genre_name, limit=limit, offset=offset)


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
    """Get artists in a style (via releases)."""
    cypher = """
    MATCH (r:Release)-[:IS]->(s:Style {name: $name}), (r)-[:BY]->(a:Artist)
    RETURN DISTINCT a.id AS id, a.name AS name, 'artist' AS type
    ORDER BY a.name
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


async def count_artist_releases(driver: AsyncResilientNeo4jDriver, artist_name: str) -> int:
    """Count total releases by an artist."""
    cypher = "MATCH (r:Release)-[:BY]->(a:Artist {name: $name}) RETURN count(DISTINCT r) AS total"
    return await _run_count(driver, cypher, name=artist_name)


async def count_artist_labels(driver: AsyncResilientNeo4jDriver, artist_name: str) -> int:
    """Count total distinct labels associated with an artist."""
    cypher = """
    MATCH (r:Release)-[:BY]->(a:Artist {name: $name}), (r)-[:ON]->(l:Label)
    RETURN count(DISTINCT l) AS total
    """
    return await _run_count(driver, cypher, name=artist_name)


async def count_artist_aliases(driver: AsyncResilientNeo4jDriver, artist_name: str) -> int:
    """Count total aliases, group memberships, and members for an artist."""
    cypher = """
    MATCH (a:Artist {name: $name})
    OPTIONAL MATCH (a)-[:ALIAS_OF]->(alias:Artist)
    WITH a, count(DISTINCT alias) AS alias_count
    OPTIONAL MATCH (a)-[:MEMBER_OF]->(grp:Artist)
    WITH a, alias_count, count(DISTINCT grp) AS group_count
    OPTIONAL MATCH (m:Artist)-[:MEMBER_OF]->(a)
    RETURN alias_count + group_count + count(DISTINCT m) AS total
    """
    return await _run_count(driver, cypher, name=artist_name)


async def count_genre_releases(driver: AsyncResilientNeo4jDriver, genre_name: str) -> int:
    """Count total releases in a genre."""
    cypher = "MATCH (r:Release)-[:IS]->(g:Genre {name: $name}) RETURN count(DISTINCT r) AS total"
    return await _run_count(driver, cypher, name=genre_name)


async def count_genre_artists(driver: AsyncResilientNeo4jDriver, genre_name: str) -> int:
    """Count total distinct artists in a genre."""
    cypher = """
    MATCH (r:Release)-[:IS]->(g:Genre {name: $name}), (r)-[:BY]->(a:Artist)
    RETURN count(DISTINCT a) AS total
    """
    return await _run_count(driver, cypher, name=genre_name)


async def count_genre_labels(driver: AsyncResilientNeo4jDriver, genre_name: str) -> int:
    """Count total distinct labels associated with a genre."""
    cypher = """
    MATCH (r:Release)-[:IS]->(g:Genre {name: $name}), (r)-[:ON]->(l:Label)
    RETURN count(DISTINCT l) AS total
    """
    return await _run_count(driver, cypher, name=genre_name)


async def count_genre_styles(driver: AsyncResilientNeo4jDriver, genre_name: str) -> int:
    """Count total distinct styles associated with a genre."""
    cypher = """
    MATCH (r:Release)-[:IS]->(g:Genre {name: $name}), (r)-[:IS]->(s:Style)
    RETURN count(DISTINCT s) AS total
    """
    return await _run_count(driver, cypher, name=genre_name)


async def count_label_releases(driver: AsyncResilientNeo4jDriver, label_name: str) -> int:
    """Count total releases on a label."""
    cypher = "MATCH (r:Release)-[:ON]->(l:Label {name: $name}) RETURN count(DISTINCT r) AS total"
    return await _run_count(driver, cypher, name=label_name)


async def count_label_artists(driver: AsyncResilientNeo4jDriver, label_name: str) -> int:
    """Count total distinct artists on a label."""
    cypher = """
    MATCH (r:Release)-[:ON]->(l:Label {name: $name}), (r)-[:BY]->(a:Artist)
    RETURN count(DISTINCT a) AS total
    """
    return await _run_count(driver, cypher, name=label_name)


async def count_label_genres(driver: AsyncResilientNeo4jDriver, label_name: str) -> int:
    """Count total distinct genres associated with a label."""
    cypher = """
    MATCH (r:Release)-[:ON]->(l:Label {name: $name}), (r)-[:IS]->(g:Genre)
    RETURN count(DISTINCT g) AS total
    """
    return await _run_count(driver, cypher, name=label_name)


async def count_style_releases(driver: AsyncResilientNeo4jDriver, style_name: str) -> int:
    """Count total releases in a style."""
    cypher = "MATCH (r:Release)-[:IS]->(s:Style {name: $name}) RETURN count(DISTINCT r) AS total"
    return await _run_count(driver, cypher, name=style_name)


async def count_style_artists(driver: AsyncResilientNeo4jDriver, style_name: str) -> int:
    """Count total distinct artists in a style."""
    cypher = """
    MATCH (r:Release)-[:IS]->(s:Style {name: $name}), (r)-[:BY]->(a:Artist)
    RETURN count(DISTINCT a) AS total
    """
    return await _run_count(driver, cypher, name=style_name)


async def count_style_labels(driver: AsyncResilientNeo4jDriver, style_name: str) -> int:
    """Count total distinct labels associated with a style."""
    cypher = """
    MATCH (r:Release)-[:IS]->(s:Style {name: $name}), (r)-[:ON]->(l:Label)
    RETURN count(DISTINCT l) AS total
    """
    return await _run_count(driver, cypher, name=style_name)


async def count_style_genres(driver: AsyncResilientNeo4jDriver, style_name: str) -> int:
    """Count total distinct genres associated with a style."""
    cypher = """
    MATCH (r:Release)-[:IS]->(s:Style {name: $name}), (r)-[:IS]->(g:Genre)
    RETURN count(DISTINCT g) AS total
    """
    return await _run_count(driver, cypher, name=style_name)


# --- Node Details ---


async def get_artist_details(driver: AsyncResilientNeo4jDriver, node_id: str) -> dict[str, Any] | None:
    """Get full details for an artist node."""
    cypher = """
    MATCH (a:Artist) WHERE a.id = $id OR a.name = $id
    OPTIONAL MATCH (r:Release)-[:BY]->(a), (r)-[:IS]->(g:Genre)
    WITH a, collect(DISTINCT g.name) AS genres
    OPTIONAL MATCH (r2:Release)-[:BY]->(a), (r2)-[:IS]->(s:Style)
    WITH a, genres, collect(DISTINCT s.name) AS styles
    OPTIONAL MATCH (r3:Release)-[:BY]->(a)
    WITH a, genres, styles, count(DISTINCT r3) AS release_count
    OPTIONAL MATCH (a)-[:MEMBER_OF]->(grp:Artist)
    WITH a, genres, styles, release_count, collect(DISTINCT grp.name) AS groups
    RETURN a.id AS id, a.name AS name, genres, styles, release_count, groups
    """
    return await _run_single(driver, cypher, id=node_id)


async def get_release_details(driver: AsyncResilientNeo4jDriver, node_id: str) -> dict[str, Any] | None:
    """Get full details for a release node."""
    cypher = """
    MATCH (r:Release) WHERE r.id = $id OR r.title = $id
    OPTIONAL MATCH (r)-[:BY]->(a:Artist)
    WITH r, collect(DISTINCT a.name) AS artists
    OPTIONAL MATCH (r)-[:ON]->(l:Label)
    WITH r, artists, collect(DISTINCT l.name) AS labels
    OPTIONAL MATCH (r)-[:IS]->(g:Genre)
    WITH r, artists, labels, collect(DISTINCT g.name) AS genres
    OPTIONAL MATCH (r)-[:IS]->(s:Style)
    WITH r, artists, labels, genres, collect(DISTINCT s.name) AS styles
    OPTIONAL MATCH (r)-[:DERIVED_FROM]->(m:Master)
    WITH r, artists, labels, genres, styles,
         CASE WHEN toInteger(m.year) > 0 THEN toInteger(m.year) ELSE null END AS year
    RETURN r.id AS id, r.title AS name, year,
           artists, labels, genres, styles
    """
    return await _run_single(driver, cypher, id=node_id)


async def get_label_details(driver: AsyncResilientNeo4jDriver, node_id: str) -> dict[str, Any] | None:
    """Get full details for a label node."""
    cypher = """
    MATCH (l:Label) WHERE l.id = $id OR l.name = $id
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
    """Get release count by year for an artist (year from Master)."""
    cypher = """
    MATCH (r:Release)-[:BY]->(a:Artist {name: $name}),
          (r)-[:DERIVED_FROM]->(m:Master)
    WHERE toInteger(m.year) > 0
    WITH toInteger(m.year) AS year, count(DISTINCT r) AS count
    RETURN year, count
    ORDER BY year
    """
    return await _run_query(driver, cypher, name=name)


async def trends_genre(driver: AsyncResilientNeo4jDriver, name: str) -> list[dict[str, Any]]:
    """Get release count by year for a genre (year from Master)."""
    cypher = """
    MATCH (r:Release)-[:IS]->(g:Genre {name: $name}),
          (r)-[:DERIVED_FROM]->(m:Master)
    WHERE toInteger(m.year) > 0
    WITH toInteger(m.year) AS year, count(DISTINCT r) AS count
    RETURN year, count
    ORDER BY year
    """
    return await _run_query(driver, cypher, name=name)


async def trends_label(driver: AsyncResilientNeo4jDriver, name: str) -> list[dict[str, Any]]:
    """Get release count by year for a label (year from Master)."""
    cypher = """
    MATCH (r:Release)-[:ON]->(l:Label {name: $name}),
          (r)-[:DERIVED_FROM]->(m:Master)
    WHERE toInteger(m.year) > 0
    WITH toInteger(m.year) AS year, count(DISTINCT r) AS count
    RETURN year, count
    ORDER BY year
    """
    return await _run_query(driver, cypher, name=name)


async def trends_style(driver: AsyncResilientNeo4jDriver, name: str) -> list[dict[str, Any]]:
    """Get release count by year for a style (year from Master)."""
    cypher = """
    MATCH (r:Release)-[:IS]->(s:Style {name: $name}),
          (r)-[:DERIVED_FROM]->(m:Master)
    WHERE toInteger(m.year) > 0
    WITH toInteger(m.year) AS year, count(DISTINCT r) AS count
    RETURN year, count
    ORDER BY year
    """
    return await _run_query(driver, cypher, name=name)


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

"""Neo4j Cypher queries for Explore service.

All database queries are defined here to keep the API layer thin.
"""

from functools import lru_cache
from typing import Any

from common import AsyncResilientNeo4jDriver


# --- Autocomplete ---


async def autocomplete_artist(driver: AsyncResilientNeo4jDriver, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search artists by name using fulltext index."""
    cypher = """
    CALL db.index.fulltext.queryNodes('artist_name_fulltext', $query + '*')
    YIELD node, score
    RETURN node.id AS id, node.name AS name, score
    ORDER BY score DESC
    LIMIT $limit
    """
    async with await driver.session() as session:
        result = await session.run(cypher, parameters={"query": query, "limit": limit})
        return [dict(record) async for record in result]


async def autocomplete_label(driver: AsyncResilientNeo4jDriver, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search labels by name using fulltext index."""
    cypher = """
    CALL db.index.fulltext.queryNodes('label_name_fulltext', $query + '*')
    YIELD node, score
    RETURN node.id AS id, node.name AS name, score
    ORDER BY score DESC
    LIMIT $limit
    """
    async with await driver.session() as session:
        result = await session.run(cypher, parameters={"query": query, "limit": limit})
        return [dict(record) async for record in result]


async def autocomplete_genre(driver: AsyncResilientNeo4jDriver, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search genres by name prefix."""
    cypher = """
    MATCH (g:Genre)
    WHERE toLower(g.name) STARTS WITH toLower($query)
    RETURN g.name AS id, g.name AS name, 1.0 AS score
    ORDER BY g.name
    LIMIT $limit
    """
    async with await driver.session() as session:
        result = await session.run(cypher, parameters={"query": query, "limit": limit})
        return [dict(record) async for record in result]


# --- Explore (center node + category nodes) ---


async def explore_artist(driver: AsyncResilientNeo4jDriver, name: str) -> dict[str, Any] | None:
    """Get artist center node with category counts."""
    cypher = """
    MATCH (a:Artist {name: $name})
    OPTIONAL MATCH (a)-[:BY]->(r:Release)
    WITH a, count(DISTINCT r) AS release_count
    OPTIONAL MATCH (a)-[:BY]->(r2:Release)-[:ON]->(l:Label)
    WITH a, release_count, count(DISTINCT l) AS label_count
    OPTIONAL MATCH (a)-[:MEMBER_OF]->(g:Artist)
    WITH a, release_count, label_count, count(DISTINCT g) AS alias_count
    OPTIONAL MATCH (a2:Artist)-[:MEMBER_OF]->(a)
    WITH a, release_count, label_count, alias_count + count(DISTINCT a2) AS alias_count
    RETURN a.id AS id, a.name AS name,
           release_count, label_count, alias_count
    """
    async with await driver.session() as session:
        result = await session.run(cypher, name=name)
        record = await result.single()
        if not record:
            return None
        return dict(record)


async def explore_genre(driver: AsyncResilientNeo4jDriver, name: str) -> dict[str, Any] | None:
    """Get genre center node with category counts."""
    cypher = """
    MATCH (g:Genre {name: $name})
    OPTIONAL MATCH (a:Artist)-[:IS]->(g)
    WITH g, count(DISTINCT a) AS artist_count
    OPTIONAL MATCH (a2:Artist)-[:IS]->(g), (a2)-[:BY]->(r:Release)-[:ON]->(l:Label)
    WITH g, artist_count, count(DISTINCT l) AS label_count
    OPTIONAL MATCH (a3:Artist)-[:IS]->(g), (a3)-[:IS]->(s:Style)
    WITH g, artist_count, label_count, count(DISTINCT s) AS style_count
    RETURN g.name AS id, g.name AS name,
           artist_count, label_count, style_count
    """
    async with await driver.session() as session:
        result = await session.run(cypher, name=name)
        record = await result.single()
        if not record:
            return None
        return dict(record)


async def explore_label(driver: AsyncResilientNeo4jDriver, name: str) -> dict[str, Any] | None:
    """Get label center node with category counts."""
    cypher = """
    MATCH (l:Label {name: $name})
    OPTIONAL MATCH (r:Release)-[:ON]->(l)
    WITH l, count(DISTINCT r) AS release_count
    OPTIONAL MATCH (a:Artist)-[:BY]->(r2:Release)-[:ON]->(l)
    WITH l, release_count, count(DISTINCT a) AS artist_count
    RETURN l.id AS id, l.name AS name,
           release_count, artist_count
    """
    async with await driver.session() as session:
        result = await session.run(cypher, name=name)
        record = await result.single()
        if not record:
            return None
        return dict(record)


# --- Expand (populate category children) ---


async def expand_artist_releases(driver: AsyncResilientNeo4jDriver, artist_name: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get releases by an artist."""
    cypher = """
    MATCH (a:Artist {name: $name})-[:BY]->(r:Release)
    RETURN r.id AS id, r.title AS name, 'release' AS type, r.year AS year
    ORDER BY r.year DESC
    LIMIT $limit
    """
    async with await driver.session() as session:
        result = await session.run(cypher, name=artist_name, limit=limit)
        return [dict(record) async for record in result]


async def expand_artist_labels(driver: AsyncResilientNeo4jDriver, artist_name: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get labels associated with an artist via their releases."""
    cypher = """
    MATCH (a:Artist {name: $name})-[:BY]->(r:Release)-[:ON]->(l:Label)
    RETURN DISTINCT l.id AS id, l.name AS name, 'label' AS type, count(r) AS release_count
    ORDER BY release_count DESC
    LIMIT $limit
    """
    async with await driver.session() as session:
        result = await session.run(cypher, name=artist_name, limit=limit)
        return [dict(record) async for record in result]


async def expand_artist_aliases(driver: AsyncResilientNeo4jDriver, artist_name: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get aliases and group memberships for an artist."""
    cypher = """
    MATCH (a:Artist {name: $name})
    OPTIONAL MATCH (a)-[:MEMBER_OF]->(g:Artist)
    WITH a, collect(DISTINCT {id: g.id, name: g.name, type: 'artist'}) AS groups
    OPTIONAL MATCH (m:Artist)-[:MEMBER_OF]->(a)
    WITH groups, collect(DISTINCT {id: m.id, name: m.name, type: 'artist'}) AS members
    UNWIND (groups + members) AS alias
    RETURN DISTINCT alias.id AS id, alias.name AS name, alias.type AS type
    LIMIT $limit
    """
    async with await driver.session() as session:
        result = await session.run(cypher, name=artist_name, limit=limit)
        return [dict(record) async for record in result]


async def expand_genre_artists(driver: AsyncResilientNeo4jDriver, genre_name: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get artists in a genre."""
    cypher = """
    MATCH (a:Artist)-[:IS]->(g:Genre {name: $name})
    RETURN DISTINCT a.id AS id, a.name AS name, 'artist' AS type
    ORDER BY a.name
    LIMIT $limit
    """
    async with await driver.session() as session:
        result = await session.run(cypher, name=genre_name, limit=limit)
        return [dict(record) async for record in result]


async def expand_genre_labels(driver: AsyncResilientNeo4jDriver, genre_name: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get labels associated with a genre via artists and releases."""
    cypher = """
    MATCH (a:Artist)-[:IS]->(g:Genre {name: $name}),
          (a)-[:BY]->(r:Release)-[:ON]->(l:Label)
    RETURN DISTINCT l.id AS id, l.name AS name, 'label' AS type, count(DISTINCT r) AS release_count
    ORDER BY release_count DESC
    LIMIT $limit
    """
    async with await driver.session() as session:
        result = await session.run(cypher, name=genre_name, limit=limit)
        return [dict(record) async for record in result]


async def expand_genre_styles(driver: AsyncResilientNeo4jDriver, genre_name: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get styles (subgenres) associated with a genre."""
    cypher = """
    MATCH (a:Artist)-[:IS]->(g:Genre {name: $name}),
          (a)-[:IS]->(s:Style)
    RETURN DISTINCT s.name AS id, s.name AS name, 'style' AS type, count(DISTINCT a) AS artist_count
    ORDER BY artist_count DESC
    LIMIT $limit
    """
    async with await driver.session() as session:
        result = await session.run(cypher, name=genre_name, limit=limit)
        return [dict(record) async for record in result]


async def expand_label_releases(driver: AsyncResilientNeo4jDriver, label_name: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get releases on a label."""
    cypher = """
    MATCH (r:Release)-[:ON]->(l:Label {name: $name})
    RETURN r.id AS id, r.title AS name, 'release' AS type, r.year AS year
    ORDER BY r.year DESC
    LIMIT $limit
    """
    async with await driver.session() as session:
        result = await session.run(cypher, name=label_name, limit=limit)
        return [dict(record) async for record in result]


async def expand_label_artists(driver: AsyncResilientNeo4jDriver, label_name: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get artists on a label."""
    cypher = """
    MATCH (a:Artist)-[:BY]->(r:Release)-[:ON]->(l:Label {name: $name})
    RETURN DISTINCT a.id AS id, a.name AS name, 'artist' AS type, count(DISTINCT r) AS release_count
    ORDER BY release_count DESC
    LIMIT $limit
    """
    async with await driver.session() as session:
        result = await session.run(cypher, name=label_name, limit=limit)
        return [dict(record) async for record in result]


# --- Node Details ---


async def get_artist_details(driver: AsyncResilientNeo4jDriver, node_id: str) -> dict[str, Any] | None:
    """Get full details for an artist node."""
    cypher = """
    MATCH (a:Artist) WHERE a.id = $id OR a.name = $id
    OPTIONAL MATCH (a)-[:IS]->(g:Genre)
    WITH a, collect(DISTINCT g.name) AS genres
    OPTIONAL MATCH (a)-[:IS]->(s:Style)
    WITH a, genres, collect(DISTINCT s.name) AS styles
    OPTIONAL MATCH (a)-[:BY]->(r:Release)
    WITH a, genres, styles, count(DISTINCT r) AS release_count
    OPTIONAL MATCH (a)-[:MEMBER_OF]->(grp:Artist)
    WITH a, genres, styles, release_count, collect(DISTINCT grp.name) AS groups
    RETURN a.id AS id, a.name AS name, genres, styles, release_count, groups
    """
    async with await driver.session() as session:
        result = await session.run(cypher, id=node_id)
        record = await result.single()
        if not record:
            return None
        return dict(record)


async def get_release_details(driver: AsyncResilientNeo4jDriver, node_id: str) -> dict[str, Any] | None:
    """Get full details for a release node."""
    cypher = """
    MATCH (r:Release) WHERE r.id = $id OR r.title = $id
    OPTIONAL MATCH (a:Artist)-[:BY]->(r)
    WITH r, collect(DISTINCT a.name) AS artists
    OPTIONAL MATCH (r)-[:ON]->(l:Label)
    WITH r, artists, collect(DISTINCT l.name) AS labels
    OPTIONAL MATCH (r)-[:HAS_GENRE]->(g:Genre)
    WITH r, artists, labels, collect(DISTINCT g.name) AS genres
    OPTIONAL MATCH (r)-[:HAS_STYLE]->(s:Style)
    WITH r, artists, labels, genres, collect(DISTINCT s.name) AS styles
    RETURN r.id AS id, r.title AS name, r.year AS year, r.country AS country,
           artists, labels, genres, styles
    """
    async with await driver.session() as session:
        result = await session.run(cypher, id=node_id)
        record = await result.single()
        if not record:
            return None
        return dict(record)


async def get_label_details(driver: AsyncResilientNeo4jDriver, node_id: str) -> dict[str, Any] | None:
    """Get full details for a label node."""
    cypher = """
    MATCH (l:Label) WHERE l.id = $id OR l.name = $id
    OPTIONAL MATCH (r:Release)-[:ON]->(l)
    WITH l, count(DISTINCT r) AS release_count
    RETURN l.id AS id, l.name AS name, release_count
    """
    async with await driver.session() as session:
        result = await session.run(cypher, id=node_id)
        record = await result.single()
        if not record:
            return None
        return dict(record)


async def get_genre_details(driver: AsyncResilientNeo4jDriver, node_id: str) -> dict[str, Any] | None:
    """Get full details for a genre node."""
    cypher = """
    MATCH (g:Genre {name: $id})
    OPTIONAL MATCH (a:Artist)-[:IS]->(g)
    WITH g, count(DISTINCT a) AS artist_count
    RETURN g.name AS id, g.name AS name, artist_count
    """
    async with await driver.session() as session:
        result = await session.run(cypher, id=node_id)
        record = await result.single()
        if not record:
            return None
        return dict(record)


# --- Trends (time-series) ---


async def trends_artist(driver: AsyncResilientNeo4jDriver, name: str) -> list[dict[str, Any]]:
    """Get release count by year for an artist."""
    cypher = """
    MATCH (a:Artist {name: $name})-[:BY]->(r:Release)
    WHERE r.year IS NOT NULL AND r.year > 0
    RETURN r.year AS year, count(r) AS count
    ORDER BY r.year
    """
    async with await driver.session() as session:
        result = await session.run(cypher, name=name)
        return [dict(record) async for record in result]


async def trends_genre(driver: AsyncResilientNeo4jDriver, name: str) -> list[dict[str, Any]]:
    """Get release count by year for a genre."""
    cypher = """
    MATCH (r:Release)-[:HAS_GENRE]->(g:Genre {name: $name})
    WHERE r.year IS NOT NULL AND r.year > 0
    RETURN r.year AS year, count(r) AS count
    ORDER BY r.year
    """
    async with await driver.session() as session:
        result = await session.run(cypher, name=name)
        return [dict(record) async for record in result]


async def trends_label(driver: AsyncResilientNeo4jDriver, name: str) -> list[dict[str, Any]]:
    """Get release count by year for a label."""
    cypher = """
    MATCH (r:Release)-[:ON]->(l:Label {name: $name})
    WHERE r.year IS NOT NULL AND r.year > 0
    RETURN r.year AS year, count(r) AS count
    ORDER BY r.year
    """
    async with await driver.session() as session:
        result = await session.run(cypher, name=name)
        return [dict(record) async for record in result]


# --- Dispatch helpers ---

# LRU cache for autocomplete results
_autocomplete_cache_size = 256


@lru_cache(maxsize=_autocomplete_cache_size)
def _autocomplete_cache_key(query: str, entity_type: str, limit: int) -> tuple[str, str, int]:
    """Create a hashable cache key for autocomplete (used by the caller for LRU)."""
    return (query.lower(), entity_type, limit)


EXPLORE_DISPATCH: dict[str, Any] = {
    "artist": explore_artist,
    "genre": explore_genre,
    "label": explore_label,
}

AUTOCOMPLETE_DISPATCH: dict[str, Any] = {
    "artist": autocomplete_artist,
    "genre": autocomplete_genre,
    "label": autocomplete_label,
}

EXPAND_DISPATCH: dict[str, dict[str, Any]] = {
    "artist": {
        "releases": expand_artist_releases,
        "labels": expand_artist_labels,
        "aliases": expand_artist_aliases,
    },
    "genre": {
        "artists": expand_genre_artists,
        "labels": expand_genre_labels,
        "styles": expand_genre_styles,
    },
    "label": {
        "releases": expand_label_releases,
        "artists": expand_label_artists,
    },
}

DETAILS_DISPATCH: dict[str, Any] = {
    "artist": get_artist_details,
    "release": get_release_details,
    "label": get_label_details,
    "genre": get_genre_details,
    "style": get_genre_details,
}

TRENDS_DISPATCH: dict[str, Any] = {
    "artist": trends_artist,
    "genre": trends_genre,
    "label": trends_label,
}

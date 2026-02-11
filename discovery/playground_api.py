"""Extended API endpoints for Discovery Playground."""

import logging
import re
from typing import Any

from fastapi import HTTPException, Query
from neo4j import AsyncGraphDatabase
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from common import get_config
from discovery.cache import CACHE_TTL, cache_manager, cached


logger = logging.getLogger(__name__)

# Database models
Base = declarative_base()


class SearchRequest(BaseModel):
    """Search request model."""

    query: str
    type: str = "all"  # all, artist, release, label
    limit: int = 10


class JourneyRequest(BaseModel):
    """Music journey request model."""

    start_artist_id: str
    end_artist_id: str
    max_depth: int = 5


class TrendRequest(BaseModel):
    """Trend analysis request model."""

    type: str  # genre, artist, label
    start_year: int = 1950
    end_year: int = 2024
    top_n: int = 20


class HeatmapRequest(BaseModel):
    """Heatmap request model."""

    type: str  # genre, collab, style
    top_n: int = 20


class PlaygroundAPI:
    """Extended API functionality for Discovery Playground."""

    def __init__(self) -> None:
        """Initialize the Playground API."""
        self.config = get_config()
        self.neo4j_driver: Any | None = None
        self.pg_engine: Any | None = None
        self.pg_session_maker: Any | None = None
        self.cache = cache_manager

    async def initialize(self) -> None:
        """Initialize database connections."""
        # Initialize cache
        await self.cache.initialize()

        # Neo4j connection
        self.neo4j_driver = AsyncGraphDatabase.driver(
            self.config.neo4j_address,
            auth=(self.config.neo4j_username, self.config.neo4j_password),
        )

        # PostgreSQL connection
        pg_url = (
            f"postgresql+asyncpg://{self.config.postgres_username}:"
            f"{self.config.postgres_password}@{self.config.postgres_address}/"
            f"{self.config.postgres_database}"
        )
        self.pg_engine = create_async_engine(pg_url)
        self.pg_session_maker = async_sessionmaker(
            bind=self.pg_engine,
            expire_on_commit=False,
        )

    async def close(self) -> None:
        """Close database connections."""
        await self.cache.close()
        if self.neo4j_driver:
            await self.neo4j_driver.close()
        if self.pg_engine:
            await self.pg_engine.dispose()

    @staticmethod
    def _escape_lucene_query(query: str) -> str:
        """Escape Lucene special characters and build a fulltext search query.

        Args:
            query: Raw user search query

        Returns:
            Escaped query with wildcard suffix for partial matching
        """
        # Escape Lucene special characters: + - && || ! ( ) { } [ ] ^ " ~ * ? : \ /
        escaped = re.sub(r'([+\-&|!(){}[\]^"~*?:\\/])', r"\\\1", query)
        # Add wildcard suffix for partial matching (approximates CONTAINS)
        terms = escaped.strip().split()
        if not terms:
            return ""
        return " AND ".join(f"{term}*" for term in terms)

    @cached("search", ttl=CACHE_TTL["search"])
    async def search(self, query: str, search_type: str = "all", limit: int = 10, cursor: str | None = None) -> dict[str, Any]:
        """Search for artists, releases, or labels with cursor-based pagination."""
        from discovery.pagination import OffsetPagination

        # Extract offset from cursor
        offset = OffsetPagination.get_offset_from_cursor(cursor)

        results: dict[str, list[dict[str, Any]]] = {"artists": [], "releases": [], "labels": []}

        if not self.neo4j_driver:
            raise HTTPException(status_code=500, detail="Database not initialized")

        lucene_query = self._escape_lucene_query(query)
        if not lucene_query:
            return {
                "items": results,
                "total": None,
                "has_more": False,
                "next_cursor": None,
                "page_info": {"query": query, "type": search_type, "offset": offset},
            }

        async with self.neo4j_driver.session() as session:
            # Search artists using fulltext index
            if search_type in ["all", "artist"]:
                artist_query = """
                CALL db.index.fulltext.queryNodes('artist_name_fulltext', $query)
                YIELD node, score
                RETURN node.id AS id, node.name AS name, node.real_name AS real_name, score
                ORDER BY score DESC
                SKIP $offset
                LIMIT $limit
                """
                artist_result = await session.run(artist_query, {"query": lucene_query, "offset": offset, "limit": limit})
                results["artists"] = [dict(record) async for record in artist_result]

            # Search releases using fulltext index
            if search_type in ["all", "release"]:
                release_query = """
                CALL db.index.fulltext.queryNodes('release_title_fulltext', $query)
                YIELD node, score
                RETURN node.id AS id, node.title AS title, node.year AS year, score
                ORDER BY score DESC
                SKIP $offset
                LIMIT $limit
                """
                release_result = await session.run(release_query, {"query": lucene_query, "offset": offset, "limit": limit})
                results["releases"] = [dict(record) async for record in release_result]

            # Search labels using fulltext index
            if search_type in ["all", "label"]:
                label_query = """
                CALL db.index.fulltext.queryNodes('label_name_fulltext', $query)
                YIELD node, score
                RETURN node.id AS id, node.name AS name, score
                ORDER BY score DESC
                SKIP $offset
                LIMIT $limit
                """
                label_result = await session.run(label_query, {"query": lucene_query, "offset": offset, "limit": limit})
                results["labels"] = [dict(record) async for record in label_result]

        # Create paginated response
        # For multi-type search, use the longest result list to determine has_more
        all_items = []
        if search_type == "all":
            all_items = results["artists"] + results["releases"] + results["labels"]
        elif search_type == "artist":
            all_items = results["artists"]
        elif search_type == "release":
            all_items = results["releases"]
        elif search_type == "label":
            all_items = results["labels"]

        # Determine if there are more results
        has_more = len(all_items) >= limit
        next_cursor = None
        if has_more:
            next_cursor = OffsetPagination.create_next_cursor(offset, limit)

        return {
            "items": results,
            "total": None,
            "has_more": has_more,
            "next_cursor": next_cursor,
            "page_info": {"query": query, "type": search_type, "offset": offset},
        }

    @cached("graph", ttl=CACHE_TTL["graph"])
    async def get_graph_data(self, node_id: str, depth: int = 2, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        """Get graph data for visualization with cursor-based pagination."""
        from discovery.pagination import OffsetPagination

        # Extract offset from cursor
        offset = OffsetPagination.get_offset_from_cursor(cursor)

        nodes = []
        links = []
        link_keys: set[tuple[str, str, str]] = set()
        node_ids = set()

        if not self.neo4j_driver:
            raise HTTPException(status_code=500, detail="Database not initialized")

        async with self.neo4j_driver.session() as session:
            # Get the center node and its connections.
            # Use UNION across labeled matches so Neo4j can leverage
            # per-label indexes on the `id` property.  An unlabeled
            # MATCH (center) WHERE center.id = ... would require a
            # full graph scan on 30M+ nodes.
            # Depth (already validated as int 1-5) is interpolated
            # directly because Neo4j disallows parameterized
            # variable-length relationships.
            query = f"""
            CALL {{
                MATCH (n:Artist {{id: $node_id}}) RETURN n
                UNION ALL
                MATCH (n:Release {{id: $node_id}}) RETURN n
                UNION ALL
                MATCH (n:Label {{id: $node_id}}) RETURN n
                UNION ALL
                MATCH (n:Master {{id: $node_id}}) RETURN n
            }}
            WITH n AS center
            OPTIONAL MATCH path = (center)-[*1..{depth}]-(connected)
            WHERE NOT (connected:Master AND connected.id = '0')
            WITH center, connected, relationships(path) AS rels, nodes(path) AS path_nodes
            ORDER BY connected.id
            SKIP $offset
            LIMIT $limit
            RETURN DISTINCT center, connected, rels, path_nodes
            """

            result = await session.run(query, node_id=node_id, offset=offset, limit=limit)

            def _node_id(neo_node: Any) -> str:
                """Return a stable unique ID for a Neo4j node.

                Genre/Style nodes lack an ``id`` property, so fall back to
                a label:name composite key, then to the Neo4j element_id.
                """
                nid = neo_node.get("id")
                if nid is not None:
                    return str(nid)
                name = neo_node.get("name", "")
                label = next(iter(neo_node.labels), "node")
                if name:
                    return f"{label}:{name}"
                return str(neo_node.element_id)

            async for record in result:
                # Add center node
                center = record["center"]
                cid = _node_id(center) if center else None
                if center and cid not in node_ids:
                    node_ids.add(cid)
                    nodes.append(
                        {
                            "id": cid,
                            "name": center.get("name", center.get("title", "")),
                            "title": center.get("title", ""),
                            "type": next(iter(center.labels)).lower(),
                            "properties": dict(center),
                        }
                    )

                # Add all path nodes (including intermediates) and relationships
                if record["connected"] and record["rels"]:
                    # Add every node along the path so links can reference them
                    for path_node in record["path_nodes"]:
                        if path_node:
                            pid = _node_id(path_node)
                            if pid not in node_ids:
                                node_ids.add(pid)
                                nodes.append(
                                    {
                                        "id": pid,
                                        "name": path_node.get("name", path_node.get("title", "")),
                                        "title": path_node.get("title", ""),
                                        "type": next(iter(path_node.labels)).lower(),
                                        "properties": dict(path_node),
                                    }
                                )

                    # Add relationships (deduplicated)
                    for i, rel in enumerate(record["rels"]):
                        if i < len(record["path_nodes"]) - 1:
                            src = _node_id(record["path_nodes"][i])
                            tgt = _node_id(record["path_nodes"][i + 1])
                            rel_type = rel.type.lower()
                            link_key = (src, tgt, rel_type)
                            if link_key not in link_keys:
                                link_keys.add(link_key)
                                links.append(
                                    {
                                        "source": src,
                                        "target": tgt,
                                        "type": rel_type,
                                        "properties": dict(rel),
                                    }
                                )

        # Determine if there are more results
        # We check if we got the full limit of results
        has_more = len(nodes) >= limit
        next_cursor = None
        if has_more:
            next_cursor = OffsetPagination.create_next_cursor(offset, limit)

        return {
            "nodes": nodes,
            "links": links,
            "has_more": has_more,
            "next_cursor": next_cursor,
            "page_info": {"node_id": node_id, "depth": depth, "offset": offset, "limit": limit},
        }

    @cached("journey", ttl=CACHE_TTL["journey"])
    async def find_music_journey(self, start_artist_id: str, end_artist_id: str, max_depth: int = 5) -> dict[str, Any]:
        """Find a musical journey between two artists."""
        if not self.neo4j_driver:
            raise HTTPException(status_code=500, detail="Database not initialized")

        async with self.neo4j_driver.session() as session:
            # Note: Neo4j does not allow parameterized variable-length
            # relationships, so max_depth (already validated as int 1-5)
            # is interpolated directly into the query string.
            query = f"""
            MATCH path = shortestPath(
                (start:Artist {{id: $start_id}})-[*1..{max_depth}]-(end:Artist {{id: $end_id}})
            )
            RETURN path,
                   [node in nodes(path) | {{
                       id: node.id,
                       name: COALESCE(node.name, node.title),
                       type: labels(node)[0],
                       properties: properties(node)
                   }}] AS nodes,
                   [rel in relationships(path) | {{
                       type: type(rel),
                       properties: properties(rel)
                   }}] AS relationships
            """

            result = await session.run(
                query,
                start_id=start_artist_id,
                end_id=end_artist_id,
            )

            record = await result.single()
            if not record:
                return {"journey": None, "message": "No path found between these artists"}

            return {
                "journey": {
                    "nodes": record["nodes"],
                    "relationships": record["relationships"],
                    "length": len(record["nodes"]) - 1,
                }
            }

    @cached("trends", ttl=CACHE_TTL["trends"])
    async def get_trends(
        self,
        trend_type: str,
        start_year: int,
        end_year: int,
        top_n: int = 20,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Get trend analysis data with cursor-based pagination."""
        from discovery.pagination import OffsetPagination

        # Extract offset from cursor
        offset = OffsetPagination.get_offset_from_cursor(cursor)

        trends = []

        if trend_type == "genre":
            if not self.neo4j_driver:
                return {
                    "trends": [],
                    "type": trend_type,
                    "has_more": False,
                    "next_cursor": None,
                    "page_info": {
                        "type": trend_type,
                        "start_year": start_year,
                        "end_year": end_year,
                        "offset": offset,
                    },
                }

            async with self.neo4j_driver.session() as session:
                query = """
                MATCH (r:Release)-[:IS]->(g:Genre)
                WHERE r.year >= $start_year AND r.year <= $end_year
                WITH g.name AS genre, r.year AS year, COUNT(r) AS count
                ORDER BY year, count DESC
                WITH year, collect({genre: genre, count: count})[0..$top_n] AS top_genres
                RETURN year, top_genres
                ORDER BY year
                SKIP $offset
                LIMIT $limit
                """

                result = await session.run(query, start_year=start_year, end_year=end_year, top_n=top_n, offset=offset, limit=limit)

                async for record in result:
                    trends.append({"year": record["year"], "data": record["top_genres"]})

        elif trend_type == "artist":
            if not self.neo4j_driver:
                return {
                    "trends": [],
                    "type": trend_type,
                    "has_more": False,
                    "next_cursor": None,
                    "page_info": {
                        "type": trend_type,
                        "start_year": start_year,
                        "end_year": end_year,
                        "offset": offset,
                    },
                }

            async with self.neo4j_driver.session() as session:
                query = """
                MATCH (a:Artist)<-[:BY]-(r:Release)
                WHERE r.year >= $start_year AND r.year <= $end_year
                WITH a.name AS artist, r.year AS year, COUNT(r) AS releases
                ORDER BY year, releases DESC
                WITH year, collect({artist: artist, releases: releases})[0..$top_n] AS top_artists
                RETURN year, top_artists
                ORDER BY year
                SKIP $offset
                LIMIT $limit
                """

                result = await session.run(query, start_year=start_year, end_year=end_year, top_n=top_n, offset=offset, limit=limit)

                async for record in result:
                    trends.append({"year": record["year"], "data": record["top_artists"]})

        elif trend_type == "label":
            if not self.neo4j_driver:
                return {
                    "trends": [],
                    "type": trend_type,
                    "has_more": False,
                    "next_cursor": None,
                    "page_info": {
                        "type": trend_type,
                        "start_year": start_year,
                        "end_year": end_year,
                        "offset": offset,
                    },
                }

            async with self.neo4j_driver.session() as session:
                query = """
                MATCH (l:Label)<-[:ON]-(r:Release)
                WHERE r.year >= $start_year AND r.year <= $end_year
                WITH l.name AS label, r.year AS year, COUNT(r) AS releases
                ORDER BY year, releases DESC
                WITH year, collect({label: label, releases: releases})[0..$top_n] AS top_labels
                RETURN year, top_labels
                ORDER BY year
                SKIP $offset
                LIMIT $limit
                """

                result = await session.run(query, start_year=start_year, end_year=end_year, top_n=top_n, offset=offset, limit=limit)

                async for record in result:
                    trends.append({"year": record["year"], "data": record["top_labels"]})

        # Determine if there are more results
        has_more = len(trends) >= limit
        next_cursor = None
        if has_more:
            next_cursor = OffsetPagination.create_next_cursor(offset, limit)

        return {
            "trends": trends,
            "type": trend_type,
            "has_more": has_more,
            "next_cursor": next_cursor,
            "page_info": {"type": trend_type, "start_year": start_year, "end_year": end_year, "offset": offset},
        }

    @cached("heatmap", ttl=CACHE_TTL["heatmap"])
    async def get_heatmap(self, heatmap_type: str, top_n: int = 20, limit: int = 100, cursor: str | None = None) -> dict[str, Any]:
        """Get similarity heatmap data with cursor-based pagination."""
        from discovery.pagination import OffsetPagination

        # Extract offset from cursor
        offset = OffsetPagination.get_offset_from_cursor(cursor)

        if heatmap_type == "genre":
            if not self.neo4j_driver:
                return {
                    "heatmap": [],
                    "labels": [],
                    "type": heatmap_type,
                    "has_more": False,
                    "next_cursor": None,
                    "page_info": {"type": heatmap_type, "top_n": top_n, "offset": offset},
                }

            async with self.neo4j_driver.session() as session:
                # Step 1: Get top artists by release count
                top_artists_query = """
                MATCH (a:Artist)<-[:BY]-(r:Release)
                WITH a, COUNT(r) AS release_count
                ORDER BY release_count DESC
                LIMIT $top_n
                RETURN a.id AS id, a.name AS name
                """
                top_result = await session.run(top_artists_query, top_n=top_n)
                top_artist_ids = []
                async for record in top_result:
                    top_artist_ids.append(record["id"])

                # Step 2: For those artists, find shared genres pairwise
                query = """
                MATCH (a1:Artist)<-[:BY]-(r1:Release)-[:IS]->(g:Genre)<-[:IS]-(r2:Release)-[:BY]->(a2:Artist)
                WHERE a1.id IN $artist_ids AND a2.id IN $artist_ids
                  AND a1.id < a2.id
                WITH a1.name AS artist1, a2.name AS artist2, COUNT(DISTINCT g) AS shared_genres
                RETURN artist1, artist2, shared_genres
                ORDER BY shared_genres DESC, artist1, artist2
                SKIP $offset
                LIMIT $limit
                """

                result = await session.run(query, artist_ids=top_artist_ids, offset=offset, limit=limit)
                data = []
                artists = set()

                async for record in result:
                    artists.add(record["artist1"])
                    artists.add(record["artist2"])
                    data.append(
                        {
                            "x": record["artist1"],
                            "y": record["artist2"],
                            "value": record["shared_genres"],
                        }
                    )

                # Determine if there are more results
                has_more = len(data) >= limit
                next_cursor = None
                if has_more:
                    next_cursor = OffsetPagination.create_next_cursor(offset, limit)

                return {
                    "heatmap": data,
                    "labels": sorted(artists),
                    "type": heatmap_type,
                    "has_more": has_more,
                    "next_cursor": next_cursor,
                    "page_info": {"type": heatmap_type, "top_n": top_n, "offset": offset},
                }

        elif heatmap_type == "collab":
            if not self.neo4j_driver:
                return {
                    "heatmap": [],
                    "labels": [],
                    "type": heatmap_type,
                    "has_more": False,
                    "next_cursor": None,
                    "page_info": {"type": heatmap_type, "top_n": top_n, "offset": offset},
                }

            async with self.neo4j_driver.session() as session:
                # Step 1: Get top collaborating artists
                top_collab_query = """
                MATCH (a:Artist)<-[:BY]-(r:Release)-[:BY]->(other:Artist)
                WHERE a <> other
                WITH a, count(DISTINCT other) AS collab_count
                ORDER BY collab_count DESC
                LIMIT $top_n
                RETURN a.id AS id, a.name AS name
                """
                top_result = await session.run(top_collab_query, top_n=top_n)
                top_artist_ids = []
                async for record in top_result:
                    top_artist_ids.append(record["id"])

                # Step 2: For those artists, compute pairwise collaboration
                query = """
                MATCH (a1:Artist)<-[:BY]-(r:Release)-[:BY]->(a2:Artist)
                WHERE a1.id IN $artist_ids AND a2.id IN $artist_ids
                  AND a1.id < a2.id
                WITH a1.name AS artist1, a2.name AS artist2, COUNT(DISTINCT r) AS collaborated
                RETURN artist1, artist2, collaborated
                ORDER BY collaborated DESC, artist1, artist2
                SKIP $offset
                LIMIT $limit
                """

                result = await session.run(query, artist_ids=top_artist_ids, offset=offset, limit=limit)
                data = []
                artists = set()

                async for record in result:
                    if record["collaborated"] > 0:
                        artists.add(record["artist1"])
                        artists.add(record["artist2"])
                        data.append(
                            {
                                "x": record["artist1"],
                                "y": record["artist2"],
                                "value": record["collaborated"],
                            }
                        )

                # Determine if there are more results
                has_more = len(data) >= limit
                next_cursor = None
                if has_more:
                    next_cursor = OffsetPagination.create_next_cursor(offset, limit)

                return {
                    "heatmap": data,
                    "labels": sorted(artists),
                    "type": heatmap_type,
                    "has_more": has_more,
                    "next_cursor": next_cursor,
                    "page_info": {"type": heatmap_type, "top_n": top_n, "offset": offset},
                }

        return {
            "heatmap": [],
            "labels": [],
            "type": heatmap_type,
            "has_more": False,
            "next_cursor": None,
            "page_info": {"type": heatmap_type, "top_n": top_n, "offset": offset},
        }

    @cached("master_details", ttl=CACHE_TTL["master_details"])
    async def get_master_details(self, master_id: str) -> dict[str, Any]:
        """Get detailed information about a master release."""
        if not self.neo4j_driver:
            raise HTTPException(status_code=500, detail="Database not initialized")

        async with self.neo4j_driver.session() as session:
            query = """
            MATCH (m:Master {id: $master_id})
            OPTIONAL MATCH (m)<-[:VERSION_OF]-(r:Release)
            OPTIONAL MATCH (m)-[:BY]->(a:Artist)
            RETURN m,
                   COUNT(DISTINCT r) AS version_count,
                   collect(DISTINCT r.title)[0..10] AS versions,
                   collect(DISTINCT a.name) AS artists
            """

            result = await session.run(query, master_id=master_id)
            record = await result.single()

            if not record:
                raise HTTPException(status_code=404, detail="Master not found")

            master = record["m"]
            return {
                "id": master["id"],
                "title": master.get("title"),
                "year": master.get("year"),
                "genres": master.get("genres", []),
                "styles": master.get("styles", []),
                "version_count": record["version_count"],
                "versions": record["versions"],
                "artists": record["artists"],
            }

    @cached("artist_details", ttl=CACHE_TTL["artist_details"])
    async def get_artist_details(self, artist_id: str) -> dict[str, Any]:
        """Get detailed information about an artist."""
        if not self.neo4j_driver:
            raise HTTPException(status_code=500, detail="Database not initialized")

        async with self.neo4j_driver.session() as session:
            query = """
            MATCH (a:Artist {id: $artist_id})
            OPTIONAL MATCH (a)<-[:BY]-(r:Release)
            OPTIONAL MATCH (a)-[:MEMBER_OF]->(g:Artist)
            OPTIONAL MATCH (a)<-[:ALIAS_OF]-(alias:Artist)
            OPTIONAL MATCH (a)<-[:BY]-(rel:Release)-[:BY]->(collab:Artist)
            WHERE a <> collab
            RETURN a,
                   COUNT(DISTINCT r) AS release_count,
                   collect(DISTINCT g.name) AS groups,
                   collect(DISTINCT alias.name) AS aliases,
                   collect(DISTINCT collab.name)[0..10] AS collaborators
            """

            result = await session.run(query, artist_id=artist_id)
            record = await result.single()

            if not record:
                raise HTTPException(status_code=404, detail="Artist not found")

            artist = record["a"]
            return {
                "id": artist["id"],
                "name": artist.get("name"),
                "real_name": artist.get("real_name"),
                "profile": artist.get("profile"),
                "urls": artist.get("urls", []),
                "release_count": record["release_count"],
                "groups": record["groups"],
                "aliases": record["aliases"],
                "collaborators": record["collaborators"],
            }


# Create global instance
playground_api = PlaygroundAPI()


# FastAPI route handlers
async def search_handler(
    q: str = Query(..., description="Search query"),
    type: str = Query("all", description="Search type: all, artist, release, label"),
    limit: int = Query(10, ge=1, le=50),
    cursor: str | None = Query(None, description="Cursor for pagination"),
) -> dict[str, Any]:
    """Search endpoint handler with cursor-based pagination."""
    result: dict[str, Any] = await playground_api.search(q, type, limit, cursor)
    return result


async def graph_data_handler(
    node_id: str = Query(..., description="Node ID"),
    depth: int = Query(2, ge=1, le=5),
    limit: int = Query(50, ge=10, le=200),
    cursor: str | None = Query(None, description="Cursor for pagination"),
) -> dict[str, Any]:
    """Graph data endpoint handler with cursor-based pagination."""
    result: dict[str, Any] = await playground_api.get_graph_data(node_id, depth, limit, cursor)
    return result


async def journey_handler(request: JourneyRequest) -> dict[str, Any]:
    """Music journey endpoint handler."""
    result: dict[str, Any] = await playground_api.find_music_journey(request.start_artist_id, request.end_artist_id, request.max_depth)
    return result


async def trends_handler(
    type: str = Query(..., description="Trend type: genre, artist, label"),
    start_year: int = Query(1950, ge=1950),
    end_year: int = Query(2024, le=2024),
    top_n: int = Query(20, ge=5, le=50),
    limit: int = Query(20, ge=1, le=50),
    cursor: str | None = Query(None, description="Cursor for pagination"),
) -> dict[str, Any]:
    """Trends endpoint handler with cursor-based pagination."""
    result: dict[str, Any] = await playground_api.get_trends(type, start_year, end_year, top_n, limit, cursor)
    return result


async def heatmap_handler(
    type: str = Query(..., description="Heatmap type: genre, collab"),
    top_n: int = Query(20, ge=10, le=50),
    limit: int = Query(100, ge=10, le=500),
    cursor: str | None = Query(None, description="Cursor for pagination"),
) -> dict[str, Any]:
    """Heatmap endpoint handler with cursor-based pagination."""
    result: dict[str, Any] = await playground_api.get_heatmap(type, top_n, limit, cursor)
    return result


async def master_details_handler(master_id: str) -> dict[str, Any]:
    """Master details endpoint handler."""
    result: dict[str, Any] = await playground_api.get_master_details(master_id)
    return result


async def artist_details_handler(artist_id: str) -> dict[str, Any]:
    """Artist details endpoint handler."""
    result: dict[str, Any] = await playground_api.get_artist_details(artist_id)
    return result

"""Extended API endpoints for Discovery Playground."""

import logging
from typing import Any

from common import get_config
from fastapi import HTTPException, Query
from neo4j import AsyncGraphDatabase
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

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

    @cached("search", ttl=CACHE_TTL["search"])
    async def search(self, query: str, search_type: str = "all", limit: int = 10) -> dict[str, Any]:
        """Search for artists, releases, or labels."""
        results: dict[str, list[dict[str, Any]]] = {"artists": [], "releases": [], "labels": []}

        if not self.neo4j_driver:
            raise HTTPException(status_code=500, detail="Database not initialized")

        async with self.neo4j_driver.session() as session:
            # Search artists
            if search_type in ["all", "artist"]:
                artist_query = """
                MATCH (a:Artist)
                WHERE toLower(a.name) CONTAINS toLower($query)
                RETURN a.id AS id, a.name AS name, a.real_name AS real_name
                LIMIT $limit
                """
                artist_result = await session.run(artist_query, query=query, limit=limit)
                results["artists"] = [dict(record) async for record in artist_result]

            # Search releases
            if search_type in ["all", "release"]:
                release_query = """
                MATCH (r:Release)
                WHERE toLower(r.title) CONTAINS toLower($query)
                RETURN r.id AS id, r.title AS title, r.year AS year
                LIMIT $limit
                """
                release_result = await session.run(release_query, query=query, limit=limit)
                results["releases"] = [dict(record) async for record in release_result]

            # Search labels
            if search_type in ["all", "label"]:
                label_query = """
                MATCH (l:Label)
                WHERE toLower(l.name) CONTAINS toLower($query)
                RETURN l.id AS id, l.name AS name
                LIMIT $limit
                """
                label_result = await session.run(label_query, query=query, limit=limit)
                results["labels"] = [dict(record) async for record in label_result]

        return results

    @cached("graph", ttl=CACHE_TTL["graph"])
    async def get_graph_data(self, node_id: str, depth: int = 2, limit: int = 50) -> dict[str, Any]:
        """Get graph data for visualization."""
        nodes = []
        links = []
        node_ids = set()

        if not self.neo4j_driver:
            raise HTTPException(status_code=500, detail="Database not initialized")

        async with self.neo4j_driver.session() as session:
            # Get the center node and its connections
            query = """
            MATCH (center)
            WHERE center.id = $node_id
            OPTIONAL MATCH path = (center)-[*1..$depth]-(connected)
            WITH center, connected, relationships(path) AS rels, nodes(path) AS path_nodes
            LIMIT $limit
            RETURN DISTINCT center, connected, rels, path_nodes
            """

            result = await session.run(query, node_id=node_id, depth=depth, limit=limit)

            async for record in result:
                # Add center node
                center = record["center"]
                if center and center["id"] not in node_ids:
                    node_ids.add(center["id"])
                    nodes.append(
                        {
                            "id": center["id"],
                            "name": center.get("name", center.get("title", "")),
                            "type": next(iter(center.labels)).lower(),
                            "properties": dict(center),
                        }
                    )

                # Add connected nodes and relationships
                if record["connected"] and record["rels"]:
                    connected = record["connected"]
                    if connected["id"] not in node_ids:
                        node_ids.add(connected["id"])
                        nodes.append(
                            {
                                "id": connected["id"],
                                "name": connected.get("name", connected.get("title", "")),
                                "type": next(iter(connected.labels)).lower(),
                                "properties": dict(connected),
                            }
                        )

                    # Add relationships
                    for i, rel in enumerate(record["rels"]):
                        if i < len(record["path_nodes"]) - 1:
                            source_node = record["path_nodes"][i]
                            target_node = record["path_nodes"][i + 1]
                            links.append(
                                {
                                    "source": source_node["id"],
                                    "target": target_node["id"],
                                    "type": rel.type.lower(),
                                    "properties": dict(rel),
                                }
                            )

        return {"nodes": nodes, "links": links}

    @cached("journey", ttl=CACHE_TTL["journey"])
    async def find_music_journey(
        self, start_artist_id: str, end_artist_id: str, max_depth: int = 5
    ) -> dict[str, Any]:
        """Find a musical journey between two artists."""
        if not self.neo4j_driver:
            raise HTTPException(status_code=500, detail="Database not initialized")

        async with self.neo4j_driver.session() as session:
            query = """
            MATCH path = shortestPath(
                (start:Artist {id: $start_id})-[*1..$max_depth]-(end:Artist {id: $end_id})
            )
            RETURN path,
                   [node in nodes(path) | {
                       id: node.id,
                       name: node.name,
                       type: labels(node)[0],
                       properties: properties(node)
                   }] AS nodes,
                   [rel in relationships(path) | {
                       type: type(rel),
                       properties: properties(rel)
                   }] AS relationships
            """

            result = await session.run(
                query,
                start_id=start_artist_id,
                end_id=end_artist_id,
                max_depth=max_depth,
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
        self, trend_type: str, start_year: int, end_year: int, top_n: int = 20
    ) -> dict[str, Any]:
        """Get trend analysis data."""
        trends = []

        if trend_type == "genre":
            if not self.neo4j_driver:
                return {"trends": [], "type": trend_type}

            async with self.neo4j_driver.session() as session:
                query = """
                MATCH (r:Release)-[:HAS_GENRE]->(g:Genre)
                WHERE r.year >= $start_year AND r.year <= $end_year
                WITH g.name AS genre, r.year AS year, COUNT(r) AS count
                ORDER BY year, count DESC
                WITH year, collect({genre: genre, count: count})[0..$top_n] AS top_genres
                RETURN year, top_genres
                ORDER BY year
                """

                result = await session.run(
                    query, start_year=start_year, end_year=end_year, top_n=top_n
                )

                async for record in result:
                    trends.append({"year": record["year"], "data": record["top_genres"]})

        elif trend_type == "artist":
            if not self.neo4j_driver:
                return {"trends": [], "type": trend_type}

            async with self.neo4j_driver.session() as session:
                query = """
                MATCH (a:Artist)-[:BY]-(r:Release)
                WHERE r.year >= $start_year AND r.year <= $end_year
                WITH a.name AS artist, r.year AS year, COUNT(r) AS releases
                ORDER BY year, releases DESC
                WITH year, collect({artist: artist, releases: releases})[0..$top_n] AS top_artists
                RETURN year, top_artists
                ORDER BY year
                """

                result = await session.run(
                    query, start_year=start_year, end_year=end_year, top_n=top_n
                )

                async for record in result:
                    trends.append({"year": record["year"], "data": record["top_artists"]})

        return {"trends": trends, "type": trend_type}

    @cached("heatmap", ttl=CACHE_TTL["heatmap"])
    async def get_heatmap(self, heatmap_type: str, top_n: int = 20) -> dict[str, Any]:
        """Get similarity heatmap data."""
        if heatmap_type == "genre":
            if not self.neo4j_driver:
                return {"heatmap": [], "labels": [], "type": heatmap_type}

            async with self.neo4j_driver.session() as session:
                # Get top artists by release count
                query = """
                MATCH (a:Artist)-[:BY]->(r:Release)
                WITH a, COUNT(r) AS release_count
                ORDER BY release_count DESC
                LIMIT $top_n
                WITH collect(a) AS artists
                UNWIND artists AS a1
                UNWIND artists AS a2
                MATCH (a1)-[:BY]->(r1:Release)-[:HAS_GENRE]->(g:Genre)<-[:HAS_GENRE]-(r2:Release)<-[:BY]-(a2)
                WHERE id(a1) < id(a2)
                WITH a1.name AS artist1, a2.name AS artist2, COUNT(DISTINCT g) AS shared_genres
                RETURN artist1, artist2, shared_genres
                ORDER BY shared_genres DESC
                """

                result = await session.run(query, top_n=top_n)
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

                return {
                    "heatmap": data,
                    "labels": sorted(artists),
                    "type": heatmap_type,
                }

        elif heatmap_type == "collab":
            if not self.neo4j_driver:
                return {"heatmap": [], "labels": [], "type": heatmap_type}

            async with self.neo4j_driver.session() as session:
                query = """
                MATCH (a:Artist)
                WITH a, size((a)-[:COLLABORATED_WITH]-()) AS collab_count
                ORDER BY collab_count DESC
                LIMIT $top_n
                WITH collect(a) AS artists
                UNWIND artists AS a1
                UNWIND artists AS a2
                OPTIONAL MATCH (a1)-[c:COLLABORATED_WITH]-(a2)
                WHERE id(a1) < id(a2)
                WITH a1.name AS artist1, a2.name AS artist2,
                     CASE WHEN c IS NOT NULL THEN 1 ELSE 0 END AS collaborated
                RETURN artist1, artist2, collaborated
                """

                result = await session.run(query, top_n=top_n)
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

                return {
                    "heatmap": data,
                    "labels": sorted(artists),
                    "type": heatmap_type,
                }

        return {"heatmap": [], "labels": [], "type": heatmap_type}

    @cached("artist_details", ttl=CACHE_TTL["artist_details"])
    async def get_artist_details(self, artist_id: str) -> dict[str, Any]:
        """Get detailed information about an artist."""
        if not self.neo4j_driver:
            raise HTTPException(status_code=500, detail="Database not initialized")

        async with self.neo4j_driver.session() as session:
            query = """
            MATCH (a:Artist {id: $artist_id})
            OPTIONAL MATCH (a)-[:BY]->(r:Release)
            OPTIONAL MATCH (a)-[:MEMBER_OF]->(g:Artist)
            OPTIONAL MATCH (a)-[:HAS_ALIAS]->(alias:Artist)
            OPTIONAL MATCH (a)-[:COLLABORATED_WITH]-(collab:Artist)
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
) -> dict[str, Any]:
    """Search endpoint handler."""
    result: dict[str, Any] = await playground_api.search(q, type, limit)
    return result


async def graph_data_handler(
    node_id: str = Query(..., description="Node ID"),
    depth: int = Query(2, ge=1, le=5),
    limit: int = Query(50, ge=10, le=200),
) -> dict[str, Any]:
    """Graph data endpoint handler."""
    result: dict[str, Any] = await playground_api.get_graph_data(node_id, depth, limit)
    return result


async def journey_handler(request: JourneyRequest) -> dict[str, Any]:
    """Music journey endpoint handler."""
    result: dict[str, Any] = await playground_api.find_music_journey(
        request.start_artist_id, request.end_artist_id, request.max_depth
    )
    return result


async def trends_handler(
    type: str = Query(..., description="Trend type: genre, artist, label"),
    start_year: int = Query(1950, ge=1950),
    end_year: int = Query(2024, le=2024),
    top_n: int = Query(20, ge=5, le=50),
) -> dict[str, Any]:
    """Trends endpoint handler."""
    result: dict[str, Any] = await playground_api.get_trends(type, start_year, end_year, top_n)
    return result


async def heatmap_handler(
    type: str = Query(..., description="Heatmap type: genre, collab, style"),
    top_n: int = Query(20, ge=10, le=50),
) -> dict[str, Any]:
    """Heatmap endpoint handler."""
    result: dict[str, Any] = await playground_api.get_heatmap(type, top_n)
    return result


async def artist_details_handler(artist_id: str) -> dict[str, Any]:
    """Artist details endpoint handler."""
    result: dict[str, Any] = await playground_api.get_artist_details(artist_id)
    return result

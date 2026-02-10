"""Graph Analytics API.

This module provides endpoints for centrality metrics, community detection,
genre evolution analysis, and similarity networks.
"""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import structlog


logger = structlog.get_logger(__name__)

# Create API router
router = APIRouter(prefix="/api/graph", tags=["Graph Analytics"])


# Request/Response Models


class CentralityRequest(BaseModel):
    """Request for centrality metrics calculation."""

    metric: Literal["degree", "betweenness", "closeness", "eigenvector", "pagerank"] = Field(
        "pagerank",
        description="Centrality metric to calculate",
    )
    limit: int = Field(20, description="Number of top nodes to return", ge=1, le=100)
    node_type: Literal["artist", "release", "label"] = Field("artist", description="Node type to analyze")
    sample_size: int | None = Field(None, description="Optional sample size for large graphs", ge=100)


class CommunityDetectionRequest(BaseModel):
    """Request for community detection."""

    algorithm: Literal["louvain", "label_propagation"] = Field("louvain", description="Detection algorithm")
    min_community_size: int = Field(5, description="Minimum community size", ge=2)
    resolution: float = Field(1.0, description="Resolution parameter for Louvain", ge=0.1, le=2.0)


class GenreEvolutionRequest(BaseModel):
    """Request for genre evolution analysis."""

    genre: str = Field(..., description="Genre to analyze")
    start_year: int = Field(1950, description="Start year", ge=1900, le=2030)
    end_year: int = Field(2024, description="End year", ge=1900, le=2030)


class SimilarityNetworkRequest(BaseModel):
    """Request for similarity network building."""

    artist_id: str = Field(..., description="Seed artist ID")
    max_depth: int = Field(2, description="Maximum network depth", ge=1, le=5)
    similarity_threshold: float = Field(0.3, description="Minimum similarity", ge=0.0, le=1.0)
    max_nodes: int = Field(50, description="Maximum nodes in network", ge=10, le=200)


# Module-level instances (initialized on startup)
graph_api_initialized = False
centrality_analyzer: Any = None
community_detector: Any = None
genre_evolution_tracker: Any = None
similarity_network_builder: Any = None


async def initialize_graph_api(neo4j_driver: Any) -> None:
    """Initialize Graph Analytics API components.

    Args:
        neo4j_driver: Neo4j async driver instance
    """
    global graph_api_initialized, centrality_analyzer, community_detector
    global genre_evolution_tracker, similarity_network_builder

    logger.info("🚀 Initializing Graph Analytics API components...")

    # Import Phase 3 components
    from discovery.centrality_metrics import CentralityAnalyzer
    from discovery.community_detection import CommunityDetector
    from discovery.genre_evolution import GenreEvolutionTracker
    from discovery.similarity_network import SimilarityNetworkBuilder

    # Initialize components
    centrality_analyzer = CentralityAnalyzer(neo4j_driver)
    community_detector = CommunityDetector(neo4j_driver)
    genre_evolution_tracker = GenreEvolutionTracker(neo4j_driver)
    similarity_network_builder = SimilarityNetworkBuilder(neo4j_driver)

    graph_api_initialized = True
    logger.info("✅ Graph Analytics API initialization complete")


async def close_graph_api() -> None:
    """Close Graph Analytics API components and cleanup resources."""
    global graph_api_initialized

    logger.info("🛑 Closing Graph Analytics API components...")
    graph_api_initialized = False
    logger.info("✅ Graph Analytics API components closed")


# API Endpoints


@router.post("/centrality")
async def calculate_centrality_endpoint(request: Request, req_body: CentralityRequest) -> dict[str, Any]:  # noqa: ARG001
    """Calculate centrality metrics for graph nodes.

    Supports degree, betweenness, closeness, eigenvector, and PageRank centrality.

    Args:
        request: FastAPI request object (required for rate limiting)
        req_body: Request parameters

    Returns:
        Dictionary with centrality scores for top nodes

    Raises:
        HTTPException: If graph API not initialized
    """
    if not graph_api_initialized or centrality_analyzer is None:
        raise HTTPException(status_code=503, detail="Graph Analytics API not initialized")

    logger.info(
        "📊 Centrality calculation request",
        metric=req_body.metric,
        node_type=req_body.node_type,
    )

    try:
        # Build network first (centrality methods require it)
        sample_limit = req_body.sample_size if req_body.sample_size else 5000
        await centrality_analyzer.build_network(limit=sample_limit)

        # Calculate requested centrality metric
        if req_body.metric == "degree":
            centrality_scores = centrality_analyzer.calculate_degree_centrality()
        elif req_body.metric == "betweenness":
            k = req_body.sample_size if req_body.sample_size else None
            centrality_scores = centrality_analyzer.calculate_betweenness_centrality(k=k)
        elif req_body.metric == "closeness":
            centrality_scores = centrality_analyzer.calculate_closeness_centrality()
        elif req_body.metric == "eigenvector":
            centrality_scores = centrality_analyzer.calculate_eigenvector_centrality()
        elif req_body.metric == "pagerank":
            centrality_scores = centrality_analyzer.calculate_pagerank()
        else:
            raise ValueError(f"Unknown centrality metric: {req_body.metric}")

        # Sort by score and get top N
        sorted_nodes = sorted(centrality_scores.items(), key=lambda x: x[1], reverse=True)[: req_body.limit]

        # Format as list of dicts
        top_nodes = [{"node": node, "score": float(score)} for node, score in sorted_nodes]

        return {
            "metric": req_body.metric,
            "node_type": req_body.node_type,
            "top_nodes": top_nodes,
            "total_nodes": len(centrality_scores),
            "status": "success",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"❌ Centrality calculation error: {e}")
        raise HTTPException(status_code=500, detail=f"Centrality calculation error: {e!s}") from e


@router.post("/communities")
async def detect_communities_endpoint(request: Request, req_body: CommunityDetectionRequest) -> dict[str, Any]:  # noqa: ARG001
    """Detect communities in the graph.

    Uses Louvain or label propagation algorithms for community detection.

    Args:
        request: FastAPI request object (required for rate limiting)
        req_body: Request parameters

    Returns:
        Dictionary with detected communities

    Raises:
        HTTPException: If graph API not initialized
    """
    if not graph_api_initialized or community_detector is None:
        raise HTTPException(status_code=503, detail="Graph Analytics API not initialized")

    logger.info(
        "📊 Community detection request",
        algorithm=req_body.algorithm,
    )

    try:
        # Build collaboration network first
        await community_detector.build_collaboration_network()

        # Detect communities using selected algorithm
        if req_body.algorithm == "louvain":
            communities = community_detector.detect_communities_louvain()
        elif req_body.algorithm == "label_propagation":
            communities = community_detector.detect_communities_label_propagation()
        else:
            raise ValueError(f"Unknown algorithm: {req_body.algorithm}")

        # Calculate modularity
        modularity = community_detector.calculate_modularity()

        # Filter communities by minimum size and format
        filtered_communities = []
        for community_id, members in communities.items():
            if len(members) >= req_body.min_community_size:
                filtered_communities.append({"id": community_id, "members": members, "size": len(members)})

        # Sort by size (largest first)
        filtered_communities.sort(key=lambda x: x["size"], reverse=True)

        return {
            "algorithm": req_body.algorithm,
            "communities": filtered_communities,
            "total_communities": len(filtered_communities),
            "modularity": float(modularity),
            "status": "success",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"❌ Community detection error: {e}")
        raise HTTPException(status_code=500, detail=f"Community detection error: {e!s}") from e


@router.post("/genre-evolution")
async def analyze_genre_evolution_endpoint(request: Request, req_body: GenreEvolutionRequest) -> dict[str, Any]:  # noqa: ARG001
    """Analyze genre evolution over time.

    Tracks genre popularity, growth, and decline across decades.

    Args:
        request: FastAPI request object (required for rate limiting)
        req_body: Request parameters

    Returns:
        Dictionary with genre evolution data

    Raises:
        HTTPException: If graph API not initialized
    """
    if not graph_api_initialized or genre_evolution_tracker is None:
        raise HTTPException(status_code=503, detail="Graph Analytics API not initialized")

    logger.info(
        "📊 Genre evolution request",
        genre=req_body.genre,
        year_range=f"{req_body.start_year}-{req_body.end_year}",
    )

    try:
        # Analyze genre timeline
        all_genres = await genre_evolution_tracker.analyze_genre_timeline(
            start_year=req_body.start_year,
            end_year=req_body.end_year,
        )

        # Extract the requested genre's data
        genre_trend = all_genres.get(req_body.genre)

        if genre_trend is None:
            return {
                "genre": req_body.genre,
                "start_year": req_body.start_year,
                "end_year": req_body.end_year,
                "evolution_data": [],
                "status": "not_found",
                "message": f"Genre '{req_body.genre}' not found in the specified time range",
                "timestamp": datetime.now().isoformat(),
            }

        # Convert GenreTrend dataclass to dict
        evolution_data = {
            "total_releases": genre_trend.total_releases,
            "peak_year": genre_trend.peak_year,
            "peak_count": genre_trend.peak_count,
            "growth_rate": genre_trend.growth_rate,
            "timeline": [{"year": year, "count": count} for year, count in genre_trend.timeline],
        }

        return {
            "genre": req_body.genre,
            "start_year": req_body.start_year,
            "end_year": req_body.end_year,
            "evolution_data": evolution_data,
            "status": "success",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"❌ Genre evolution error: {e}")
        raise HTTPException(status_code=500, detail=f"Genre evolution error: {e!s}") from e


@router.post("/similarity-network")
async def build_similarity_network_endpoint(request: Request, req_body: SimilarityNetworkRequest) -> dict[str, Any]:  # noqa: ARG001
    """Build similarity network for an artist.

    Creates a network of similar artists based on collaboration and genre patterns.

    Args:
        request: FastAPI request object (required for rate limiting)
        req_body: Request parameters

    Returns:
        Dictionary with network nodes and edges

    Raises:
        HTTPException: If graph API not initialized
    """
    if not graph_api_initialized or similarity_network_builder is None:
        raise HTTPException(status_code=503, detail="Graph Analytics API not initialized")

    logger.info(
        "📊 Similarity network request",
        artist_id=req_body.artist_id,
        max_depth=req_body.max_depth,
    )

    try:
        # Build similarity network starting from the seed artist
        # Use artist_id as the seed artist name (API uses IDs, component uses names)
        graph = await similarity_network_builder.build_similarity_network(
            artist_list=[req_body.artist_id],
            similarity_threshold=req_body.similarity_threshold,
            max_artists=req_body.max_nodes,
            similarity_method="collaboration",
        )

        # Convert NetworkX graph to nodes and edges format
        nodes = [{"id": node, "label": node} for node in graph.nodes()]
        edges = [{"source": u, "target": v, "weight": float(graph[u][v].get("weight", 1.0))} for u, v in graph.edges()]

        return {
            "artist_id": req_body.artist_id,
            "max_depth": req_body.max_depth,
            "nodes": nodes,
            "edges": edges,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "status": "success",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"❌ Similarity network error: {e}")
        raise HTTPException(status_code=500, detail=f"Similarity network error: {e!s}") from e


@router.get("/stats")
async def get_graph_stats(request: Request) -> dict[str, Any]:  # noqa: ARG001
    """Get graph statistics.

    Returns statistics about the graph structure and metrics.

    Note: Graph-wide statistics require building networks first.
    This endpoint returns placeholder data. Use specific endpoints
    (centrality, communities, etc.) for detailed graph analysis.

    Args:
        request: FastAPI request object (required for rate limiting)

    Returns:
        Dictionary with graph statistics
    """
    if not graph_api_initialized:
        raise HTTPException(status_code=503, detail="Graph Analytics API not initialized")

    logger.info("📊 Graph statistics request")

    # Note: Graph-wide statistics require building networks which is expensive
    # Future enhancement: Cache network statistics or implement lightweight query
    return {
        "statistics": {
            "total_nodes": 0,
            "total_edges": 0,
            "node_types": {},
            "edge_types": {},
        },
        "status": "partial",
        "message": "Graph statistics require building networks. Use specific endpoints for analysis.",
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/status")
async def get_graph_api_status(request: Request) -> dict[str, Any]:  # noqa: ARG001
    """Get Graph Analytics API status and feature availability.

    Args:
        request: FastAPI request object (required for rate limiting)

    Returns:
        Dictionary with API status and available features
    """
    return {
        "status": "initialized" if graph_api_initialized else "not_initialized",
        "features": {
            "centrality_metrics": "active" if centrality_analyzer is not None else "unavailable",
            "community_detection": "active" if community_detector is not None else "unavailable",
            "genre_evolution": "active" if genre_evolution_tracker is not None else "unavailable",
            "similarity_networks": "active" if similarity_network_builder is not None else "unavailable",
            "statistics": "partial",
        },
        "components": {
            "centrality_analyzer": centrality_analyzer is not None,
            "community_detector": community_detector is not None,
            "genre_evolution_tracker": genre_evolution_tracker is not None,
            "similarity_network_builder": similarity_network_builder is not None,
        },
        "phase": "4.2 (Full Implementation)",
        "notes": {
            "statistics": "Graph-wide stats require network building. Use specific analysis endpoints.",
        },
        "timestamp": datetime.now().isoformat(),
    }

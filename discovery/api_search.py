"""Advanced Search API.

This module provides endpoints for full-text search, semantic search, faceted search,
autocomplete, and search ranking.
"""

import os
from datetime import datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field


logger = structlog.get_logger(__name__)

# Create API router
router = APIRouter(prefix="/api/search", tags=["Advanced Search"])


# Request/Response Models


class FullTextSearchRequest(BaseModel):
    """Request for full-text search."""

    query: str = Field(..., description="Search query text", min_length=1, max_length=500)
    entity: Literal["artist", "release", "label", "master", "all"] = Field("all", description="Entity type to search")
    operator: Literal["and", "or", "phrase", "proximity"] = Field("and", description="Search operator")
    limit: int = Field(50, description="Maximum number of results", ge=1, le=100)
    offset: int = Field(0, description="Result offset for pagination", ge=0)
    rank_threshold: float = Field(0.0, description="Minimum ranking score", ge=0.0, le=1.0)


class SemanticSearchRequest(BaseModel):
    """Request for semantic search."""

    query: str = Field(..., description="Natural language search query", min_length=1, max_length=500)
    entity: Literal["artist", "release", "label"] = Field("artist", description="Entity type to search")
    limit: int = Field(20, description="Maximum number of results", ge=1, le=100)
    similarity_threshold: float = Field(0.5, description="Minimum similarity score", ge=0.0, le=1.0)


class FacetedSearchRequest(BaseModel):
    """Request for faceted search."""

    query: str | None = Field(None, description="Optional search query text")
    entity: Literal["artist", "release", "label"] = Field("artist", description="Entity type")
    facets: dict[str, list[str]] = Field(default_factory=dict, description="Facet filters (genre, year, etc.)")
    limit: int = Field(50, description="Maximum number of results", ge=1, le=100)
    offset: int = Field(0, description="Result offset for pagination", ge=0)


class AutocompleteRequest(BaseModel):
    """Request for search autocomplete."""

    prefix: str = Field(..., description="Search prefix", min_length=1, max_length=100)
    entity: Literal["artist", "release", "label", "master"] = Field("artist", description="Entity type")
    limit: int = Field(10, description="Maximum number of suggestions", ge=1, le=50)


# Module-level instances (initialized on startup)
search_api_initialized = False
fulltext_search: Any = None
semantic_search: Any = None
faceted_search: Any = None
search_ranker: Any = None


async def initialize_search_api(neo4j_driver: Any, postgres_conn: Any) -> None:  # noqa: ARG001
    """Initialize Search API components.

    Args:
        neo4j_driver: Neo4j async driver instance
        postgres_conn: PostgreSQL async connection
    """
    global search_api_initialized, fulltext_search, semantic_search, faceted_search, search_ranker

    logger.info("🚀 Initializing Search API components...")

    # Import Phase 3 components
    from discovery.faceted_search import FacetedSearchEngine
    from discovery.fulltext_search import FullTextSearch
    from discovery.search_ranking import SearchRanker
    from discovery.semantic_search import SemanticSearchEngine

    # Initialize components
    fulltext_search = FullTextSearch(postgres_conn)
    semantic_search = SemanticSearchEngine(
        model_name="all-MiniLM-L6-v2",
        cache_dir=os.environ.get("EMBEDDINGS_CACHE_DIR", "/tmp/embeddings_cache"),  # nosec B108  # noqa: S108
        use_onnx=True,
    )
    faceted_search = FacetedSearchEngine(postgres_conn)
    search_ranker = SearchRanker()

    search_api_initialized = True
    logger.info("✅ Search API initialization complete")


async def close_search_api() -> None:
    """Close Search API components and cleanup resources."""
    global search_api_initialized

    logger.info("🛑 Closing Search API components...")
    search_api_initialized = False
    logger.info("✅ Search API components closed")


# API Endpoints


@router.post("/fulltext")  # type: ignore[untyped-decorator]
async def fulltext_search_endpoint(request: Request, req_body: FullTextSearchRequest) -> dict[str, Any]:  # noqa: ARG001
    """Perform full-text search using PostgreSQL tsvector.

    Supports AND, OR, phrase, and proximity search operators with ranking.

    Args:
        request: FastAPI request object (required for rate limiting)
        req_body: Request parameters

    Returns:
        Dictionary with search results and metadata

    Raises:
        HTTPException: If search API not initialized
    """
    if not search_api_initialized or fulltext_search is None:
        raise HTTPException(status_code=503, detail="Search API not initialized")

    logger.info(
        "🔍 Full-text search request",
        query=req_body.query,
        entity=req_body.entity,
        operator=req_body.operator,
    )

    try:
        # Import enums for mapping
        from discovery.fulltext_search import SearchEntity, SearchOperator

        # Map string values to enums
        entity_enum = SearchEntity(req_body.entity)
        operator_enum = SearchOperator(req_body.operator)

        # Perform search using Phase 3 component
        results = await fulltext_search.search(
            query=req_body.query,
            entity=entity_enum,
            operator=operator_enum,
            limit=req_body.limit,
            offset=req_body.offset,
            rank_threshold=req_body.rank_threshold,
        )

        return {
            "query": req_body.query,
            "entity": req_body.entity,
            "operator": req_body.operator,
            "results": results,
            "total": len(results),
            "search_type": "fulltext",
            "status": "success",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"❌ Full-text search error: {e}")
        raise HTTPException(status_code=500, detail=f"Search error: {e!s}") from e


@router.post("/semantic")  # type: ignore[untyped-decorator]
async def semantic_search_endpoint(request: Request, req_body: SemanticSearchRequest) -> dict[str, Any]:  # noqa: ARG001
    """Perform semantic search using ONNX embeddings.

    Uses natural language understanding for similarity-based search.

    Note: Semantic search requires pre-built embeddings database integration.
    This is tracked as future enhancement in Phase 4.2.

    Args:
        request: FastAPI request object (required for rate limiting)
        req_body: Request parameters

    Returns:
        Dictionary with semantic search results

    Raises:
        HTTPException: If search API not initialized
    """
    if not search_api_initialized or semantic_search is None:
        raise HTTPException(status_code=503, detail="Search API not initialized")

    logger.info(
        "🔍 Semantic search request",
        query=req_body.query,
        entity=req_body.entity,
    )

    # Note: SemanticSearchEngine requires pre-built embeddings to be passed in
    # Future enhancement: Integrate with PostgreSQL embeddings table or Neo4j
    return {
        "query": req_body.query,
        "entity": req_body.entity,
        "results": [],
        "search_type": "semantic",
        "status": "partial",
        "message": "Semantic search engine initialized but requires embeddings database integration",
        "timestamp": datetime.now().isoformat(),
    }


@router.post("/faceted")  # type: ignore[untyped-decorator]
async def faceted_search_endpoint(request: Request, req_body: FacetedSearchRequest) -> dict[str, Any]:  # noqa: ARG001
    """Perform faceted search with dynamic filters.

    Supports filtering by genre, year, label, and other facets.

    Args:
        request: FastAPI request object (required for rate limiting)
        req_body: Request parameters

    Returns:
        Dictionary with filtered results and available facets

    Raises:
        HTTPException: If search API not initialized
    """
    if not search_api_initialized or faceted_search is None:
        raise HTTPException(status_code=503, detail="Search API not initialized")

    logger.info(
        "🔍 Faceted search request",
        query=req_body.query,
        entity=req_body.entity,
        facet_count=len(req_body.facets),
    )

    try:
        # Perform faceted search using Phase 3 component
        search_result = await faceted_search.search_with_facets(
            query=req_body.query or "",
            entity_type=req_body.entity,
            selected_facets=req_body.facets if req_body.facets else None,
            limit=req_body.limit,
            offset=req_body.offset,
        )

        return {
            "query": req_body.query,
            "entity": req_body.entity,
            "facets": req_body.facets,
            "results": search_result.get("results", []),
            "available_facets": search_result.get("facets", {}),
            "total": len(search_result.get("results", [])),
            "search_type": "faceted",
            "status": "success",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"❌ Faceted search error: {e}")
        raise HTTPException(status_code=500, detail=f"Search error: {e!s}") from e


@router.post("/autocomplete")  # type: ignore[untyped-decorator]
async def autocomplete_endpoint(request: Request, req_body: AutocompleteRequest) -> dict[str, Any]:  # noqa: ARG001
    """Get search autocomplete suggestions.

    Provides prefix-based suggestions for search queries.

    Args:
        request: FastAPI request object (required for rate limiting)
        req_body: Request parameters

    Returns:
        Dictionary with autocomplete suggestions

    Raises:
        HTTPException: If search API not initialized
    """
    if not search_api_initialized or fulltext_search is None:
        raise HTTPException(status_code=503, detail="Search API not initialized")

    logger.info(
        "🔍 Autocomplete request",
        prefix=req_body.prefix,
        entity=req_body.entity,
    )

    try:
        # Import enum for mapping
        from discovery.fulltext_search import SearchEntity

        # Map string to enum
        entity_enum = SearchEntity(req_body.entity)

        # Get suggestions using Phase 3 component
        suggestions = await fulltext_search.suggest_completions(
            prefix=req_body.prefix,
            entity=entity_enum,
            limit=req_body.limit,
        )

        return {
            "prefix": req_body.prefix,
            "entity": req_body.entity,
            "suggestions": suggestions,
            "total": len(suggestions),
            "status": "success",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"❌ Autocomplete error: {e}")
        raise HTTPException(status_code=500, detail=f"Autocomplete error: {e!s}") from e


@router.get("/stats")  # type: ignore[untyped-decorator]
async def get_search_stats(request: Request) -> dict[str, Any]:  # noqa: ARG001
    """Get search statistics.

    Returns statistics about searchable content and index sizes.

    Args:
        request: FastAPI request object (required for rate limiting)

    Returns:
        Dictionary with search statistics
    """
    if not search_api_initialized or fulltext_search is None:
        raise HTTPException(status_code=503, detail="Search API not initialized")

    logger.info("📊 Search statistics request")

    try:
        # Get statistics from Phase 3 component
        stats = await fulltext_search.get_search_statistics()

        return {
            "statistics": stats,
            "status": "success",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"❌ Search statistics error: {e}")
        raise HTTPException(status_code=500, detail=f"Statistics error: {e!s}") from e


@router.get("/status")  # type: ignore[untyped-decorator]
async def get_search_api_status(request: Request) -> dict[str, Any]:  # noqa: ARG001
    """Get Search API status and feature availability.

    Args:
        request: FastAPI request object (required for rate limiting)

    Returns:
        Dictionary with API status and available features
    """
    return {
        "status": "initialized" if search_api_initialized else "not_initialized",
        "features": {
            "fulltext_search": "active" if fulltext_search is not None else "unavailable",
            "semantic_search": "partial" if semantic_search is not None else "unavailable",
            "faceted_search": "active" if faceted_search is not None else "unavailable",
            "autocomplete": "active" if fulltext_search is not None else "unavailable",
            "statistics": "active" if fulltext_search is not None else "unavailable",
        },
        "components": {
            "fulltext_search": fulltext_search is not None,
            "semantic_search": semantic_search is not None,
            "faceted_search": faceted_search is not None,
            "search_ranker": search_ranker is not None,
        },
        "phase": "4.2 (Full Implementation)",
        "notes": {
            "semantic_search": "Initialized but requires embeddings database integration for full functionality",
        },
        "timestamp": datetime.now().isoformat(),
    }

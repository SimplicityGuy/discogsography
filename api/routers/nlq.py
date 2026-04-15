"""NLQ router — natural language query endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
import structlog

from api.limiter import limiter
from api.nlq.config import NLQConfig
from api.nlq.engine import NLQContext, NLQEngine
from api.nlq.suggestions import build_suggestions


logger = structlog.get_logger(__name__)

router = APIRouter()
_SUGGESTIONS_CACHE_TTL = 300  # 5 minutes
_nlq_config: NLQConfig = NLQConfig()
_engine: NLQEngine | None = None
_redis: Any = None
_jwt_secret: str | None = None


def configure(nlq_config: NLQConfig, engine: NLQEngine | None, redis: Any = None, jwt_secret: str | None = None) -> None:
    """Wire NLQ config, engine, Redis, and JWT secret into the router."""
    global _nlq_config, _engine, _redis, _jwt_secret
    _nlq_config = nlq_config
    _engine = engine
    _redis = redis
    _jwt_secret = jwt_secret


class NLQQueryRequest(BaseModel):
    """Request body for NLQ query endpoint."""

    query: str
    context: dict[str, Any] | None = None


def _extract_user_id(request: Request) -> str | None:
    """Extract user_id from an optional Bearer token. Returns None if missing or invalid."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[7:]
    try:
        from api.auth import decode_token  # noqa: PLC0415

        if _jwt_secret is None:
            return None
        payload = decode_token(token, _jwt_secret)
        if payload.get("type") == "admin":
            return None
        return payload.get("sub")
    except (ValueError, Exception):
        return None


def _cache_key(query: str) -> str:
    """Build a Redis cache key from a normalized query."""
    normalized = query.strip().lower()
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return f"nlq:{digest}"


@router.get("/api/nlq/suggestions")
@limiter.limit("100/minute")
async def nlq_suggestions(
    request: Request,  # noqa: ARG001
    pane: str = "explore",
    focus: str | None = None,
    focus_type: str | None = None,
) -> JSONResponse:
    """Return dynamic suggested queries for the Ask pill."""
    cache_key = f"nlq:suggest:{pane}:{focus or ''}:{focus_type or ''}"
    if _redis is not None:
        try:
            cached = await _redis.get(cache_key)
            if cached is not None:
                return JSONResponse(content=json.loads(cached))
        except Exception:
            logger.debug("⚠️ NLQ suggestions cache read failed", key=cache_key)

    suggestions = build_suggestions(pane=pane, focus=focus, focus_type=focus_type)
    payload = {"suggestions": suggestions}

    if _redis is not None:
        try:
            await _redis.setex(cache_key, _SUGGESTIONS_CACHE_TTL, json.dumps(payload))
        except Exception:
            logger.debug("⚠️ NLQ suggestions cache write failed", key=cache_key)

    return JSONResponse(content=payload)


@router.get("/api/nlq/status")
async def nlq_status() -> JSONResponse:
    """Return whether NLQ is enabled."""
    return JSONResponse(content={"enabled": _nlq_config.is_available})


@router.post("/api/nlq/query")
@limiter.limit("10/minute")
async def nlq_query(request: Request, body: NLQQueryRequest) -> Any:
    """Run a natural language query against the knowledge graph."""
    # Validate query
    if not body.query or not body.query.strip():
        return JSONResponse(content={"error": "Query must not be empty"}, status_code=400)
    if len(body.query) > _nlq_config.max_query_length:
        return JSONResponse(
            content={"error": f"Query exceeds maximum length of {_nlq_config.max_query_length} characters"},
            status_code=400,
        )

    # Check availability
    if not _nlq_config.is_available or _engine is None:
        return JSONResponse(content={"error": "NLQ is not available"}, status_code=503)

    # Extract optional user_id from Bearer token
    user_id = _extract_user_id(request)

    # Check Redis cache for public (unauthenticated) queries
    if user_id is None and _redis is not None:
        cache_k = _cache_key(body.query)
        try:
            cached = await _redis.get(cache_k)
            if cached is not None:
                cached_data = json.loads(cached)
                cached_data["cached"] = True
                return JSONResponse(content=cached_data)
        except Exception:
            logger.debug("⚠️ NLQ cache read failed", key=cache_k)

    # Check for SSE request
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        return _stream_response(body.query, user_id, body.context)

    # Build context
    ctx = NLQContext(
        user_id=user_id,
        current_entity_id=body.context.get("entity_id") if body.context else None,
        current_entity_type=body.context.get("entity_type") if body.context else None,
    )

    # Run engine
    result = await _engine.run(body.query, ctx)

    response_data = {
        "query": body.query,
        "summary": result.summary,
        "entities": result.entities,
        "tools_used": result.tools_used,
        "actions": [action.model_dump(by_alias=True, mode="json") for action in result.actions],
        "cached": False,
    }

    # Cache public results
    if user_id is None and _redis is not None:
        cache_k = _cache_key(body.query)
        try:
            await _redis.setex(cache_k, _nlq_config.cache_ttl, json.dumps(response_data))
        except Exception:
            logger.debug("⚠️ NLQ cache write failed", key=cache_k)

    return JSONResponse(content=response_data)


def _stream_response(query: str, user_id: str | None, context: dict[str, Any] | None) -> EventSourceResponse:
    """Return an SSE EventSourceResponse that streams NLQ status and result."""

    async def event_generator() -> Any:
        ctx = NLQContext(
            user_id=user_id,
            current_entity_id=context.get("entity_id") if context else None,
            current_entity_type=context.get("entity_type") if context else None,
        )

        status_queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def emit_status(step: str) -> None:
            await status_queue.put(step)

        if _engine is None:  # pragma: no cover — guarded by caller
            return

        # Run engine in background so status events can be yielded as they arrive
        engine_task = asyncio.create_task(_engine.run(query, ctx, on_status=emit_status))

        # Yield status events as they arrive
        while not engine_task.done():
            try:
                step = await asyncio.wait_for(status_queue.get(), timeout=0.1)
                yield {"event": "status", "data": json.dumps({"step": step})}
            except TimeoutError:
                continue

        # Drain any remaining status events
        while not status_queue.empty():
            step = status_queue.get_nowait()
            yield {"event": "status", "data": json.dumps({"step": step})}

        try:
            result = await engine_task
        except Exception as exc:
            logger.error("❌ NLQ engine error", error=str(exc), exc_info=True)
            yield {"event": "error", "data": json.dumps({"error": "An internal error occurred"})}
            return

        # Emit actions event before result so the client can snapshot and apply
        yield {
            "event": "actions",
            "data": json.dumps({"actions": [action.model_dump(by_alias=True, mode="json") for action in result.actions]}),
        }

        # Emit final result
        response_data = {
            "query": query,
            "summary": result.summary,
            "entities": result.entities,
            "tools_used": result.tools_used,
            "cached": False,
        }
        yield {"event": "result", "data": json.dumps(response_data)}

    return EventSourceResponse(event_generator())

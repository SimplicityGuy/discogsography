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


async def _extract_user_id(request: Request) -> str | None:
    """Extract user_id from an optional Bearer token. Returns None if missing, invalid, or revoked.

    Async because revocation state lives in Redis: a resolved user_id unlocks the
    authenticated collection tools, so a logged-out or password-changed token must
    NOT resolve here either (discogsography-aexv). Any failure — bad token, Redis
    error — fails closed to None, i.e. an anonymous/public query.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[7:]
    try:
        from api.auth import decode_token, token_revocation_reason  # noqa: PLC0415

        if _jwt_secret is None:
            return None
        payload = decode_token(token, _jwt_secret)
        # Allowlist: only pure access tokens (no `type` claim) resolve to a user.
        # Admin and 2FA challenge tokens must not be treated as an authenticated user.
        if payload.get("type") is not None:
            return None
        # Signature and exp alone do not make a token current — logout and
        # password change revoke it in Redis, exactly as every other auth site checks.
        if await token_revocation_reason(payload, _redis) is not None:
            return None
        return payload.get("sub")
    except (ValueError, Exception):
        return None


def _cache_key(query: str, context: dict[str, Any] | None = None) -> str:
    """Build a Redis cache key from a normalized query and its entity context.

    The engine now resolves deictic references ("this artist") using
    ``current_entity_id``/``current_entity_type`` (discogsography-xcsx), so the
    same query text can produce a different answer depending on which entity is
    focused. The cache key MUST include that context — keying on query text
    alone would serve one focused entity's cached answer to a different
    anonymous user asking the identical question about a different entity.
    """
    normalized = query.strip().lower()
    entity_id = (context or {}).get("entity_id") or ""
    entity_type = (context or {}).get("entity_type") or ""
    digest = hashlib.sha256(f"{normalized}\x00{entity_type}\x00{entity_id}".encode()).hexdigest()[:16]
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
    user_id = await _extract_user_id(request)

    # Determine the response mode BEFORE consulting the cache. A streaming client
    # must ALWAYS receive an event stream — never a plain JSON cache body, which
    # its SSE parser cannot read, hanging the Ask UI. See discogsography-cu2.27.
    accept = request.headers.get("accept", "")
    wants_stream = "text/event-stream" in accept

    # Check Redis cache for public (unauthenticated) queries
    cached_data: dict[str, Any] | None = None
    if user_id is None and _redis is not None:
        cache_k = _cache_key(body.query, body.context)
        try:
            cached = await _redis.get(cache_k)
            if cached is not None:
                cached_data = json.loads(cached)
                cached_data["cached"] = True
        except Exception:
            logger.debug("⚠️ NLQ cache read failed", key=cache_k)

    # Streaming clients get an event stream regardless of cache state — a cache
    # hit is replayed as synthetic SSE events inside _stream_response.
    if wants_stream:
        return _stream_response(body.query, user_id, body.context, cached=cached_data)

    if cached_data is not None:
        return JSONResponse(content=cached_data)

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
        cache_k = _cache_key(body.query, body.context)
        try:
            await _redis.setex(cache_k, _nlq_config.cache_ttl, json.dumps(response_data))
        except Exception:
            logger.debug("⚠️ NLQ cache write failed", key=cache_k)

    return JSONResponse(content=response_data)


def _stream_response(
    query: str,
    user_id: str | None,
    context: dict[str, Any] | None,
    cached: dict[str, Any] | None = None,
) -> EventSourceResponse:
    """Return an SSE EventSourceResponse that streams NLQ status and result.

    When ``cached`` is provided (a prior JSON cache hit), the cached result is
    replayed as synthetic actions/result SSE events instead of re-running the
    engine — so a streaming client always receives a well-formed event stream.
    """

    async def event_generator() -> Any:
        # Replay a cached result as synthetic SSE events so a streaming client
        # never hangs on a plain JSON cache body. See discogsography-cu2.27.
        if cached is not None:
            cached_actions = cached.get("actions", [])
            yield {"event": "actions", "data": json.dumps({"actions": cached_actions})}
            yield {
                "event": "result",
                "data": json.dumps(
                    {
                        "query": cached.get("query", query),
                        "summary": cached.get("summary"),
                        "entities": cached.get("entities"),
                        "tools_used": cached.get("tools_used"),
                        # Mirror the non-streaming JSON body: actions travel on the
                        # result frame too, not only the sideband event. See
                        # discogsography-l6fm.
                        "actions": cached_actions,
                        "cached": True,
                    }
                ),
            }
            return

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

        try:
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
            actions_payload = [action.model_dump(by_alias=True, mode="json") for action in result.actions]
            yield {
                "event": "actions",
                "data": json.dumps({"actions": actions_payload}),
            }

            # Emit final result. `actions` is repeated here on purpose: the
            # non-streaming JSON body and the Redis cache entry both carry it on
            # the result object, and a client that only subscribes to `result`
            # would otherwise apply nothing at all. See discogsography-l6fm.
            response_data = {
                "query": query,
                "summary": result.summary,
                "entities": result.entities,
                "tools_used": result.tools_used,
                "actions": actions_payload,
                "cached": False,
            }

            # Cache public results — mirrors the non-streaming branch below.
            # This is the only client the production UI uses (nlq.js always sends
            # Accept: text/event-stream), so without this write the query cache and
            # its cached-replay path above are permanently unpopulated. Written
            # before the "result" yield: a client disconnect raises GeneratorExit
            # at that yield, and a write placed after it would never run.
            # See discogsography-c584.
            if user_id is None and _redis is not None:
                cache_k = _cache_key(query, context)
                try:
                    await _redis.setex(cache_k, _nlq_config.cache_ttl, json.dumps(response_data))
                except Exception:
                    logger.debug("⚠️ NLQ cache write failed", key=cache_k)

            yield {"event": "result", "data": json.dumps(response_data)}
        finally:
            # Client disconnect raises GeneratorExit at the current yield; cancel
            # the still-running engine task so the Anthropic/Neo4j work does not
            # leak and the pending task cannot be GC'd mid-flight. gather with
            # return_exceptions swallows the resulting CancelledError. See
            # discogsography-cu2.28.
            if not engine_task.done():
                engine_task.cancel()
                await asyncio.gather(engine_task, return_exceptions=True)

    return EventSourceResponse(event_generator())

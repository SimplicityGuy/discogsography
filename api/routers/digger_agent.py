"""POST /api/digger/agent/message — SSE-streamed agent chat turn + session list.

Flow for a turn:
1. Confirm the caller has digger enabled (403 otherwise).
2. Reject if the caller's daily interactive token cap is exhausted (429).
3. Acquire a per-user concurrency lock and run one agent turn, streaming typed
   SSE events (text, tool_call, tool_result, bundle_card, proposal_card, done).
4. On completion, persist the assistant message, roll up token totals + cost,
   and record the spend against the daily budget.

DI mirrors ``api/routers/digger_recommend.py``: module-global pool/redis injected
via ``configure()`` with 503-guard accessors (not FastAPI ``Depends``).
"""

from __future__ import annotations

from decimal import Decimal
import json
import logging
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.dependencies import require_user
from api.digger_agent.guardrails import ConcurrencyLock, TokenBudget
from api.digger_agent.memory import build_message_history
from api.digger_agent.runtime import run_agent_turn
from api.digger_agent.tools.context import ToolContext
from api.queries import digger_agent_queries as aq, digger_queries as q


if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncIterator

    import redis.asyncio as aioredis

    from common import AsyncPostgreSQLPool


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/digger/agent", tags=["digger-agent"])

_pool: AsyncPostgreSQLPool | None = None
_redis: aioredis.Redis | None = None
_anthropic_api_key: str | None = None


def configure(pool: AsyncPostgreSQLPool, redis: aioredis.Redis, anthropic_api_key: str | None = None) -> None:
    """Inject the Postgres pool, Redis client, and Anthropic API key at startup."""
    global _pool, _redis, _anthropic_api_key
    _pool = pool
    _redis = redis
    _anthropic_api_key = anthropic_api_key


def _get_pool() -> AsyncPostgreSQLPool:
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    return _pool


def _get_redis() -> aioredis.Redis:
    if _redis is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    return _redis


class MessageIn(BaseModel):
    user_message: str = Field(min_length=1, max_length=4000)
    session_id: UUID | None = None
    model_override: str | None = None


# USD per 1M tokens, by model alias (display-only; feeds agent_sessions.total_cost_usd).
_COST_PER_M = {
    "haiku": {"in": 1.0, "out": 5.0, "cache_read": 0.10},
    "sonnet": {"in": 3.0, "out": 15.0, "cache_read": 0.30},
    "opus": {"in": 15.0, "out": 75.0, "cache_read": 1.50},
}


def _estimate_cost_usd(model: str, usage: dict[str, Any]) -> Decimal:
    """Estimate this turn's spend in USD from token usage (unknown models bill as sonnet)."""
    p = _COST_PER_M.get(model, _COST_PER_M["sonnet"])
    return (
        Decimal(usage["input"]) * Decimal(str(p["in"])) / 1_000_000
        + Decimal(usage["output"]) * Decimal(str(p["out"])) / 1_000_000
        + Decimal(usage["cache_read"]) * Decimal(str(p["cache_read"])) / 1_000_000
    )


@router.post("/message")
async def message(body: MessageIn, current_user: Annotated[dict[str, Any], Depends(require_user)]) -> EventSourceResponse:
    """Run one agent turn for the caller, streaming typed SSE events."""
    pool = _get_pool()
    redis = _get_redis()
    user_id = UUID(current_user["sub"])

    settings_row = await q.get_user_settings(pool, user_id)
    if settings_row is None or not settings_row.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="digger not enabled")

    model = body.model_override or settings_row.preferred_model
    budget = TokenBudget(redis=redis, daily_cap=settings_row.daily_token_cap_interactive, kind="interactive")
    if await budget.is_exceeded(user_id):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="daily token cap exceeded")

    lock = ConcurrencyLock(redis=redis)
    client = anthropic.AsyncAnthropic(api_key=_anthropic_api_key)

    session_id = body.session_id or await aq.create_session(pool, user_id, model=model)
    await aq.append_message(pool, session_id, role="user", content=[{"type": "text", "text": body.user_message}])

    async def stream_events() -> AsyncIterator[dict[str, str]]:
        try:
            async with lock.acquire(user_id):
                history, anchor = await build_message_history(pool, session_id, client=client)
                messages: list[dict[str, Any]] = []
                if anchor is not None:
                    messages.append(anchor)
                messages.extend(history)

                ctx = ToolContext(pool=pool, redis=redis, user_id=user_id, session_id=session_id)
                final_messages: list[dict[str, Any]] | None = None
                final_usage: dict[str, Any] | None = None
                async for ev in run_agent_turn(client=client, model=model, ctx=ctx, messages=messages, max_iterations=8):
                    if ev["type"] == "done":
                        final_messages = ev["messages_after"]
                        final_usage = ev["usage"]
                        yield {"event": "done", "data": json.dumps({"session_id": str(session_id), "usage": final_usage})}
                    else:
                        yield {"event": ev["type"], "data": json.dumps({k: v for k, v in ev.items() if k != "type"})}

                if final_messages is not None:
                    last = final_messages[-1]
                    if last["role"] == "assistant":
                        await aq.append_message(pool, session_id, role="assistant", content=last["content"], token_counts=final_usage)
                if final_usage is not None:
                    cost = _estimate_cost_usd(model, final_usage)
                    await aq.update_token_totals(
                        pool,
                        session_id,
                        input_tokens=final_usage["input"],
                        output_tokens=final_usage["output"],
                        cache_read=final_usage["cache_read"],
                        cost_usd=cost,
                    )
                    await budget.record(user_id, input_tokens=final_usage["input"], output_tokens=final_usage["output"])
        except RuntimeError as exc:
            yield {"event": "error", "data": json.dumps({"reason": str(exc)})}

    return EventSourceResponse(stream_events())


class AgentSessionItem(BaseModel):
    session_id: str
    started_at: str
    last_active_at: str
    total_cost_usd: float


class AgentSessionList(BaseModel):
    items: list[AgentSessionItem]


@router.get("/sessions", response_model=AgentSessionList)
async def list_sessions(current_user: Annotated[dict[str, Any], Depends(require_user)]) -> AgentSessionList:
    """Return the caller's recent agent sessions, most recently active first."""
    pool = _get_pool()
    user_id = UUID(current_user["sub"])
    items = await aq.list_sessions(pool, user_id)
    return AgentSessionList(items=[AgentSessionItem(**it) for it in items])

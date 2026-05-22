"""Tests for the digger agent session/message persistence queries (mock-based)."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import uuid

from psycopg.types.json import Jsonb
import pytest

from api.queries.digger_agent_queries import (
    append_message,
    create_session,
    list_messages,
    update_token_totals,
)


@pytest.mark.asyncio
async def test_create_session_inserts_and_returns_uuid(mock_pool: MagicMock, mock_cur: AsyncMock) -> None:
    user_id = uuid.uuid4()
    session_id = await create_session(mock_pool, user_id, model="sonnet")
    assert isinstance(session_id, uuid.UUID)
    sql, params = mock_cur.execute.await_args.args
    assert "INSERT INTO digger.agent_sessions" in sql
    assert params == (session_id, user_id, "sonnet")


@pytest.mark.asyncio
async def test_append_message_inserts_and_touches_session(mock_pool: MagicMock, mock_cur: AsyncMock) -> None:
    session_id = uuid.uuid4()
    content = [{"type": "text", "text": "hi"}]
    message_id = await append_message(mock_pool, session_id, role="user", content=content)
    assert isinstance(message_id, uuid.UUID)
    calls = mock_cur.execute.await_args_list
    assert "INSERT INTO digger.agent_messages" in calls[0].args[0]
    insert_params = calls[0].args[1]
    assert isinstance(insert_params[3], Jsonb)  # content wrapped for jsonb
    assert insert_params[4] is None  # no token_counts
    assert "UPDATE digger.agent_sessions" in calls[1].args[0]


@pytest.mark.asyncio
async def test_append_message_with_token_counts(mock_pool: MagicMock, mock_cur: AsyncMock) -> None:
    session_id = uuid.uuid4()
    await append_message(
        mock_pool,
        session_id,
        role="assistant",
        content=[{"type": "text", "text": "hello"}],
        token_counts={"input": 10, "output": 5},
    )
    insert_params = mock_cur.execute.await_args_list[0].args[1]
    assert isinstance(insert_params[4], Jsonb)


@pytest.mark.asyncio
async def test_list_messages_returns_role_and_content(mock_pool: MagicMock, mock_cur: AsyncMock) -> None:
    mock_cur.fetchall.return_value = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
    ]
    session_id = uuid.uuid4()
    msgs = await list_messages(mock_pool, session_id)
    assert len(msgs) == 2
    assert msgs[0] == {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    sql, params = mock_cur.execute.await_args.args
    assert "ORDER BY created_at ASC" in sql
    assert params == (session_id,)


@pytest.mark.asyncio
async def test_update_token_totals_increments(mock_pool: MagicMock, mock_cur: AsyncMock) -> None:
    session_id = uuid.uuid4()
    await update_token_totals(mock_pool, session_id, input_tokens=10, output_tokens=5, cache_read=3, cost_usd=0.001)
    sql, params = mock_cur.execute.await_args.args
    assert "total_input_tokens = total_input_tokens + %s" in sql
    assert params == (10, 5, 3, Decimal("0.001"), session_id)

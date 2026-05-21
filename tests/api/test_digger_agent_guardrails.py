"""Tests for the digger agent guardrails (daily token cap + concurrency lock).

Uses a real fakeredis async client (the plan's ``redis_test_client`` fixture
does not exist in this repo).
"""

import uuid

import fakeredis.aioredis as aioredis_fake
import pytest

from api.digger_agent.guardrails import ConcurrencyLock, TokenBudget


@pytest.fixture
def redis_client() -> aioredis_fake.FakeRedis:
    return aioredis_fake.FakeRedis()


@pytest.mark.asyncio
async def test_token_budget_records_and_blocks_over_cap(redis_client: aioredis_fake.FakeRedis) -> None:
    user_id = uuid.uuid4()
    budget = TokenBudget(redis=redis_client, daily_cap=100, kind="interactive")
    total = await budget.record(user_id, input_tokens=30, output_tokens=20)
    assert total == 50
    assert await budget.remaining(user_id) == 50
    assert await budget.is_exceeded(user_id) is False
    await budget.record(user_id, input_tokens=60, output_tokens=0)
    assert await budget.is_exceeded(user_id) is True


@pytest.mark.asyncio
async def test_token_budget_remaining_floors_at_zero(redis_client: aioredis_fake.FakeRedis) -> None:
    user_id = uuid.uuid4()
    budget = TokenBudget(redis=redis_client, daily_cap=100, kind="scheduled")
    await budget.record(user_id, input_tokens=200, output_tokens=0)
    assert await budget.remaining(user_id) == 0


@pytest.mark.asyncio
async def test_token_budget_kinds_are_independent(redis_client: aioredis_fake.FakeRedis) -> None:
    user_id = uuid.uuid4()
    interactive = TokenBudget(redis=redis_client, daily_cap=100, kind="interactive")
    scheduled = TokenBudget(redis=redis_client, daily_cap=100, kind="scheduled")
    await interactive.record(user_id, input_tokens=80, output_tokens=0)
    assert await scheduled.remaining(user_id) == 100


@pytest.mark.asyncio
async def test_concurrency_lock_rejects_second(redis_client: aioredis_fake.FakeRedis) -> None:
    user_id = uuid.uuid4()
    lock = ConcurrencyLock(redis=redis_client, ttl_seconds=10)
    async with lock.acquire(user_id):
        with pytest.raises(RuntimeError):
            async with lock.acquire(user_id):
                pass


@pytest.mark.asyncio
async def test_concurrency_lock_releases_on_exit(redis_client: aioredis_fake.FakeRedis) -> None:
    user_id = uuid.uuid4()
    lock = ConcurrencyLock(redis=redis_client, ttl_seconds=10)
    async with lock.acquire(user_id):
        pass
    # A second acquire after the first released must succeed.
    async with lock.acquire(user_id):
        pass


@pytest.mark.asyncio
async def test_concurrency_lock_per_user(redis_client: aioredis_fake.FakeRedis) -> None:
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    lock = ConcurrencyLock(redis=redis_client, ttl_seconds=10)
    async with lock.acquire(user_a), lock.acquire(user_b):
        pass  # different users do not block each other

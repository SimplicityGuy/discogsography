"""Tests for the digger OptimizerInput builder (Postgres -> OptimizerInput)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch
import uuid

import pytest

from api.digger_refresh.input_builder import build_optimizer_input
from api.queries.digger_queries import WantlistPriorityRow
from common.digger_optimizer.models import OptimizerInput


@pytest.mark.asyncio
async def test_build_optimizer_input_groups_tiers_and_attaches_listings(mock_pool: object, mock_cur: AsyncMock) -> None:
    user_id = uuid.uuid4()
    priorities = [
        WantlistPriorityRow(release_id=1, tier="must", min_media_condition="VG", min_sleeve_condition="VG", max_price_cents=None),
        WantlistPriorityRow(release_id=2, tier="nice", min_media_condition="VG", min_sleeve_condition="VG", max_price_cents=500),
        WantlistPriorityRow(release_id=3, tier="eventually", min_media_condition="VG", min_sleeve_condition="VG", max_price_cents=None),
    ]
    listing_rows = [
        {
            "listing_id": 101,
            "release_id": 1,
            "seller_id": 11,
            "price_value": Decimal("10.00"),
            "price_currency": "USD",
            "media_condition": "NM",
            "sleeve_condition": "NM",
        }
    ]
    seller_rows = [
        {
            "seller_id": 11,
            "region": "us",
            "country_code": "US",
            "shipping_policy": {"us": {"first_cents": 500, "additional_cents": 100, "currency": "USD"}},
            "feedback_score": Decimal("99.5"),
        }
    ]
    mock_cur.fetchall = AsyncMock(side_effect=[listing_rows, seller_rows])

    with patch("api.digger_refresh.input_builder.list_wantlist_priorities", AsyncMock(return_value=priorities)):
        inp = await build_optimizer_input(mock_pool, user_id, location="US", currency="USD")

    assert isinstance(inp, OptimizerInput)
    assert [c.release_id for c in inp.must_have_releases] == [1]
    assert [c.release_id for c in inp.nice_have_releases] == [2]
    assert [c.release_id for c in inp.eventually_releases] == [3]
    assert len(inp.candidate_listings) == 1
    assert inp.candidate_listings[0].seller_id == 11
    assert inp.sellers[11].region == "us"
    assert inp.sellers[11].shipping_policy is not None
    assert inp.sellers[11].shipping_policy["us"].first_cents == 500


@pytest.mark.asyncio
async def test_build_optimizer_input_empty_wantlist_returns_empty(mock_pool: object) -> None:
    user_id = uuid.uuid4()
    with patch("api.digger_refresh.input_builder.list_wantlist_priorities", AsyncMock(return_value=[])):
        inp = await build_optimizer_input(mock_pool, user_id, location="US")
    assert inp.must_have_releases == []
    assert inp.candidate_listings == []
    assert inp.sellers == {}


@pytest.mark.asyncio
async def test_build_optimizer_input_with_priorities_but_no_listings(mock_pool: object, mock_cur: AsyncMock) -> None:
    user_id = uuid.uuid4()
    priorities = [WantlistPriorityRow(release_id=1, tier="must", min_media_condition="VG", min_sleeve_condition="VG", max_price_cents=None)]
    mock_cur.fetchall = AsyncMock(return_value=[])  # listings query returns nothing -> no sellers fetched
    with patch("api.digger_refresh.input_builder.list_wantlist_priorities", AsyncMock(return_value=priorities)):
        inp = await build_optimizer_input(mock_pool, user_id, location="US")
    assert len(inp.must_have_releases) == 1
    assert inp.candidate_listings == []
    assert inp.sellers == {}

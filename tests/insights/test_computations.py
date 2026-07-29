"""Tests for insights computation orchestration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_failing_pool() -> AsyncMock:
    """Create a mock pool whose cursor.execute raises on the first call."""
    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock(side_effect=RuntimeError("DB error"))
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_pool = AsyncMock()
    mock_pool.connection = MagicMock(return_value=mock_conn)
    return mock_pool


def _make_mock_pool() -> AsyncMock:
    """Create a mock pool for storing results."""
    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=(1,))

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    # Support conn.transaction() as an async context manager
    mock_tx_cm = AsyncMock()
    mock_tx_cm.__aenter__ = AsyncMock(return_value=None)
    mock_tx_cm.__aexit__ = AsyncMock(return_value=None)
    mock_conn.transaction = MagicMock(return_value=mock_tx_cm)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_pool = AsyncMock()
    mock_pool.connection = MagicMock(return_value=mock_conn)
    return mock_pool


class TestFetchFromApi:
    @pytest.mark.asyncio
    async def test_basic_call_without_params_or_timeout(self) -> None:
        from insights.computations import _fetch_from_api, endpoint_timeout

        mock_response = MagicMock()
        mock_response.json.return_value = {"items": [{"id": 1}]}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        result = await _fetch_from_api(mock_client, "/api/test")

        # An unmapped path still gets the split default budget, never a scalar.
        mock_client.get.assert_called_once_with("/api/test", timeout=endpoint_timeout("/api/test"))
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_passes_params_when_provided(self) -> None:
        from insights.computations import _fetch_from_api, endpoint_timeout

        mock_response = MagicMock()
        mock_response.json.return_value = {"items": []}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        await _fetch_from_api(mock_client, "/api/test", params={"limit": 10})

        mock_client.get.assert_called_once_with("/api/test", params={"limit": 10}, timeout=endpoint_timeout("/api/test"))

    @pytest.mark.asyncio
    async def test_passes_timeout_when_provided(self) -> None:
        from insights.computations import _fetch_from_api

        mock_response = MagicMock()
        mock_response.json.return_value = {"items": []}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        await _fetch_from_api(mock_client, "/api/test", timeout=600.0)

        mock_client.get.assert_called_once_with("/api/test", timeout=600.0)

    @pytest.mark.asyncio
    async def test_passes_both_params_and_timeout(self) -> None:
        from insights.computations import _fetch_from_api

        mock_response = MagicMock()
        mock_response.json.return_value = {"items": [{"id": 1}]}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        result = await _fetch_from_api(mock_client, "/api/test", params={"limit": 5}, timeout=600.0)

        mock_client.get.assert_called_once_with("/api/test", params={"limit": 5}, timeout=600.0)
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_items_key(self) -> None:
        from insights.computations import _fetch_from_api

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "something"}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        result = await _fetch_from_api(mock_client, "/api/test")

        assert result == []


class TestDescribeError:
    """Guards against blank error log lines from message-less exceptions."""

    def test_includes_type_when_message_empty(self) -> None:
        """An exception with an empty str() (e.g. httpx.ReadTimeout) still names its type."""
        import httpx

        from insights.computations import describe_exception

        # httpx.ReadTimeout("") has an empty str(), which previously logged as error="".
        assert describe_exception(httpx.ReadTimeout("")) == "ReadTimeout"

    def test_includes_type_and_message_when_present(self) -> None:
        from insights.computations import describe_exception

        assert describe_exception(ValueError("boom")) == "ValueError: boom"


# Every compute_and_store_* entry point, with the API path it fetches. A
# ReadTimeout on that fetch must produce a log line + computation_log row that
# names "ReadTimeout" rather than the historical blank error="".
_COMPUTATION_ENTRY_POINTS = [
    ("compute_and_store_artist_centrality", "artist_centrality"),
    ("compute_and_store_genre_trends", "genre_trends"),
    ("compute_and_store_label_longevity", "label_longevity"),
    ("compute_and_store_anniversaries", "anniversaries"),
    ("compute_and_store_data_completeness", "data_completeness"),
    ("compute_and_store_community_enrichment", "community_enrichment"),
    ("compute_and_store_rarity", "release_rarity"),
]


class TestReadTimeoutIsDiagnosable:
    """Regression for the blank error="" production logs (discogsography-ggz6)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("func_name", "insight_type"), _COMPUTATION_ENTRY_POINTS)
    async def test_read_timeout_names_the_exception_type(self, func_name: str, insight_type: str) -> None:
        import httpx

        import insights.computations as computations

        func = getattr(computations, func_name)
        mock_client = AsyncMock()
        # httpx.ReadTimeout("") stringifies to "" — the exact production case.
        mock_client.get = AsyncMock(side_effect=httpx.ReadTimeout(""))
        mock_pool = _make_mock_pool()

        with (
            patch.object(computations.logger, "error") as mock_log_error,
            patch.object(computations, "_log_computation", new=AsyncMock()) as mock_log_computation,
            pytest.raises(httpx.ReadTimeout),
        ):
            await func(mock_client, mock_pool)

        # The structlog error call must carry a diagnosable error value.
        assert mock_log_error.call_count == 1
        logged_error = mock_log_error.call_args.kwargs["error"]
        assert logged_error == "ReadTimeout", f"{func_name} logged error={logged_error!r}"

        # ...and so must the persisted computation_log row.
        failure_calls = [c for c in mock_log_computation.await_args_list if c.args[2] == "failed"]
        assert len(failure_calls) == 1
        assert failure_calls[0].args[1] == insight_type
        assert failure_calls[0].kwargs["error_message"] == "ReadTimeout"

    @pytest.mark.asyncio
    async def test_run_all_computations_names_the_type_for_a_failed_member(self) -> None:
        import httpx

        import insights.computations as computations

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with (
            patch.object(computations, "compute_and_store_artist_centrality", side_effect=httpx.ReadTimeout("")),
            patch.object(computations, "compute_and_store_genre_trends", return_value=0),
            patch.object(computations, "compute_and_store_label_longevity", return_value=0),
            patch.object(computations, "compute_and_store_anniversaries", return_value=0),
            patch.object(computations, "compute_and_store_data_completeness", return_value=0),
            patch.object(computations, "compute_and_store_community_enrichment", return_value=0),
            patch.object(computations, "compute_and_store_rarity", return_value=0),
            patch.object(computations.logger, "error") as mock_log_error,
        ):
            await computations.run_all_computations(mock_client, mock_pool)

        assert mock_log_error.call_args.kwargs["error"] == "ReadTimeout"


class TestComputeAndStoreArtistCentrality:
    @pytest.mark.asyncio
    async def test_fetches_from_api_and_stores_results(self) -> None:
        from insights.computations import compute_and_store_artist_centrality

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {"artist_id": "a1", "artist_name": "Artist One", "edge_count": 100},
            ]
            rows = await compute_and_store_artist_centrality(mock_client, mock_pool)

        assert rows == 1
        mock_fetch.assert_called_once_with(mock_client, "/api/internal/insights/artist-centrality", {"limit": 100})

    @pytest.mark.asyncio
    async def test_handles_empty_results(self) -> None:
        from insights.computations import compute_and_store_artist_centrality

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = []
            rows = await compute_and_store_artist_centrality(mock_client, mock_pool)

        assert rows == 0

    @pytest.mark.asyncio
    async def test_filters_out_null_artist_names(self) -> None:
        from insights.computations import compute_and_store_artist_centrality

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {"artist_id": "a1", "artist_name": "Artist One", "edge_count": 100},
                {"artist_id": "a2", "artist_name": None, "edge_count": 90},
                {"artist_id": "a3", "artist_name": "", "edge_count": 80},
                {"artist_id": "a4", "artist_name": "Artist Four", "edge_count": 70},
            ]
            rows = await compute_and_store_artist_centrality(mock_client, mock_pool)

        assert rows == 2

    @pytest.mark.asyncio
    async def test_all_results_filtered_returns_zero(self) -> None:
        from insights.computations import compute_and_store_artist_centrality

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            # All results have None or empty names — should return 0 after filtering
            mock_fetch.return_value = [
                {"artist_id": "a1", "artist_name": None, "edge_count": 100},
                {"artist_id": "a2", "artist_name": "", "edge_count": 90},
            ]
            rows = await compute_and_store_artist_centrality(mock_client, mock_pool)

        assert rows == 0

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self) -> None:
        from insights.computations import compute_and_store_artist_centrality

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API unavailable")
            with pytest.raises(RuntimeError, match="API unavailable"):
                await compute_and_store_artist_centrality(mock_client, mock_pool)


class TestComputeAndStoreGenreTrends:
    @pytest.mark.asyncio
    async def test_fetches_and_stores(self) -> None:
        from insights.computations import compute_and_store_genre_trends

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {"genre": "Rock", "decade": 1990, "release_count": 5000},
            ]
            rows = await compute_and_store_genre_trends(mock_client, mock_pool)

        assert rows == 1

    @pytest.mark.asyncio
    async def test_handles_empty_results(self) -> None:
        from insights.computations import compute_and_store_genre_trends

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = []
            rows = await compute_and_store_genre_trends(mock_client, mock_pool)

        assert rows == 0

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self) -> None:
        from insights.computations import compute_and_store_genre_trends

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API unavailable")
            with pytest.raises(RuntimeError, match="API unavailable"):
                await compute_and_store_genre_trends(mock_client, mock_pool)


class TestComputeAndStoreLabelLongevity:
    @pytest.mark.asyncio
    async def test_fetches_and_stores(self) -> None:
        from insights.computations import compute_and_store_label_longevity

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "label_id": "l1",
                    "label_name": "Blue Note",
                    "first_year": 1939,
                    "last_year": 2025,
                    "years_active": 86,
                    "total_releases": 4500,
                    "peak_decade": 1960,
                },
            ]
            rows = await compute_and_store_label_longevity(mock_client, mock_pool)

        assert rows == 1

    @pytest.mark.asyncio
    async def test_handles_empty_results(self) -> None:
        from insights.computations import compute_and_store_label_longevity

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = []
            rows = await compute_and_store_label_longevity(mock_client, mock_pool)

        assert rows == 0

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self) -> None:
        from insights.computations import compute_and_store_label_longevity

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API unavailable")
            with pytest.raises(RuntimeError, match="API unavailable"):
                await compute_and_store_label_longevity(mock_client, mock_pool)


class TestComputeAndStoreAnniversaries:
    @pytest.mark.asyncio
    async def test_handles_empty_results(self) -> None:
        from insights.computations import compute_and_store_anniversaries

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = []
            rows = await compute_and_store_anniversaries(mock_client, mock_pool, current_year=2026, current_month=3)

        assert rows == 0

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self) -> None:
        from insights.computations import compute_and_store_anniversaries

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API unavailable")
            with pytest.raises(RuntimeError, match="API unavailable"):
                await compute_and_store_anniversaries(mock_client, mock_pool, current_year=2026, current_month=3)

    @pytest.mark.asyncio
    async def test_fetches_and_stores(self) -> None:
        from insights.computations import compute_and_store_anniversaries

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {"master_id": "m1", "title": "OK Computer", "artist_name": "Radiohead", "release_year": 1997},
            ]
            rows = await compute_and_store_anniversaries(mock_client, mock_pool, current_year=2022, current_month=6)

        # 2022-1997=25, which IS in milestone_years, so 1 row written
        assert rows == 1

    @pytest.mark.asyncio
    async def test_custom_milestone_years_passed_to_api(self) -> None:
        from insights.computations import compute_and_store_anniversaries

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()
        custom_milestones = [10, 20]

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {"master_id": "m1", "title": "Album", "artist_name": "Artist", "release_year": 2006},
            ]
            rows = await compute_and_store_anniversaries(
                mock_client,
                mock_pool,
                current_year=2026,
                current_month=3,
                milestone_years=custom_milestones,
            )

        # Verify milestones were passed to the API call
        mock_fetch.assert_called_once_with(
            mock_client,
            "/api/internal/insights/anniversaries",
            {"year": 2026, "month": 3, "milestones": "10,20"},
        )
        # 2026-2006=20, which IS in custom_milestones
        assert rows == 1

    @pytest.mark.asyncio
    async def test_custom_milestone_years_filters_results(self) -> None:
        from insights.computations import compute_and_store_anniversaries

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {"master_id": "m1", "title": "Album", "artist_name": "Artist", "release_year": 2016},
            ]
            # 2026-2016=10, but milestone_years=[20] so should NOT be stored
            rows = await compute_and_store_anniversaries(
                mock_client,
                mock_pool,
                current_year=2026,
                current_month=3,
                milestone_years=[20],
            )

        assert rows == 0


class TestComputeAndStoreDataCompleteness:
    @pytest.mark.asyncio
    async def test_fetches_and_stores(self) -> None:
        from insights.computations import compute_and_store_data_completeness

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "entity_type": "releases",
                    "total_count": 15000000,
                    "with_image": 12000000,
                    "with_year": 14500000,
                    "with_country": 13000000,
                    "with_genre": 14000000,
                    "completeness_pct": 89.67,
                },
            ]
            rows = await compute_and_store_data_completeness(mock_client, mock_pool)

        assert rows == 1

    @pytest.mark.asyncio
    async def test_handles_empty_results(self) -> None:
        from insights.computations import compute_and_store_data_completeness

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = []
            rows = await compute_and_store_data_completeness(mock_client, mock_pool)

        assert rows == 0

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self) -> None:
        from insights.computations import compute_and_store_data_completeness

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("DB error")
            with pytest.raises(RuntimeError, match="DB error"):
                await compute_and_store_data_completeness(mock_client, mock_pool)


class TestLogComputationFailureDuringError:
    """Test that when _log_computation raises, the original exception still propagates."""

    @pytest.mark.asyncio
    async def test_original_exception_propagates_when_log_computation_fails(self) -> None:
        """When _fetch_from_api raises and _log_computation also raises, the original error propagates."""
        from insights.computations import compute_and_store_artist_centrality

        mock_client = AsyncMock()
        # Create a pool where _log_computation will fail (cursor.execute raises)
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock(side_effect=RuntimeError("DB log write failed"))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = AsyncMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API unavailable")
            with pytest.raises(RuntimeError, match="API unavailable"):
                await compute_and_store_artist_centrality(mock_client, mock_pool)

    @pytest.mark.asyncio
    async def test_genre_trends_original_exception_propagates_when_log_fails(self) -> None:
        """Genre trends: original exception propagates even when _log_computation raises."""
        from insights.computations import compute_and_store_genre_trends

        mock_client = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock(side_effect=RuntimeError("DB log write failed"))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = AsyncMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API down")
            with pytest.raises(RuntimeError, match="API down"):
                await compute_and_store_genre_trends(mock_client, mock_pool)

    @pytest.mark.asyncio
    async def test_label_longevity_original_exception_propagates_when_log_fails(self) -> None:
        """Label longevity: original exception propagates even when _log_computation raises."""
        from insights.computations import compute_and_store_label_longevity

        mock_client = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock(side_effect=RuntimeError("DB log write failed"))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = AsyncMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API unreachable")
            with pytest.raises(RuntimeError, match="API unreachable"):
                await compute_and_store_label_longevity(mock_client, mock_pool)

    @pytest.mark.asyncio
    async def test_anniversaries_original_exception_propagates_when_log_fails(self) -> None:
        """Anniversaries: original exception propagates even when _log_computation raises."""
        from insights.computations import compute_and_store_anniversaries

        mock_client = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock(side_effect=RuntimeError("DB log write failed"))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = AsyncMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API timeout")
            with pytest.raises(RuntimeError, match="API timeout"):
                await compute_and_store_anniversaries(mock_client, mock_pool, current_year=2026, current_month=3)

    @pytest.mark.asyncio
    async def test_data_completeness_original_exception_propagates_when_log_fails(self) -> None:
        """Data completeness: original exception propagates even when _log_computation raises."""
        from insights.computations import compute_and_store_data_completeness

        mock_client = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock(side_effect=RuntimeError("DB log write failed"))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = AsyncMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API connection refused")
            with pytest.raises(RuntimeError, match="API connection refused"):
                await compute_and_store_data_completeness(mock_client, mock_pool)

    @pytest.mark.asyncio
    async def test_rarity_original_exception_propagates_when_log_fails(self) -> None:
        """Rarity: original exception propagates even when _log_computation raises."""
        from insights.computations import compute_and_store_rarity

        mock_client = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock(side_effect=RuntimeError("DB log write failed"))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = AsyncMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API server error")
            with pytest.raises(RuntimeError, match="API server error"):
                await compute_and_store_rarity(mock_client, mock_pool)


class TestRunAllComputations:
    @pytest.mark.asyncio
    async def test_runs_all_five(self) -> None:
        from insights.computations import run_all_computations

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with (
            patch("insights.computations.compute_and_store_artist_centrality", return_value=10),
            patch("insights.computations.compute_and_store_genre_trends", return_value=20),
            patch("insights.computations.compute_and_store_label_longevity", return_value=5),
            patch("insights.computations.compute_and_store_anniversaries", return_value=3),
            patch("insights.computations.compute_and_store_data_completeness", return_value=4),
            patch("insights.computations.compute_and_store_community_enrichment", return_value=100),
            patch("insights.computations.compute_and_store_rarity", return_value=7),
        ):
            results = await run_all_computations(mock_client, mock_pool)

        assert results["artist_centrality"] == 10
        assert results["genre_trends"] == 20
        assert results["label_longevity"] == 5
        assert results["anniversaries"] == 3
        assert results["data_completeness"] == 4
        assert results["community_enrichment"] == 100
        assert results["release_rarity"] == 7

    @pytest.mark.asyncio
    async def test_passes_milestone_years_to_anniversaries(self) -> None:
        from insights.computations import run_all_computations

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()
        custom_milestones = [10, 50]

        with (
            patch("insights.computations.compute_and_store_artist_centrality", return_value=0),
            patch("insights.computations.compute_and_store_genre_trends", return_value=0),
            patch("insights.computations.compute_and_store_label_longevity", return_value=0),
            patch("insights.computations.compute_and_store_anniversaries", return_value=0) as mock_anniv,
            patch("insights.computations.compute_and_store_data_completeness", return_value=0),
            patch("insights.computations.compute_and_store_community_enrichment", return_value=0),
            patch("insights.computations.compute_and_store_rarity", return_value=0),
        ):
            await run_all_computations(mock_client, mock_pool, milestone_years=custom_milestones)

        mock_anniv.assert_called_once_with(mock_client, mock_pool, milestone_years=custom_milestones)


class TestEndpointTimeouts:
    """Regression for ReadTimeout failures on the heavy endpoints (discogsography-1cxi)."""

    def test_connect_budget_is_short_so_a_dead_api_fails_fast(self) -> None:
        from insights.computations import endpoint_timeout

        timeout = endpoint_timeout("/api/internal/insights/data-completeness")
        assert timeout.connect is not None
        assert timeout.connect <= 30.0

    def test_default_read_budget_applies_to_unmapped_paths(self) -> None:
        from insights.computations import DEFAULT_READ_TIMEOUT_SECONDS, endpoint_timeout

        assert endpoint_timeout("/api/internal/insights/genre-trends").read == DEFAULT_READ_TIMEOUT_SECONDS
        assert endpoint_timeout().read == DEFAULT_READ_TIMEOUT_SECONDS

    def test_data_completeness_read_budget_clears_the_documented_worst_case(self) -> None:
        """The API documents a ~400s releases seq scan, exceeding 600s on bad days."""
        from insights.computations import endpoint_timeout

        read = endpoint_timeout("/api/internal/insights/data-completeness").read
        assert read is not None
        assert read >= 1200.0

    def test_community_enrichment_budget_covers_the_capped_batch(self) -> None:
        """1 Discogs req/s * MAX_ENRICHMENT_RELEASES must fit inside the read budget."""
        from api.routers.insights_compute import _ENRICHMENT_DELAY_SECONDS, MAX_ENRICHMENT_RELEASES
        from insights.computations import endpoint_timeout

        read = endpoint_timeout("/api/internal/insights/community-enrichment").read
        assert read is not None
        worst_case = MAX_ENRICHMENT_RELEASES * _ENRICHMENT_DELAY_SECONDS
        assert read > worst_case, f"read budget {read}s does not cover worst case {worst_case}s"

    def test_rarity_read_budget_clears_the_neo4j_transaction_timeout(self) -> None:
        """Must outlast the server-side db.transaction.timeout (600s) plus overhead."""
        from insights.computations import endpoint_timeout

        read = endpoint_timeout("/api/internal/insights/rarity-scores").read
        assert read is not None
        assert read >= 1200.0

    def test_every_mapped_endpoint_exceeds_the_default(self) -> None:
        from insights.computations import DEFAULT_READ_TIMEOUT_SECONDS, ENDPOINT_READ_TIMEOUTS

        for path, read in ENDPOINT_READ_TIMEOUTS.items():
            assert read > DEFAULT_READ_TIMEOUT_SECONDS, path

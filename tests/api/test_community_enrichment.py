"""Tests for community have/want enrichment endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestEnrichReleasesFromDiscogs:
    @pytest.mark.asyncio
    async def test_no_releases_to_enrich(self) -> None:
        """When no releases need enrichment, return 0."""
        from api.routers.insights_compute import _enrich_community_counts

        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(return_value=[])
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        result = await _enrich_community_counts(mock_pool, None, None)
        assert result["enriched"] == 0

    @pytest.mark.asyncio
    async def test_no_oauth_credentials(self) -> None:
        """When no OAuth credentials found, skip enrichment."""
        from api.routers.insights_compute import _enrich_community_counts

        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        call_count = 0

        async def mock_fetchall():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"release_id": 123}]
            return []

        mock_cur.fetchall = mock_fetchall
        mock_cur.fetchone = AsyncMock(return_value=None)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        result = await _enrich_community_counts(mock_pool, None, None)
        assert result["enriched"] == 0
        assert result["error"] == "no_credentials"

    @pytest.mark.asyncio
    async def test_successful_enrichment(self) -> None:
        """Successful fetch stores counts in PG and Neo4j."""
        from api.routers.insights_compute import _enrich_community_counts

        mock_pool = MagicMock()
        mock_cur = AsyncMock()

        call_count = 0

        async def mock_fetchall():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"release_id": 123}]
            if call_count == 2:
                return [
                    {"key": "discogs_consumer_key", "value": "ck"},
                    {"key": "discogs_consumer_secret", "value": "cs"},
                ]
            return []

        mock_cur.fetchall = mock_fetchall
        mock_cur.fetchone = AsyncMock(
            return_value={
                "access_token": "at",
                "access_secret": "as",
                "provider_username": "testuser",
            }
        )
        mock_cur.execute = AsyncMock()
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        # Mock Neo4j
        mock_neo4j_result = AsyncMock()
        mock_neo4j_result.consume = AsyncMock()
        mock_neo4j_session = AsyncMock()
        mock_neo4j_session.run = AsyncMock(return_value=mock_neo4j_result)
        mock_neo4j_session.__aenter__ = AsyncMock(return_value=mock_neo4j_session)
        mock_neo4j_session.__aexit__ = AsyncMock(return_value=False)
        mock_neo4j = MagicMock()
        mock_neo4j.session = MagicMock(return_value=mock_neo4j_session)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "community": {"have": 42, "want": 7},
        }

        with (
            patch("api.routers.insights_compute.decrypt_oauth_token", side_effect=lambda v, _k: v),
            patch("api.routers.insights_compute._auth_header", return_value="OAuth ..."),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await _enrich_community_counts(mock_pool, mock_neo4j, None)

        assert result["enriched"] == 1
        assert result["errors"] == 0

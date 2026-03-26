"""Tests for MusicBrainz enrichment API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from api.queries.musicbrainz_queries import (
    get_artist_external_links,
    get_artist_mb_relationships,
    get_artist_musicbrainz,
    get_enrichment_status,
)


# ---------------------------------------------------------------------------
# Helper: build a mock Neo4j driver with preconfigured session results
# ---------------------------------------------------------------------------


def _make_neo4j_driver(data_return: list | None = None) -> MagicMock:
    """Create a mock Neo4j driver whose session.run().data() returns *data_return*."""
    mock_result = AsyncMock()
    mock_result.data = AsyncMock(return_value=data_return if data_return is not None else [])
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    driver = MagicMock()
    driver.session = MagicMock(return_value=mock_session)
    return driver


# ===========================================================================
# Endpoint tests (via TestClient)
# ===========================================================================


class TestArtistMusicbrainzEndpoint:
    """GET /api/artist/{id}/musicbrainz"""

    def test_get_artist_musicbrainz_found(self, test_client: TestClient) -> None:
        mb_data = {
            "discogs_id": 42,
            "mbid": "abc-123",
            "type": "Person",
            "gender": "Male",
            "begin_date": "1970-01-01",
            "end_date": None,
            "area": "United Kingdom",
            "begin_area": "London",
            "disambiguation": "singer",
        }
        with patch("api.routers.musicbrainz.get_artist_musicbrainz", new_callable=AsyncMock, return_value=mb_data):
            resp = test_client.get("/api/artist/42/musicbrainz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["mbid"] == "abc-123"
        assert body["discogs_id"] == 42
        assert body["type"] == "Person"

    def test_get_artist_musicbrainz_not_found(self, test_client: TestClient) -> None:
        with patch("api.routers.musicbrainz.get_artist_musicbrainz", new_callable=AsyncMock, return_value=None):
            resp = test_client.get("/api/artist/999/musicbrainz")
        assert resp.status_code == 404
        assert "No MusicBrainz data" in resp.json()["detail"]

    def test_get_artist_musicbrainz_service_unavailable(self, test_client: TestClient) -> None:
        with patch("api.routers.musicbrainz._neo4j_driver", None):
            resp = test_client.get("/api/artist/1/musicbrainz")
        assert resp.status_code == 503


class TestArtistRelationshipsEndpoint:
    """GET /api/artist/{id}/relationships"""

    def test_get_artist_relationships_found(self, test_client: TestClient) -> None:
        rels = [
            {
                "type": "MEMBER_OF",
                "target_id": 100,
                "target_name": "Some Band",
                "direction": "outgoing",
                "begin_date": "1990",
                "end_date": "2000",
                "attributes": ["vocals"],
            }
        ]
        with patch("api.routers.musicbrainz.get_artist_mb_relationships", new_callable=AsyncMock, return_value=rels):
            resp = test_client.get("/api/artist/42/relationships")
        assert resp.status_code == 200
        body = resp.json()
        assert body["discogs_id"] == 42
        assert len(body["relationships"]) == 1
        assert body["relationships"][0]["type"] == "MEMBER_OF"

    def test_get_artist_relationships_empty(self, test_client: TestClient) -> None:
        with patch("api.routers.musicbrainz.get_artist_mb_relationships", new_callable=AsyncMock, return_value=[]):
            resp = test_client.get("/api/artist/42/relationships")
        assert resp.status_code == 200
        assert resp.json()["relationships"] == []

    def test_get_artist_relationships_service_unavailable(self, test_client: TestClient) -> None:
        with patch("api.routers.musicbrainz._neo4j_driver", None):
            resp = test_client.get("/api/artist/1/relationships")
        assert resp.status_code == 503


class TestExternalLinksEndpoint:
    """GET /api/artist/{id}/external-links"""

    def test_get_external_links_found(self, test_client: TestClient) -> None:
        links = [
            {"service": "wikipedia", "url": "https://en.wikipedia.org/wiki/Artist"},
            {"service": "wikidata", "url": "https://www.wikidata.org/wiki/Q123"},
        ]
        with patch("api.routers.musicbrainz.get_artist_external_links", new_callable=AsyncMock, return_value=links):
            resp = test_client.get("/api/artist/42/external-links")
        assert resp.status_code == 200
        body = resp.json()
        assert body["discogs_id"] == 42
        assert len(body["links"]) == 2
        assert body["links"][0]["service"] == "wikipedia"

    def test_get_external_links_empty(self, test_client: TestClient) -> None:
        with patch("api.routers.musicbrainz.get_artist_external_links", new_callable=AsyncMock, return_value=[]):
            resp = test_client.get("/api/artist/42/external-links")
        assert resp.status_code == 200
        assert resp.json()["links"] == []

    def test_get_external_links_service_unavailable(self, test_client: TestClient) -> None:
        with patch("api.routers.musicbrainz._pool", None):
            resp = test_client.get("/api/artist/1/external-links")
        assert resp.status_code == 503


class TestEnrichmentStatusEndpoint:
    """GET /api/enrichment/status"""

    def test_enrichment_status(self, test_client: TestClient) -> None:
        stats = {
            "musicbrainz": {
                "artists": {"total_mb": 100, "matched_to_discogs": 80, "enriched_in_neo4j": 75},
                "labels": {"total_mb": 50, "matched_to_discogs": 30, "enriched_in_neo4j": 25},
                "releases": {"total_mb": 200, "matched_to_discogs": 150, "enriched_in_neo4j": 140},
                "relationships": {"total_in_mb": 500, "created_in_neo4j": 450},
            }
        }
        with patch("api.routers.musicbrainz.get_enrichment_status", new_callable=AsyncMock, return_value=stats):
            resp = test_client.get("/api/enrichment/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["musicbrainz"]["artists"]["total_mb"] == 100

    def test_enrichment_status_service_unavailable_no_pool(self, test_client: TestClient) -> None:
        with patch("api.routers.musicbrainz._pool", None):
            resp = test_client.get("/api/enrichment/status")
        assert resp.status_code == 503

    def test_enrichment_status_service_unavailable_no_driver(self, test_client: TestClient) -> None:
        with patch("api.routers.musicbrainz._neo4j_driver", None):
            resp = test_client.get("/api/enrichment/status")
        assert resp.status_code == 503


# ===========================================================================
# Query function unit tests
# ===========================================================================


class TestGetArtistMusicbrainzQuery:
    """Unit tests for get_artist_musicbrainz()."""

    @pytest.mark.anyio
    async def test_returns_data(self) -> None:
        row = {
            "mbid": "abc-123",
            "type": "Person",
            "gender": "Male",
            "begin_date": "1970-01-01",
            "end_date": None,
            "area": "UK",
            "begin_area": "London",
            "disambiguation": "",
        }
        driver = _make_neo4j_driver([row])
        result = await get_artist_musicbrainz(driver, 42)
        assert result is not None
        assert result["discogs_id"] == 42
        assert result["mbid"] == "abc-123"

    @pytest.mark.anyio
    async def test_returns_none(self) -> None:
        driver = _make_neo4j_driver([])
        result = await get_artist_musicbrainz(driver, 999)
        assert result is None


class TestGetArtistMbRelationshipsQuery:
    """Unit tests for get_artist_mb_relationships()."""

    @pytest.mark.anyio
    async def test_returns_relationships(self) -> None:
        rels = [
            {
                "type": "MEMBER_OF",
                "target_id": 100,
                "target_name": "Band",
                "direction": "outgoing",
                "begin_date": None,
                "end_date": None,
                "attributes": None,
            }
        ]
        driver = _make_neo4j_driver(rels)
        result = await get_artist_mb_relationships(driver, 42)
        assert len(result) == 1
        assert result[0]["type"] == "MEMBER_OF"

    @pytest.mark.anyio
    async def test_returns_empty(self) -> None:
        driver = _make_neo4j_driver([])
        result = await get_artist_mb_relationships(driver, 42)
        assert result == []


class TestGetArtistExternalLinksQuery:
    """Unit tests for get_artist_external_links()."""

    @pytest.mark.anyio
    async def test_returns_links(self) -> None:
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(return_value=[{"service": "wikipedia", "url": "https://example.com"}])
        mock_cur.execute = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.connection = MagicMock(return_value=conn_ctx)

        result = await get_artist_external_links(pool, 42)
        assert len(result) == 1
        assert result[0]["service"] == "wikipedia"

    @pytest.mark.anyio
    async def test_returns_empty_links(self) -> None:
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(return_value=[])
        mock_cur.execute = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.connection = MagicMock(return_value=conn_ctx)

        result = await get_artist_external_links(pool, 999)
        assert result == []


class TestGetEnrichmentStatusQuery:
    """Unit tests for get_enrichment_status()."""

    @pytest.mark.anyio
    async def test_returns_stats(self) -> None:
        # Mock PostgreSQL pool
        fetchone_values = [
            {"total": 100},  # artists total
            {"matched": 80},  # artists matched
            {"total": 50},  # labels total
            {"matched": 30},  # labels matched
            {"total": 200},  # releases total
            {"matched": 150},  # releases matched
            {"total": 500},  # relationships total
        ]
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(side_effect=fetchone_values)
        mock_cur.execute = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.connection = MagicMock(return_value=conn_ctx)

        # Mock Neo4j driver - needs to return multiple results for the loop
        neo4j_results = [
            [{"count": 75}],  # artists enriched
            [{"count": 25}],  # labels enriched
            [{"count": 140}],  # releases enriched
            [{"count": 450}],  # relationships created
        ]
        mock_session = AsyncMock()
        call_idx = {"n": 0}

        async def mock_run(*_args: object, **_kwargs: object) -> AsyncMock:
            idx = call_idx["n"]
            call_idx["n"] += 1
            result = AsyncMock()
            result.data = AsyncMock(return_value=neo4j_results[idx])
            return result

        mock_session.run = mock_run
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        driver = MagicMock()
        driver.session = MagicMock(return_value=mock_session)

        stats = await get_enrichment_status(pool, driver)
        assert stats["musicbrainz"]["artists"]["total_mb"] == 100
        assert stats["musicbrainz"]["artists"]["matched_to_discogs"] == 80
        assert stats["musicbrainz"]["artists"]["enriched_in_neo4j"] == 75
        assert stats["musicbrainz"]["relationships"]["total_in_mb"] == 500
        assert stats["musicbrainz"]["relationships"]["created_in_neo4j"] == 450


# ===========================================================================
# Configure function test
# ===========================================================================


class TestConfigure:
    """Test configure() sets module-level state."""

    def test_configure_sets_pool_and_driver(self) -> None:
        import api.routers.musicbrainz as mb_router

        mock_pool = MagicMock()
        mock_driver = MagicMock()
        mb_router.configure(mock_pool, mock_driver)
        assert mb_router._pool is mock_pool
        assert mb_router._neo4j_driver is mock_driver

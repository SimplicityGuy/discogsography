"""Unit tests for Label DNA router endpoints."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest


# --- Helpers ---


def _mock_result_iter(records: list[dict[str, Any]]) -> AsyncMock:
    """Create a mock Neo4j result that yields records on async iteration."""
    result = AsyncMock()
    result.__aiter__ = lambda self: self
    records_iter = iter(records)
    result.__anext__ = AsyncMock(side_effect=lambda: next(records_iter, StopAsyncIteration()))

    async def _anext() -> Any:
        try:
            return next(iter([]))  # pragma: no cover
        except StopIteration:
            raise StopAsyncIteration  # noqa: B904

    return result


def _make_mock_session(single_return: dict[str, Any] | None = None, query_returns: list[dict[str, Any]] | None = None) -> AsyncMock:
    """Create a mock session that handles both single and multi-record queries."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    mock_result = AsyncMock()
    if single_return is not None:
        mock_result.single = AsyncMock(return_value=single_return)
    else:
        mock_result.single = AsyncMock(return_value=None)

    if query_returns is not None:
        mock_result.__aiter__ = MagicMock(return_value=iter(query_returns))
    else:
        mock_result.__aiter__ = MagicMock(return_value=iter([]))

    session.run = AsyncMock(return_value=mock_result)
    return session


# --- Tests ---


class TestLabelDnaEndpoint:
    """Tests for GET /api/label/{label_id}/dna."""

    def test_label_not_found(self, test_client: TestClient, mock_neo4j: MagicMock) -> None:
        session = _make_mock_session(single_return=None)
        mock_neo4j.session = MagicMock(return_value=session)
        response = test_client.get("/api/label/99999/dna")
        assert response.status_code == 404

    def test_label_too_few_releases(self, test_client: TestClient, mock_neo4j: MagicMock) -> None:
        # First call returns identity with < 5 releases, second call also returns identity
        identity = {"label_id": "1", "label_name": "Tiny Label", "release_count": 3, "artist_count": 2}
        session = _make_mock_session(single_return=identity)
        mock_neo4j.session = MagicMock(return_value=session)
        response = test_client.get("/api/label/1/dna")
        assert response.status_code == 422
        assert "fewer than" in response.json()["error"]

    @patch("api.routers.label_dna._build_dna")
    def test_label_dna_success(self, mock_build_dna: AsyncMock, test_client: TestClient) -> None:
        from api.models import DecadeCount, FormatWeight, GenreWeight, LabelDNA, StyleWeight

        mock_build_dna.return_value = (
            LabelDNA(
                label_id="123",
                label_name="Blue Note",
                release_count=100,
                artist_count=50,
                artist_diversity=0.5,
                active_years=[1960, 1965, 1970],
                peak_decade=1960,
                prolificacy=33.33,
                genres=[GenreWeight(name="Jazz", count=80, percentage=80.0)],
                styles=[StyleWeight(name="Hard Bop", count=40, percentage=50.0)],
                formats=[FormatWeight(name="Vinyl", count=60, percentage=60.0)],
                decades=[DecadeCount(decade=1960, count=50, percentage=50.0)],
            ),
            "ok",
        )
        response = test_client.get("/api/label/123/dna")
        assert response.status_code == 200
        data = response.json()
        assert data["label_id"] == "123"
        assert data["label_name"] == "Blue Note"
        assert data["release_count"] == 100
        assert len(data["genres"]) == 1
        assert data["genres"][0]["name"] == "Jazz"
        assert data["peak_decade"] == 1960

    def test_service_not_ready(self, test_client: TestClient) -> None:
        import api.routers.label_dna as mod

        original = mod._neo4j_driver
        mod._neo4j_driver = None
        try:
            response = test_client.get("/api/label/1/dna")
            assert response.status_code == 503
        finally:
            mod._neo4j_driver = original


class TestSimilarLabelsEndpoint:
    """Tests for GET /api/label/{label_id}/similar."""

    def test_label_not_found(self, test_client: TestClient, mock_neo4j: MagicMock) -> None:
        session = _make_mock_session(single_return=None)
        mock_neo4j.session = MagicMock(return_value=session)
        response = test_client.get("/api/label/99999/similar")
        assert response.status_code == 404

    @patch("api.routers.label_dna.get_candidate_labels_genre_vectors")
    @patch("api.routers.label_dna.get_label_genre_profile")
    @patch("api.routers.label_dna.get_label_identity")
    def test_similar_success(
        self,
        mock_identity: AsyncMock,
        mock_genres: AsyncMock,
        mock_candidates: AsyncMock,
        test_client: TestClient,
    ) -> None:
        mock_identity.return_value = {"label_id": "1", "label_name": "Blue Note", "release_count": 100, "artist_count": 50}
        mock_genres.return_value = [{"name": "Jazz", "count": 80}, {"name": "Rock", "count": 20}]
        mock_candidates.return_value = [
            {
                "label_id": "2",
                "label_name": "Prestige",
                "release_count": 80,
                "genres": [{"name": "Jazz", "count": 70}, {"name": "Blues", "count": 10}],
            },
        ]
        response = test_client.get("/api/label/1/similar?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert data["label_id"] == "1"
        assert len(data["similar"]) == 1
        assert data["similar"][0]["label_name"] == "Prestige"
        assert data["similar"][0]["similarity"] > 0

    @patch("api.routers.label_dna.get_label_identity")
    def test_too_few_releases(self, mock_identity: AsyncMock, test_client: TestClient) -> None:
        mock_identity.return_value = {"label_id": "1", "label_name": "Tiny", "release_count": 2, "artist_count": 1}
        response = test_client.get("/api/label/1/similar")
        assert response.status_code == 422


class TestCompareLabelsEndpoint:
    """Tests for GET /api/label/dna/compare."""

    def test_too_few_ids(self, test_client: TestClient) -> None:
        response = test_client.get("/api/label/dna/compare?ids=1")
        assert response.status_code == 400
        assert "At least 2" in response.json()["error"]

    def test_too_many_ids(self, test_client: TestClient) -> None:
        response = test_client.get("/api/label/dna/compare?ids=1,2,3,4,5,6")
        assert response.status_code == 400
        assert "At most 5" in response.json()["error"]

    @patch("api.routers.label_dna._build_dna")
    def test_compare_success(self, mock_build_dna: AsyncMock, test_client: TestClient) -> None:
        from api.models import DecadeCount, FormatWeight, GenreWeight, LabelDNA, StyleWeight

        dna1 = LabelDNA(
            label_id="1",
            label_name="Label A",
            release_count=50,
            artist_count=25,
            artist_diversity=0.5,
            active_years=[1990, 2000],
            peak_decade=1990,
            prolificacy=25.0,
            genres=[GenreWeight(name="Rock", count=40, percentage=80.0)],
            styles=[StyleWeight(name="Punk", count=20, percentage=40.0)],
            formats=[FormatWeight(name="Vinyl", count=30, percentage=60.0)],
            decades=[DecadeCount(decade=1990, count=30, percentage=60.0)],
        )
        dna2 = LabelDNA(
            label_id="2",
            label_name="Label B",
            release_count=30,
            artist_count=15,
            artist_diversity=0.5,
            active_years=[2000, 2010],
            peak_decade=2000,
            prolificacy=15.0,
            genres=[GenreWeight(name="Jazz", count=25, percentage=83.3)],
            styles=[StyleWeight(name="Fusion", count=10, percentage=33.3)],
            formats=[FormatWeight(name="CD", count=20, percentage=66.7)],
            decades=[DecadeCount(decade=2000, count=20, percentage=66.7)],
        )
        mock_build_dna.side_effect = [(dna1, "ok"), (dna2, "ok")]
        response = test_client.get("/api/label/dna/compare?ids=1,2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["labels"]) == 2
        assert data["labels"][0]["dna"]["label_id"] == "1"
        assert data["labels"][1]["dna"]["label_id"] == "2"

    @patch("api.routers.label_dna._build_dna")
    def test_compare_label_not_found(self, mock_build_dna: AsyncMock, test_client: TestClient) -> None:
        mock_build_dna.side_effect = [(None, "not_found"), (None, "not_found")]
        response = test_client.get("/api/label/dna/compare?ids=1,2")
        assert response.status_code == 404


class TestAddPercentages:
    """Tests for _add_percentages helper."""

    def test_zero_total_returns_zero_percentage(self) -> None:
        """Line 49: total=0 branch returns 0.0 percentage."""
        from api.routers.label_dna import _add_percentages

        items = [{"name": "Rock", "count": 10}]
        result = _add_percentages(items, 0)
        assert result[0]["percentage"] == 0.0

    def test_nonzero_total_computes_percentage(self) -> None:
        from api.routers.label_dna import _add_percentages

        items = [{"name": "Rock", "count": 50}, {"name": "Jazz", "count": 50}]
        result = _add_percentages(items, 100)
        assert result[0]["percentage"] == 50.0
        assert result[1]["percentage"] == 50.0


class TestBuildDnaInternal:
    """Tests for _build_dna internal helper (lines 64-91)."""

    @patch("api.routers.label_dna.get_label_format_profile")
    @patch("api.routers.label_dna.get_label_active_years")
    @patch("api.routers.label_dna.get_label_full_profile")
    def test_build_dna_success(
        self,
        mock_full_profile: AsyncMock,
        mock_active_years: AsyncMock,
        mock_formats: AsyncMock,
        test_client: TestClient,
    ) -> None:
        """_build_dna full success path via /api/label/{id}/dna."""
        mock_full_profile.return_value = {
            "label_id": "42",
            "label_name": "ECM Records",
            "release_count": 200,
            "artist_count": 80,
            "genres": [{"name": "Jazz", "count": 150}, {"name": "Classical", "count": 50}],
            "styles": [{"name": "Avant-garde", "count": 100}],
            "decades": [{"decade": 1970, "count": 80}, {"decade": 1980, "count": 120}],
        }
        mock_active_years.return_value = [1970, 1975, 1980, 1985, 1990]
        mock_formats.return_value = [{"name": "Vinyl", "count": 100}, {"name": "CD", "count": 100}]

        response = test_client.get("/api/label/42/dna")
        assert response.status_code == 200
        data = response.json()
        assert data["label_id"] == "42"
        assert data["label_name"] == "ECM Records"
        assert data["release_count"] == 200
        assert data["peak_decade"] == 1980
        assert len(data["genres"]) == 2
        assert data["genres"][0]["name"] == "Jazz"
        assert data["genres"][0]["percentage"] == 75.0
        assert data["prolificacy"] == round(200 / 5, 2)
        # artist_diversity = min(80/200, 1.0) = 0.4
        assert data["artist_diversity"] == 0.4

    @patch("api.routers.label_dna.get_label_format_profile")
    @patch("api.routers.label_dna.get_label_active_years")
    @patch("api.routers.label_dna.get_label_full_profile")
    def test_build_dna_no_decades_peak_none(
        self,
        mock_full_profile: AsyncMock,
        mock_active_years: AsyncMock,
        mock_formats: AsyncMock,
        test_client: TestClient,
    ) -> None:
        """peak_decade is None when decades list is empty."""
        mock_full_profile.return_value = {
            "label_id": "99",
            "label_name": "Empty Label",
            "release_count": 10,
            "artist_count": 5,
            "genres": [],
            "styles": [],
            "decades": [],
        }
        mock_active_years.return_value = []
        mock_formats.return_value = []

        response = test_client.get("/api/label/99/dna")
        assert response.status_code == 200
        data = response.json()
        assert data["peak_decade"] is None
        # prolificacy: num_active_years=0 → 0.0
        assert data["prolificacy"] == 0.0


class TestGetLabelFullProfile:
    """Tests for get_label_full_profile query function."""

    @pytest.mark.asyncio
    @patch("api.queries.label_dna_queries.get_label_decade_profile")
    @patch("api.queries.label_dna_queries.get_label_style_profile")
    @patch("api.queries.label_dna_queries.get_label_genre_profile")
    @patch("api.queries.label_dna_queries.get_label_identity")
    async def test_full_profile_with_sufficient_releases(
        self,
        mock_identity: AsyncMock,
        mock_genres: AsyncMock,
        mock_styles: AsyncMock,
        mock_decades: AsyncMock,
    ) -> None:
        """Labels with >= MIN_RELEASES run parallel genre/style/decade queries."""
        from api.queries.label_dna_queries import get_label_full_profile

        mock_identity.return_value = {
            "label_id": "42",
            "label_name": "ECM Records",
            "release_count": 200,
            "artist_count": 80,
        }
        mock_genres.return_value = [{"name": "Jazz", "count": 150}]
        mock_styles.return_value = [{"name": "Avant-garde", "count": 100}]
        mock_decades.return_value = [{"decade": 1970, "count": 80}]

        result = await get_label_full_profile(AsyncMock(), "42")
        assert result is not None
        assert result["release_count"] == 200
        assert result["genres"] == [{"name": "Jazz", "count": 150}]
        assert result["styles"] == [{"name": "Avant-garde", "count": 100}]
        assert result["decades"] == [{"decade": 1970, "count": 80}]
        mock_genres.assert_called_once()
        mock_styles.assert_called_once()
        mock_decades.assert_called_once()

    @pytest.mark.asyncio
    @patch("api.queries.label_dna_queries.get_label_genre_profile")
    @patch("api.queries.label_dna_queries.get_label_identity")
    async def test_full_profile_below_min_releases_skips_profiles(
        self,
        mock_identity: AsyncMock,
        mock_genres: AsyncMock,
    ) -> None:
        """Labels below MIN_RELEASES return early without profile queries."""
        from api.queries.label_dna_queries import get_label_full_profile

        mock_identity.return_value = {
            "label_id": "1",
            "label_name": "Tiny Label",
            "release_count": 3,
            "artist_count": 1,
        }

        result = await get_label_full_profile(AsyncMock(), "1")
        assert result is not None
        assert result["release_count"] == 3
        assert result["genres"] == []
        mock_genres.assert_not_called()


class TestSimilarLabelsEndpointNotReady:
    """Tests for GET /api/label/{label_id}/similar — 503 when not ready."""

    def test_service_not_ready(self, test_client: TestClient) -> None:
        """Line 138: similar_labels returns 503 when _neo4j_driver is None."""
        import api.routers.label_dna as mod

        original = mod._neo4j_driver
        mod._neo4j_driver = None
        try:
            response = test_client.get("/api/label/1/similar")
            assert response.status_code == 503
        finally:
            mod._neo4j_driver = original


class TestCompareLabelsEndpointExtras:
    """Additional tests for GET /api/label/dna/compare."""

    def test_service_not_ready(self, test_client: TestClient) -> None:
        """Line 173: compare_labels returns 503 when _neo4j_driver is None."""
        import api.routers.label_dna as mod

        original = mod._neo4j_driver
        mod._neo4j_driver = None
        try:
            response = test_client.get("/api/label/dna/compare?ids=1,2")
            assert response.status_code == 503
        finally:
            mod._neo4j_driver = original

    @patch("api.routers.label_dna._build_dna")
    def test_compare_label_too_few_releases(self, mock_build_dna: AsyncMock, test_client: TestClient) -> None:
        """Line 188: compare_labels returns 422 when a label has too few releases."""
        mock_build_dna.side_effect = [(None, "too_few"), (None, "too_few")]
        response = test_client.get("/api/label/dna/compare?ids=1,2")
        assert response.status_code == 422
        assert "fewer than" in response.json()["error"]


class TestLabelDnaModels:
    """Tests for Label DNA Pydantic models."""

    def test_label_dna_model(self) -> None:
        from api.models import DecadeCount, FormatWeight, GenreWeight, LabelDNA, StyleWeight

        dna = LabelDNA(
            label_id="123",
            label_name="Test Label",
            release_count=100,
            artist_count=50,
            artist_diversity=0.5,
            active_years=[1990, 2000],
            peak_decade=1990,
            prolificacy=50.0,
            genres=[GenreWeight(name="Rock", count=80, percentage=80.0)],
            styles=[StyleWeight(name="Punk", count=40, percentage=50.0)],
            formats=[FormatWeight(name="Vinyl", count=60, percentage=60.0)],
            decades=[DecadeCount(decade=1990, count=50, percentage=50.0)],
        )
        dumped = dna.model_dump()
        assert dumped["label_id"] == "123"
        assert dumped["artist_diversity"] == 0.5
        assert len(dumped["genres"]) == 1

    def test_similar_label_model(self) -> None:
        from api.models import SimilarLabel

        sl = SimilarLabel(
            label_id="1",
            label_name="Test",
            similarity=0.95,
            release_count=50,
            shared_genres=["Rock", "Jazz"],
        )
        assert sl.similarity == 0.95
        assert len(sl.shared_genres) == 2

    def test_compare_response_model(self) -> None:
        from api.models import (
            DecadeCount,
            GenreWeight,
            LabelCompareEntry,
            LabelCompareResponse,
            LabelDNA,
        )

        dna = LabelDNA(
            label_id="1",
            label_name="L",
            release_count=10,
            artist_count=5,
            artist_diversity=0.5,
            active_years=[2000],
            peak_decade=2000,
            prolificacy=10.0,
            genres=[GenreWeight(name="Rock", count=10, percentage=100.0)],
            styles=[],
            formats=[],
            decades=[DecadeCount(decade=2000, count=10, percentage=100.0)],
        )
        resp = LabelCompareResponse(labels=[LabelCompareEntry(dna=dna)])
        assert len(resp.labels) == 1


class TestLabelDnaCaching:
    """Tests for Redis caching on label DNA and similar endpoints."""

    def test_dna_cache_hit(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """Cached DNA response should be returned without querying Neo4j."""
        cached = {"label_id": "157", "label_name": "Hooj Choons", "release_count": 100}
        mock_redis.get = AsyncMock(return_value=json.dumps(cached))

        response = test_client.get("/api/label/157/dna")
        assert response.status_code == 200
        assert response.json() == cached

    def test_dna_cache_miss_stores_result(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """On cache miss, DNA result should be computed and stored in Redis."""
        from api.models import LabelDNA

        mock_redis.get = AsyncMock(return_value=None)
        fake_dna = LabelDNA(
            label_id="157",
            label_name="Hooj",
            release_count=100,
            artist_count=50,
            artist_diversity=0.5,
            active_years=[2000],
            peak_decade=2000,
            prolificacy=100.0,
            genres=[],
            styles=[],
            formats=[],
            decades=[],
        )
        with patch("api.routers.label_dna._build_dna", return_value=(fake_dna, "ok")):
            response = test_client.get("/api/label/157/dna")

        assert response.status_code == 200
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == "label-dna:157"

    def test_dna_cache_get_failure_falls_through(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """Redis get failure should fall through to Neo4j query."""
        mock_redis.get = AsyncMock(side_effect=Exception("connection lost"))
        with patch("api.routers.label_dna._build_dna", return_value=(None, "not_found")):
            response = test_client.get("/api/label/999/dna")
        assert response.status_code == 404

    def test_dna_cache_set_failure_still_returns(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """Redis set failure should not prevent DNA response."""
        from api.models import LabelDNA

        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock(side_effect=Exception("connection lost"))
        fake_dna = LabelDNA(
            label_id="157",
            label_name="Hooj",
            release_count=100,
            artist_count=50,
            artist_diversity=0.5,
            active_years=[2000],
            peak_decade=2000,
            prolificacy=100.0,
            genres=[],
            styles=[],
            formats=[],
            decades=[],
        )
        with patch("api.routers.label_dna._build_dna", return_value=(fake_dna, "ok")):
            response = test_client.get("/api/label/157/dna")
        assert response.status_code == 200

    def test_similar_cache_get_failure_falls_through(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """Redis get failure on similar should fall through to Neo4j query."""
        mock_redis.get = AsyncMock(side_effect=Exception("connection lost"))

        with (
            patch(
                "api.routers.label_dna.get_label_identity",
                return_value={"label_id": "157", "label_name": "Hooj", "release_count": 100, "artist_count": 50},
            ),
            patch("api.routers.label_dna.get_label_genre_profile", return_value=[]),
            patch("api.routers.label_dna.get_candidate_labels_genre_vectors", return_value=[]),
        ):
            response = test_client.get("/api/label/157/similar")
        assert response.status_code == 200

    def test_similar_cache_hit(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """Cached similar-labels response should be returned without computing."""
        cached = {"label_id": "157", "label_name": "Hooj Choons", "similar": []}
        mock_redis.get = AsyncMock(return_value=json.dumps(cached))

        response = test_client.get("/api/label/157/similar")
        assert response.status_code == 200
        assert response.json() == cached

    def test_similar_cache_miss_stores_result(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """On cache miss, similar result should be stored in Redis."""
        mock_redis.get = AsyncMock(return_value=None)

        with (
            patch(
                "api.routers.label_dna.get_label_identity",
                return_value={"label_id": "157", "label_name": "Hooj", "release_count": 100, "artist_count": 50},
            ),
            patch("api.routers.label_dna.get_label_genre_profile", return_value=[]),
            patch("api.routers.label_dna.get_candidate_labels_genre_vectors", return_value=[]),
        ):
            response = test_client.get("/api/label/157/similar")

        assert response.status_code == 200
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == "label-similar:157:10"

    def test_similar_cache_set_failure_still_returns(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """Redis set failure should not prevent response."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock(side_effect=Exception("connection lost"))

        with (
            patch(
                "api.routers.label_dna.get_label_identity",
                return_value={"label_id": "157", "label_name": "Hooj", "release_count": 100, "artist_count": 50},
            ),
            patch("api.routers.label_dna.get_label_genre_profile", return_value=[]),
            patch("api.routers.label_dna.get_candidate_labels_genre_vectors", return_value=[]),
        ):
            response = test_client.get("/api/label/157/similar")

        assert response.status_code == 200

"""Unit tests for Label DNA router endpoints."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


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

        async def _session(*_a: Any, **_k: Any) -> Any:
            return session

        mock_neo4j.session = MagicMock(side_effect=_session)
        response = test_client.get("/api/label/99999/dna")
        assert response.status_code == 404

    def test_label_too_few_releases(self, test_client: TestClient, mock_neo4j: MagicMock) -> None:
        # First call returns identity with < 5 releases, second call also returns identity
        identity = {"label_id": "1", "label_name": "Tiny Label", "release_count": 3, "artist_count": 2}
        session = _make_mock_session(single_return=identity)

        async def _session_factory(*_a: Any, **_k: Any) -> Any:
            return session

        mock_neo4j.session = MagicMock(side_effect=_session_factory)
        response = test_client.get("/api/label/1/dna")
        assert response.status_code == 422
        assert "fewer than" in response.json()["error"]

    @patch("api.routers.label_dna._build_dna")
    def test_label_dna_success(self, mock_build_dna: AsyncMock, test_client: TestClient) -> None:
        from api.models import DecadeCount, FormatWeight, GenreWeight, LabelDNA, StyleWeight

        mock_build_dna.return_value = LabelDNA(
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

        async def _session(*_a: Any, **_k: Any) -> Any:
            return session

        mock_neo4j.session = MagicMock(side_effect=_session)
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
                "genres": [{"genre": "Jazz", "count": 70}, {"genre": "Blues", "count": 10}],
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
        mock_build_dna.side_effect = [dna1, dna2]
        response = test_client.get("/api/label/dna/compare?ids=1,2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["labels"]) == 2
        assert data["labels"][0]["dna"]["label_id"] == "1"
        assert data["labels"][1]["dna"]["label_id"] == "2"

    @patch("api.routers.label_dna._build_dna")
    @patch("api.routers.label_dna.get_label_identity")
    def test_compare_label_not_found(self, mock_identity: AsyncMock, mock_build_dna: AsyncMock, test_client: TestClient) -> None:
        mock_build_dna.side_effect = [None, None]
        mock_identity.return_value = None
        response = test_client.get("/api/label/dna/compare?ids=1,2")
        assert response.status_code == 404


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

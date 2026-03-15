"""Unit tests for recommend router endpoints."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class TestSimilarArtistsEndpoint:
    """Tests for GET /api/recommend/similar/artist/{artist_id}."""

    def test_service_not_ready(self, test_client: TestClient) -> None:
        import api.routers.recommend as mod

        original = mod._neo4j_driver
        mod._neo4j_driver = None
        try:
            response = test_client.get("/api/recommend/similar/artist/a1")
            assert response.status_code == 503
        finally:
            mod._neo4j_driver = original

    @patch("api.routers.recommend.get_artist_identity")
    def test_artist_not_found(self, mock_identity: AsyncMock, test_client: TestClient) -> None:
        mock_identity.return_value = None
        response = test_client.get("/api/recommend/similar/artist/a99999")
        assert response.status_code == 404

    @patch("api.routers.recommend.get_artist_identity")
    def test_too_few_releases(self, mock_identity: AsyncMock, test_client: TestClient) -> None:
        mock_identity.return_value = {
            "artist_id": "a1",
            "artist_name": "Tiny Artist",
            "release_count": 2,
        }
        response = test_client.get("/api/recommend/similar/artist/a1")
        assert response.status_code == 422
        assert "fewer than" in response.json()["error"]

    @patch("api.routers.recommend.get_candidate_artists")
    @patch("api.routers.recommend.get_artist_profile")
    @patch("api.routers.recommend.get_artist_identity")
    def test_success(
        self,
        mock_identity: AsyncMock,
        mock_profile: AsyncMock,
        mock_candidates: AsyncMock,
        test_client: TestClient,
    ) -> None:
        mock_identity.return_value = {
            "artist_id": "a1",
            "artist_name": "Test Artist",
            "release_count": 20,
        }
        mock_profile.return_value = {
            "genres": [{"name": "Rock", "count": 80}],
            "styles": [{"name": "Punk", "count": 40}],
            "labels": [{"name": "Sub Pop", "count": 10}],
            "collaborators": [],
        }
        mock_candidates.return_value = [
            {
                "artist_id": "a2",
                "artist_name": "Similar Artist",
                "release_count": 15,
                "genres": [{"name": "Rock", "count": 60}],
                "styles": [{"name": "Punk", "count": 30}],
                "labels": [{"name": "Sub Pop", "count": 8}],
                "collaborators": [],
            },
        ]
        response = test_client.get("/api/recommend/similar/artist/a1?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert data["artist_id"] == "a1"
        assert len(data["similar"]) == 1
        assert data["similar"][0]["artist_name"] == "Similar Artist"
        assert "breakdown" in data["similar"][0]
        assert data["similar"][0]["similarity"] > 0

    @patch("api.routers.recommend.get_candidate_artists")
    @patch("api.routers.recommend.get_artist_profile")
    @patch("api.routers.recommend.get_artist_identity")
    def test_no_similar_artists(
        self,
        mock_identity: AsyncMock,
        mock_profile: AsyncMock,
        mock_candidates: AsyncMock,
        test_client: TestClient,
    ) -> None:
        mock_identity.return_value = {
            "artist_id": "a1",
            "artist_name": "Unique",
            "release_count": 10,
        }
        mock_profile.return_value = {
            "genres": [{"name": "Experimental", "count": 10}],
            "styles": [],
            "labels": [],
            "collaborators": [],
        }
        mock_candidates.return_value = []
        response = test_client.get("/api/recommend/similar/artist/a1")
        assert response.status_code == 200
        assert response.json()["similar"] == []


class TestExploreFromHereEndpoint:
    """Tests for GET /api/recommend/explore/{entity_type}/{entity_id}."""

    def test_requires_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/recommend/explore/artist/a1")
        assert response.status_code in (401, 403)

    def test_invalid_entity_type(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        response = test_client.get("/api/recommend/explore/release/r1", headers=auth_headers)
        assert response.status_code == 400
        assert "Invalid entity_type" in response.json()["error"]

    @patch("api.routers.recommend.get_blind_spots")
    @patch("api.routers.recommend.get_taste_heatmap")
    @patch("api.routers.recommend.get_explore_traversal")
    def test_success(
        self,
        mock_traversal: AsyncMock,
        mock_heatmap: AsyncMock,
        mock_blindspots: AsyncMock,
        test_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        mock_traversal.return_value = [
            {
                "id": "l1",
                "name": "Warp Records",
                "type": "label",
                "path_names": ["Aphex Twin", "SAW", "Warp Records"],
                "rel_types": ["BY", "ON"],
                "dist": 2,
            },
        ]
        mock_heatmap.return_value = (
            [{"genre": "Electronic", "decade": 1990, "count": 10}],
            10,
        )
        mock_blindspots.return_value = []

        response = test_client.get(
            "/api/recommend/explore/artist/a1?hops=2&limit=5",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "from" in data
        assert data["from"]["type"] == "artist"
        assert len(data["discoveries"]) == 1
        assert data["discoveries"][0]["name"] == "Warp Records"

    @patch("api.routers.recommend.get_blind_spots")
    @patch("api.routers.recommend.get_taste_heatmap")
    @patch("api.routers.recommend.get_explore_traversal")
    def test_empty_traversal(
        self,
        mock_traversal: AsyncMock,
        mock_heatmap: AsyncMock,
        mock_blindspots: AsyncMock,
        test_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        mock_traversal.return_value = []
        mock_heatmap.return_value = ([], 0)
        mock_blindspots.return_value = []

        response = test_client.get(
            "/api/recommend/explore/genre/Rock",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["discoveries"] == []


class TestRecommenderModels:
    """Tests for recommender Pydantic models."""

    def test_similar_artist_model(self) -> None:
        from api.models import SimilarArtist

        sa = SimilarArtist(
            artist_id="a1",
            artist_name="Test",
            similarity=0.85,
            breakdown={"genre": 0.9, "style": 0.8, "label": 0.7, "collaborator": 0.5},
            release_count=20,
            shared_genres=["Rock"],
            shared_labels=["Sub Pop"],
        )
        assert sa.similarity == 0.85
        assert sa.breakdown["genre"] == 0.9

    def test_explore_response_from_alias(self) -> None:
        from api.models import DiscoveryNode, EntityRef, ExploreFromHereResponse

        resp = ExploreFromHereResponse(
            from_entity=EntityRef(id="a1", name="Artist", type="artist"),
            discoveries=[
                DiscoveryNode(
                    id="l1",
                    name="Label",
                    type="label",
                    score=0.7,
                    path=["Artist", "\u2014BY\u2192", "Release", "\u2014ON\u2192", "Label"],
                    reason="graph_proximity",
                )
            ],
        )
        dumped = resp.model_dump(by_alias=True)
        assert "from" in dumped
        assert dumped["from"]["id"] == "a1"
        assert len(dumped["discoveries"]) == 1

    def test_enhanced_recommendation_model(self) -> None:
        from api.models import EnhancedRecommendation, EnhancedRecommendationsResponse

        resp = EnhancedRecommendationsResponse(
            recommendations=[
                EnhancedRecommendation(
                    id="r1",
                    title="Test Album",
                    artist="Test Artist",
                    label="Test Label",
                    year=2000,
                    genres=["Rock"],
                    score=0.87,
                    reasons=["artist: top artist", "label: top label"],
                )
            ],
            total=1,
            strategy="multi",
        )
        assert resp.total == 1
        assert resp.strategy == "multi"
        assert resp.recommendations[0].score == 0.87

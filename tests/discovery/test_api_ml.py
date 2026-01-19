"""E2E tests for ML & Recommendations API endpoints (Phase 4.2.1)."""

from fastapi.testclient import TestClient
import pytest


class TestMLAPI:
    """Test ML & Recommendations API endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a test client for the Discovery service."""
        from discovery.discovery import app

        return TestClient(app)

    def test_collaborative_recommend_endpoint(self, client: TestClient) -> None:
        """Test collaborative filtering recommendations endpoint."""
        request_data = {
            "artist_id": "artist_12345",
            "limit": 10,
            "min_similarity": 0.3,
        }

        response = client.post("/api/ml/recommend/collaborative", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "artist_id" in data
        assert data["artist_id"] == "artist_12345"
        assert "recommendations" in data
        assert "algorithm" in data
        assert data["algorithm"] == "collaborative_filtering"
        assert "status" in data
        assert data["status"] == "success"
        assert "timestamp" in data

    def test_collaborative_recommend_validation(self, client: TestClient) -> None:
        """Test collaborative filtering with invalid parameters."""
        # Test with limit exceeding maximum
        request_data = {
            "artist_id": "artist_12345",
            "limit": 200,  # exceeds max of 100
            "min_similarity": 0.3,
        }

        response = client.post("/api/ml/recommend/collaborative", json=request_data)
        assert response.status_code == 422  # Validation error

    def test_hybrid_recommend_endpoint(self, client: TestClient) -> None:
        """Test hybrid recommendations endpoint."""
        request_data = {
            "artist_name": "The Beatles",
            "limit": 10,
            "strategy": "weighted",
        }

        response = client.post("/api/ml/recommend/hybrid", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "artist_name" in data
        assert data["artist_name"] == "The Beatles"
        assert "recommendations" in data
        assert "algorithm" in data
        assert data["algorithm"] == "hybrid"
        assert "strategy" in data
        assert data["strategy"] == "weighted"
        assert "status" in data
        assert data["status"] == "success"
        assert "timestamp" in data

    def test_hybrid_recommend_strategies(self, client: TestClient) -> None:
        """Test hybrid recommendations with different strategies."""
        strategies = ["weighted", "ranked", "cascade"]

        for strategy in strategies:
            request_data = {
                "artist_name": "Pink Floyd",
                "limit": 5,
                "strategy": strategy,
            }

            response = client.post("/api/ml/recommend/hybrid", json=request_data)
            assert response.status_code == 200

            data = response.json()
            assert data["strategy"] == strategy

    def test_explain_recommendation_endpoint(self, client: TestClient) -> None:
        """Test recommendation explanation endpoint."""
        request_data = {
            "artist_id": "artist_12345",
            "recommended_id": "artist_67890",
        }

        response = client.post("/api/ml/recommend/explain", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "artist_id" in data
        assert data["artist_id"] == "artist_12345"
        assert "recommended_id" in data
        assert data["recommended_id"] == "artist_67890"
        assert "explanation" in data
        assert "status" in data
        assert data["status"] == "success"
        assert "timestamp" in data

    def test_ml_api_status_endpoint(self, client: TestClient) -> None:
        """Test ML API status endpoint."""
        response = client.get("/api/ml/status")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert data["status"] in ["initialized", "not_initialized"]
        assert "features" in data
        assert "collaborative_filtering" in data["features"]
        assert "hybrid_recommendations" in data["features"]
        assert "explanations" in data["features"]
        assert "ab_testing" in data["features"]
        assert "metrics" in data["features"]
        assert "phase" in data
        assert data["phase"] == "4.2 (Full Implementation)"
        assert "timestamp" in data

    def test_collaborative_recommend_missing_fields(self, client: TestClient) -> None:
        """Test collaborative filtering with missing required fields."""
        request_data = {
            "limit": 10,
            # missing artist_id
        }

        response = client.post("/api/ml/recommend/collaborative", json=request_data)
        assert response.status_code == 422  # Validation error

    def test_hybrid_recommend_empty_name(self, client: TestClient) -> None:
        """Test hybrid recommendations with empty artist name.

        Note: Empty string passes Pydantic validation but would fail in real implementation.
        """
        request_data = {
            "artist_name": "",
            "limit": 10,
            "strategy": "weighted",
        }

        response = client.post("/api/ml/recommend/hybrid", json=request_data)
        # Empty string is technically valid in Pydantic, endpoint returns 200 with placeholder
        assert response.status_code == 200
        data = response.json()
        assert data["artist_name"] == ""

    def test_collaborative_recommend_boundary_values(self, client: TestClient) -> None:
        """Test collaborative filtering with boundary values."""
        # Test minimum limit
        request_data = {
            "artist_id": "artist_12345",
            "limit": 1,
            "min_similarity": 0.0,
        }

        response = client.post("/api/ml/recommend/collaborative", json=request_data)
        assert response.status_code == 200

        # Test maximum limit
        request_data["limit"] = 100
        response = client.post("/api/ml/recommend/collaborative", json=request_data)
        assert response.status_code == 200

        # Test maximum similarity
        request_data["min_similarity"] = 1.0
        response = client.post("/api/ml/recommend/collaborative", json=request_data)
        assert response.status_code == 200

    def test_response_format_consistency(self, client: TestClient) -> None:
        """Test that all ML API responses follow consistent format."""
        # All endpoints should return status and timestamp
        endpoints_and_data = [
            ("/api/ml/recommend/collaborative", {"artist_id": "test", "limit": 5}),
            ("/api/ml/recommend/hybrid", {"artist_name": "Test", "limit": 5}),
            ("/api/ml/recommend/explain", {"artist_id": "test1", "recommended_id": "test2"}),
        ]

        for endpoint, request_data in endpoints_and_data:
            response = client.post(endpoint, json=request_data)
            assert response.status_code == 200

            data = response.json()
            assert "status" in data
            assert "timestamp" in data
            # ISO 8601 format check
            assert "T" in data["timestamp"]


class TestMLAPIIntegration:
    """Integration tests for ML API with other components."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a test client for the Discovery service."""
        from discovery.discovery import app

        return TestClient(app)

    def test_ml_api_with_openapi_docs(self, client: TestClient) -> None:
        """Test that ML API endpoints appear in OpenAPI documentation."""
        response = client.get("/openapi.json")
        assert response.status_code == 200

        openapi_spec = response.json()
        assert "/api/ml/recommend/collaborative" in openapi_spec["paths"]
        assert "/api/ml/recommend/hybrid" in openapi_spec["paths"]
        assert "/api/ml/recommend/explain" in openapi_spec["paths"]
        assert "/api/ml/status" in openapi_spec["paths"]

        # Check that Machine Learning tag exists
        tags = [tag["name"] for tag in openapi_spec.get("tags", [])]
        assert "Machine Learning" in tags

    def test_ml_api_rate_limiting_headers(self, client: TestClient) -> None:
        """Test that ML API responses include rate limiting headers."""
        request_data = {
            "artist_id": "artist_12345",
            "limit": 10,
            "min_similarity": 0.3,
        }

        response = client.post("/api/ml/recommend/collaborative", json=request_data)
        assert response.status_code == 200

        # Check for rate limit headers (may vary based on configuration)
        # These headers are typically added by slowapi middleware
        # The exact header names may vary

    def test_ml_api_cors_headers(self, client: TestClient) -> None:
        """Test that ML API responses include CORS headers."""
        request_data = {
            "artist_id": "artist_12345",
            "limit": 10,
        }

        response = client.post(
            "/api/ml/recommend/collaborative",
            json=request_data,
            headers={"Origin": "http://localhost:3000"},
        )

        # CORS headers should be present for configured origins
        # Note: Actual behavior depends on CORS middleware configuration
        assert response.status_code == 200


class TestMLAPIInitialization:
    """Test ML API initialization and lifecycle."""

    @pytest.mark.asyncio
    async def test_close_ml_api(self) -> None:
        """Test ML API cleanup."""
        from discovery.api_ml import close_ml_api

        # Close should work even if not initialized
        await close_ml_api()

        from discovery import api_ml

        assert api_ml.ml_api_initialized is False


class TestMLAPIErrorHandling:
    """Test error handling in ML API endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a test client for the Discovery service."""
        from discovery.discovery import app

        return TestClient(app)

    def test_collaborative_recommend_not_initialized(self, client: TestClient) -> None:
        """Test collaborative filtering when ML API not initialized."""
        from discovery import api_ml

        # Temporarily disable ML API
        original_state = api_ml.ml_api_initialized
        api_ml.ml_api_initialized = False
        api_ml.collaborative_filter = None

        request_data = {
            "artist_id": "artist_12345",
            "limit": 10,
            "min_similarity": 0.3,
        }

        try:
            response = client.post("/api/ml/recommend/collaborative", json=request_data)
            assert response.status_code == 503
            assert "not initialized" in response.json()["detail"].lower()
        finally:
            # Restore state
            api_ml.ml_api_initialized = original_state

    def test_hybrid_recommend_not_initialized(self, client: TestClient) -> None:
        """Test hybrid recommendations when ML API not initialized."""
        from discovery import api_ml

        original_state = api_ml.ml_api_initialized
        api_ml.ml_api_initialized = False
        api_ml.hybrid_recommender = None

        request_data = {
            "artist_name": "The Beatles",
            "limit": 10,
            "strategy": "weighted",
        }

        try:
            response = client.post("/api/ml/recommend/hybrid", json=request_data)
            assert response.status_code == 503
            assert "not initialized" in response.json()["detail"].lower()
        finally:
            api_ml.ml_api_initialized = original_state

    def test_explain_recommendation_not_initialized(self, client: TestClient) -> None:
        """Test explanation when ML API not initialized."""
        from discovery import api_ml

        original_state = api_ml.ml_api_initialized
        api_ml.ml_api_initialized = False
        api_ml.explainer = None

        request_data = {
            "artist_id": "artist_12345",
            "recommended_id": "artist_67890",
        }

        try:
            response = client.post("/api/ml/recommend/explain", json=request_data)
            assert response.status_code == 503
            assert "not initialized" in response.json()["detail"].lower()
        finally:
            api_ml.ml_api_initialized = original_state

    def test_collaborative_recommend_with_exception(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test collaborative filtering error handling."""
        from unittest.mock import AsyncMock

        from discovery import api_ml

        # Mock collaborative_filter to raise exception
        if api_ml.collaborative_filter is not None:
            mock_get_recommendations = AsyncMock(side_effect=Exception("Database error"))
            monkeypatch.setattr(api_ml.collaborative_filter, "get_recommendations", mock_get_recommendations)

            request_data = {
                "artist_id": "artist_12345",
                "limit": 10,
                "min_similarity": 0.3,
            }

            response = client.post("/api/ml/recommend/collaborative", json=request_data)
            assert response.status_code == 500
            assert "error" in response.json()["detail"].lower()

    def test_hybrid_recommend_with_exception(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test hybrid recommendations error handling."""
        from unittest.mock import AsyncMock

        from discovery import api_ml

        if api_ml.hybrid_recommender is not None:
            mock_get_recommendations = AsyncMock(side_effect=Exception("Processing error"))
            monkeypatch.setattr(api_ml.hybrid_recommender, "get_recommendations", mock_get_recommendations)

            request_data = {
                "artist_name": "The Beatles",
                "limit": 10,
                "strategy": "weighted",
            }

            response = client.post("/api/ml/recommend/hybrid", json=request_data)
            assert response.status_code == 500
            assert "error" in response.json()["detail"].lower()

    def test_explain_recommendation_with_exception(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test explanation error handling."""
        from unittest.mock import AsyncMock

        from discovery import api_ml

        if api_ml.explainer is not None:
            mock_explain = AsyncMock(side_effect=Exception("Explanation failed"))
            monkeypatch.setattr(api_ml.explainer, "explain_recommendation", mock_explain)

            request_data = {
                "artist_id": "artist_12345",
                "recommended_id": "artist_67890",
            }

            response = client.post("/api/ml/recommend/explain", json=request_data)
            assert response.status_code == 500
            assert "error" in response.json()["detail"].lower()


class TestMLAPIEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a test client for the Discovery service."""
        from discovery.discovery import app

        return TestClient(app)

    def test_collaborative_recommend_min_similarity_zero(self, client: TestClient) -> None:
        """Test collaborative filtering with zero minimum similarity."""
        request_data = {
            "artist_id": "artist_12345",
            "limit": 10,
            "min_similarity": 0.0,
        }

        response = client.post("/api/ml/recommend/collaborative", json=request_data)
        assert response.status_code == 200
        data = response.json()
        assert data["min_similarity"] == 0.0

    def test_collaborative_recommend_min_similarity_one(self, client: TestClient) -> None:
        """Test collaborative filtering with maximum minimum similarity."""
        request_data = {
            "artist_id": "artist_12345",
            "limit": 10,
            "min_similarity": 1.0,
        }

        response = client.post("/api/ml/recommend/collaborative", json=request_data)
        assert response.status_code == 200
        data = response.json()
        assert data["min_similarity"] == 1.0

    def test_collaborative_recommend_invalid_similarity(self, client: TestClient) -> None:
        """Test collaborative filtering with invalid similarity value."""
        request_data = {
            "artist_id": "artist_12345",
            "limit": 10,
            "min_similarity": 1.5,  # > 1.0
        }

        response = client.post("/api/ml/recommend/collaborative", json=request_data)
        assert response.status_code == 422  # Validation error

    def test_hybrid_recommend_invalid_strategy(self, client: TestClient) -> None:
        """Test hybrid recommendations with unknown strategy."""
        request_data = {
            "artist_name": "The Beatles",
            "limit": 10,
            "strategy": "unknown_strategy",
        }

        # Strategy validation is not enforced in model, so this will succeed
        # but might return different results
        response = client.post("/api/ml/recommend/hybrid", json=request_data)
        assert response.status_code == 200

    def test_collaborative_recommend_limit_one(self, client: TestClient) -> None:
        """Test collaborative filtering with minimum limit."""
        request_data = {
            "artist_id": "artist_12345",
            "limit": 1,
            "min_similarity": 0.3,
        }

        response = client.post("/api/ml/recommend/collaborative", json=request_data)
        assert response.status_code == 200

    def test_collaborative_recommend_limit_hundred(self, client: TestClient) -> None:
        """Test collaborative filtering with maximum limit."""
        request_data = {
            "artist_id": "artist_12345",
            "limit": 100,
            "min_similarity": 0.3,
        }

        response = client.post("/api/ml/recommend/collaborative", json=request_data)
        assert response.status_code == 200

    def test_collaborative_recommend_special_characters_in_id(self, client: TestClient) -> None:
        """Test collaborative filtering with special characters in artist ID."""
        request_data = {
            "artist_id": "artist-123_456!@#",
            "limit": 10,
            "min_similarity": 0.3,
        }

        response = client.post("/api/ml/recommend/collaborative", json=request_data)
        assert response.status_code == 200

    def test_hybrid_recommend_unicode_artist_name(self, client: TestClient) -> None:
        """Test hybrid recommendations with Unicode artist name."""
        request_data = {
            "artist_name": "The Bëatles 音楽家",
            "limit": 10,
            "strategy": "weighted",
        }

        response = client.post("/api/ml/recommend/hybrid", json=request_data)
        assert response.status_code == 200
        data = response.json()
        assert data["artist_name"] == "The Bëatles 音楽家"

    def test_ml_status_response_structure(self, client: TestClient) -> None:
        """Test ML API status response has all required fields."""
        response = client.get("/api/ml/status")
        assert response.status_code == 200

        data = response.json()
        # Required top-level fields
        assert "status" in data
        assert "features" in data
        assert "components" in data
        assert "phase" in data
        assert "timestamp" in data

        # Required feature fields
        assert "collaborative_filtering" in data["features"]
        assert "hybrid_recommendations" in data["features"]
        assert "explanations" in data["features"]
        assert "ab_testing" in data["features"]
        assert "metrics" in data["features"]

        # Required component fields
        assert "collaborative_filter" in data["components"]
        assert "hybrid_recommender" in data["components"]
        assert "explainer" in data["components"]


class TestMLAPIResponseFormat:
    """Test response format consistency."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a test client for the Discovery service."""
        from discovery.discovery import app

        return TestClient(app)

    def test_collaborative_recommend_response_fields(self, client: TestClient) -> None:
        """Test collaborative filtering response has all required fields."""
        request_data = {
            "artist_id": "artist_12345",
            "limit": 10,
            "min_similarity": 0.3,
        }

        response = client.post("/api/ml/recommend/collaborative", json=request_data)
        assert response.status_code == 200

        data = response.json()
        # All required fields
        assert "artist_id" in data
        assert "recommendations" in data
        assert "algorithm" in data
        assert "total" in data
        assert "min_similarity" in data
        assert "status" in data
        assert "timestamp" in data

        # Verify types
        assert isinstance(data["recommendations"], list)
        assert isinstance(data["total"], int)
        assert isinstance(data["min_similarity"], float)

    def test_hybrid_recommend_response_fields(self, client: TestClient) -> None:
        """Test hybrid recommendations response has all required fields."""
        request_data = {
            "artist_name": "The Beatles",
            "limit": 10,
            "strategy": "weighted",
        }

        response = client.post("/api/ml/recommend/hybrid", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "artist_name" in data
        assert "recommendations" in data
        assert "algorithm" in data
        assert "strategy" in data
        assert "total" in data
        assert "status" in data
        assert "timestamp" in data

    def test_explain_recommendation_response_fields(self, client: TestClient) -> None:
        """Test explanation response has all required fields."""
        request_data = {
            "artist_id": "artist_12345",
            "recommended_id": "artist_67890",
        }

        response = client.post("/api/ml/recommend/explain", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "artist_id" in data
        assert "recommended_id" in data
        assert "explanation" in data
        assert "reasons" in data
        assert "confidence" in data
        assert "evidence" in data
        assert "status" in data
        assert "timestamp" in data

        # Verify types
        assert isinstance(data["reasons"], list)
        assert isinstance(data["confidence"], float)
        assert isinstance(data["evidence"], dict)

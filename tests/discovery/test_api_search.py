"""E2E tests for Advanced Search API endpoints (Phase 4.2.2)."""

import pytest
from fastapi.testclient import TestClient


class TestSearchAPI:
    """Test Advanced Search API endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a test client for the Discovery service."""
        from discovery.discovery import app

        return TestClient(app)

    def test_fulltext_search_endpoint(self, client: TestClient) -> None:
        """Test full-text search endpoint."""
        request_data = {
            "query": "Beatles",
            "entity": "artist",
            "operator": "and",
            "limit": 50,
            "offset": 0,
            "rank_threshold": 0.0,
        }

        response = client.post("/api/search/fulltext", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "query" in data
        assert data["query"] == "Beatles"
        assert "entity" in data
        assert data["entity"] == "artist"
        assert "operator" in data
        assert data["operator"] == "and"
        assert "results" in data
        assert "total" in data
        assert "search_type" in data
        assert data["search_type"] == "fulltext"
        assert "status" in data
        assert data["status"] == "not_implemented"
        assert "timestamp" in data

    def test_fulltext_search_operators(self, client: TestClient) -> None:
        """Test full-text search with different operators."""
        operators = ["and", "or", "phrase", "proximity"]

        for operator in operators:
            request_data = {
                "query": "Pink Floyd",
                "entity": "artist",
                "operator": operator,
                "limit": 20,
            }

            response = client.post("/api/search/fulltext", json=request_data)
            assert response.status_code == 200

            data = response.json()
            assert data["operator"] == operator

    def test_fulltext_search_entities(self, client: TestClient) -> None:
        """Test full-text search across different entity types."""
        entities = ["artist", "release", "label", "master", "all"]

        for entity in entities:
            request_data = {
                "query": "Jazz",
                "entity": entity,
                "operator": "and",
                "limit": 10,
            }

            response = client.post("/api/search/fulltext", json=request_data)
            assert response.status_code == 200

            data = response.json()
            assert data["entity"] == entity

    def test_semantic_search_endpoint(self, client: TestClient) -> None:
        """Test semantic search endpoint."""
        request_data = {
            "query": "experimental electronic music with ambient textures",
            "entity": "artist",
            "limit": 20,
            "similarity_threshold": 0.5,
        }

        response = client.post("/api/search/semantic", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "query" in data
        assert "entity" in data
        assert data["entity"] == "artist"
        assert "results" in data
        assert "search_type" in data
        assert data["search_type"] == "semantic"
        assert "status" in data
        assert data["status"] == "not_implemented"
        assert "timestamp" in data

    def test_semantic_search_validation(self, client: TestClient) -> None:
        """Test semantic search with boundary values."""
        # Test minimum similarity threshold
        request_data = {
            "query": "jazz fusion",
            "entity": "artist",
            "limit": 10,
            "similarity_threshold": 0.0,
        }

        response = client.post("/api/search/semantic", json=request_data)
        assert response.status_code == 200

        # Test maximum similarity threshold
        request_data["similarity_threshold"] = 1.0
        response = client.post("/api/search/semantic", json=request_data)
        assert response.status_code == 200

        # Test exceeding max query length
        request_data["query"] = "a" * 501  # exceeds max of 500
        response = client.post("/api/search/semantic", json=request_data)
        assert response.status_code == 422  # Validation error

    def test_faceted_search_endpoint(self, client: TestClient) -> None:
        """Test faceted search endpoint."""
        request_data = {
            "query": "electronic",
            "entity": "release",
            "facets": {
                "genre": ["Electronic", "Ambient"],
                "year": ["2020", "2021", "2022"],
            },
            "limit": 50,
            "offset": 0,
        }

        response = client.post("/api/search/faceted", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "query" in data
        assert data["query"] == "electronic"
        assert "entity" in data
        assert data["entity"] == "release"
        assert "facets" in data
        assert "results" in data
        assert "available_facets" in data
        assert "search_type" in data
        assert data["search_type"] == "faceted"
        assert "status" in data
        assert "timestamp" in data

    def test_faceted_search_without_query(self, client: TestClient) -> None:
        """Test faceted search with only facet filters (no query)."""
        request_data = {
            "entity": "release",
            "facets": {
                "genre": ["Jazz"],
                "year": ["1960"],
            },
            "limit": 30,
        }

        response = client.post("/api/search/faceted", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert data["query"] is None
        assert len(data["facets"]) > 0

    def test_autocomplete_endpoint(self, client: TestClient) -> None:
        """Test autocomplete search endpoint."""
        request_data = {
            "prefix": "Bea",
            "entity": "artist",
            "limit": 10,
        }

        response = client.post("/api/search/autocomplete", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "prefix" in data
        assert data["prefix"] == "Bea"
        assert "entity" in data
        assert data["entity"] == "artist"
        assert "suggestions" in data
        assert "status" in data
        assert data["status"] == "not_implemented"
        assert "timestamp" in data

    def test_autocomplete_validation(self, client: TestClient) -> None:
        """Test autocomplete with validation errors."""
        # Test exceeding max prefix length
        request_data = {
            "prefix": "a" * 101,  # exceeds max of 100
            "entity": "artist",
            "limit": 10,
        }

        response = client.post("/api/search/autocomplete", json=request_data)
        assert response.status_code == 422  # Validation error

        # Test exceeding max limit
        request_data = {
            "prefix": "test",
            "entity": "artist",
            "limit": 100,  # exceeds max of 50
        }

        response = client.post("/api/search/autocomplete", json=request_data)
        assert response.status_code == 422  # Validation error

    def test_search_stats_endpoint(self, client: TestClient) -> None:
        """Test search statistics endpoint."""
        response = client.get("/api/search/stats")
        assert response.status_code == 200

        data = response.json()
        assert "statistics" in data
        stats = data["statistics"]
        assert "artists" in stats
        assert "releases" in stats
        assert "labels" in stats
        assert "masters" in stats
        assert "total_searchable" in stats
        assert "status" in data
        assert "timestamp" in data

    def test_search_api_status_endpoint(self, client: TestClient) -> None:
        """Test Search API status endpoint."""
        response = client.get("/api/search/status")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert data["status"] in ["initialized", "not_initialized"]
        assert "features" in data
        assert "fulltext_search" in data["features"]
        assert "semantic_search" in data["features"]
        assert "faceted_search" in data["features"]
        assert "autocomplete" in data["features"]
        assert "statistics" in data["features"]
        assert "phase" in data
        assert data["phase"] == "4.1.2"
        assert "timestamp" in data

    def test_fulltext_search_pagination(self, client: TestClient) -> None:
        """Test full-text search pagination."""
        # First page
        request_data = {
            "query": "jazz",
            "entity": "artist",
            "operator": "and",
            "limit": 10,
            "offset": 0,
        }

        response = client.post("/api/search/fulltext", json=request_data)
        assert response.status_code == 200

        # Second page
        request_data["offset"] = 10
        response = client.post("/api/search/fulltext", json=request_data)
        assert response.status_code == 200

    def test_query_length_validation(self, client: TestClient) -> None:
        """Test query length validation across search endpoints."""
        # Test minimum query length (should fail)
        request_data = {
            "query": "",  # too short
            "entity": "artist",
        }

        response = client.post("/api/search/fulltext", json=request_data)
        assert response.status_code == 422  # Validation error


class TestSearchAPIIntegration:
    """Integration tests for Search API."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a test client for the Discovery service."""
        from discovery.discovery import app

        return TestClient(app)

    def test_search_api_in_openapi_docs(self, client: TestClient) -> None:
        """Test that Search API endpoints appear in OpenAPI documentation."""
        response = client.get("/openapi.json")
        assert response.status_code == 200

        openapi_spec = response.json()
        assert "/api/search/fulltext" in openapi_spec["paths"]
        assert "/api/search/semantic" in openapi_spec["paths"]
        assert "/api/search/faceted" in openapi_spec["paths"]
        assert "/api/search/autocomplete" in openapi_spec["paths"]
        assert "/api/search/stats" in openapi_spec["paths"]
        assert "/api/search/status" in openapi_spec["paths"]

        # Check that Advanced Search tag exists
        tags = [tag["name"] for tag in openapi_spec.get("tags", [])]
        assert "Advanced Search" in tags

    def test_search_response_consistency(self, client: TestClient) -> None:
        """Test that all search endpoints return consistent response format."""
        endpoints_and_data = [
            ("/api/search/fulltext", {"query": "test", "entity": "artist"}),
            ("/api/search/semantic", {"query": "test", "entity": "artist"}),
            ("/api/search/faceted", {"entity": "artist", "facets": {}}),
            ("/api/search/autocomplete", {"prefix": "test", "entity": "artist"}),
        ]

        for endpoint, request_data in endpoints_and_data:
            response = client.post(endpoint, json=request_data)
            assert response.status_code == 200

            data = response.json()
            assert "status" in data
            assert "timestamp" in data
            # ISO 8601 format check
            assert "T" in data["timestamp"]

    def test_multiple_concurrent_searches(self, client: TestClient) -> None:
        """Test handling multiple concurrent search requests."""
        request_data = {
            "query": "jazz",
            "entity": "artist",
            "operator": "and",
            "limit": 10,
        }

        # Simulate concurrent requests
        responses = []
        for _ in range(5):
            response = client.post("/api/search/fulltext", json=request_data)
            responses.append(response)

        # All requests should succeed
        for response in responses:
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "not_implemented"

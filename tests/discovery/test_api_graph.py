"""E2E tests for Graph Analytics API endpoints (Phase 4.2.3)."""

import pytest
from fastapi.testclient import TestClient


class TestGraphAPI:
    """Test Graph Analytics API endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a test client for the Discovery service."""
        from discovery.discovery import app

        return TestClient(app)

    def test_centrality_endpoint(self, client: TestClient) -> None:
        """Test centrality metrics calculation endpoint."""
        request_data = {
            "metric": "pagerank",
            "limit": 20,
            "node_type": "artist",
            "sample_size": None,
        }

        response = client.post("/api/graph/centrality", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "metric" in data
        assert data["metric"] == "pagerank"
        assert "node_type" in data
        assert data["node_type"] == "artist"
        assert "top_nodes" in data
        assert "status" in data
        assert data["status"] == "not_implemented"
        assert "timestamp" in data

    def test_centrality_metrics(self, client: TestClient) -> None:
        """Test different centrality metric types."""
        metrics = ["degree", "betweenness", "closeness", "eigenvector", "pagerank"]

        for metric in metrics:
            request_data = {
                "metric": metric,
                "limit": 10,
                "node_type": "artist",
            }

            response = client.post("/api/graph/centrality", json=request_data)
            assert response.status_code == 200

            data = response.json()
            assert data["metric"] == metric

    def test_centrality_node_types(self, client: TestClient) -> None:
        """Test centrality calculation for different node types."""
        node_types = ["artist", "release", "label"]

        for node_type in node_types:
            request_data = {
                "metric": "pagerank",
                "limit": 15,
                "node_type": node_type,
            }

            response = client.post("/api/graph/centrality", json=request_data)
            assert response.status_code == 200

            data = response.json()
            assert data["node_type"] == node_type

    def test_centrality_with_sampling(self, client: TestClient) -> None:
        """Test centrality calculation with sample size."""
        request_data = {
            "metric": "betweenness",
            "limit": 20,
            "node_type": "artist",
            "sample_size": 1000,
        }

        response = client.post("/api/graph/centrality", json=request_data)
        assert response.status_code == 200

    def test_centrality_validation(self, client: TestClient) -> None:
        """Test centrality endpoint validation."""
        # Test exceeding max limit
        request_data = {
            "metric": "pagerank",
            "limit": 200,  # exceeds max of 100
            "node_type": "artist",
        }

        response = client.post("/api/graph/centrality", json=request_data)
        assert response.status_code == 422  # Validation error

        # Test invalid sample size (too small)
        request_data = {
            "metric": "pagerank",
            "limit": 20,
            "node_type": "artist",
            "sample_size": 50,  # below min of 100
        }

        response = client.post("/api/graph/centrality", json=request_data)
        assert response.status_code == 422  # Validation error

    def test_community_detection_endpoint(self, client: TestClient) -> None:
        """Test community detection endpoint."""
        request_data = {
            "algorithm": "louvain",
            "min_community_size": 5,
            "resolution": 1.0,
        }

        response = client.post("/api/graph/communities", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "algorithm" in data
        assert data["algorithm"] == "louvain"
        assert "communities" in data
        assert "modularity" in data
        assert "status" in data
        assert data["status"] == "not_implemented"
        assert "timestamp" in data

    def test_community_detection_algorithms(self, client: TestClient) -> None:
        """Test different community detection algorithms."""
        algorithms = ["louvain", "label_propagation"]

        for algorithm in algorithms:
            request_data = {
                "algorithm": algorithm,
                "min_community_size": 5,
                "resolution": 1.0,
            }

            response = client.post("/api/graph/communities", json=request_data)
            assert response.status_code == 200

            data = response.json()
            assert data["algorithm"] == algorithm

    def test_community_detection_resolution(self, client: TestClient) -> None:
        """Test community detection with different resolution values."""
        resolutions = [0.1, 0.5, 1.0, 1.5, 2.0]

        for resolution in resolutions:
            request_data = {
                "algorithm": "louvain",
                "min_community_size": 3,
                "resolution": resolution,
            }

            response = client.post("/api/graph/communities", json=request_data)
            assert response.status_code == 200

    def test_genre_evolution_endpoint(self, client: TestClient) -> None:
        """Test genre evolution analysis endpoint."""
        request_data = {
            "genre": "Electronic",
            "start_year": 1980,
            "end_year": 2020,
        }

        response = client.post("/api/graph/genre-evolution", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "genre" in data
        assert data["genre"] == "Electronic"
        assert "start_year" in data
        assert data["start_year"] == 1980
        assert "end_year" in data
        assert data["end_year"] == 2020
        assert "evolution_data" in data
        assert "status" in data
        assert data["status"] == "not_implemented"
        assert "timestamp" in data

    def test_genre_evolution_year_validation(self, client: TestClient) -> None:
        """Test genre evolution with year boundary validation."""
        # Test minimum year
        request_data = {
            "genre": "Jazz",
            "start_year": 1900,
            "end_year": 1950,
        }

        response = client.post("/api/graph/genre-evolution", json=request_data)
        assert response.status_code == 200

        # Test maximum year
        request_data = {
            "genre": "Electronic",
            "start_year": 2000,
            "end_year": 2030,
        }

        response = client.post("/api/graph/genre-evolution", json=request_data)
        assert response.status_code == 200

        # Test year below minimum
        request_data = {
            "genre": "Classical",
            "start_year": 1800,  # below min of 1900
            "end_year": 1950,
        }

        response = client.post("/api/graph/genre-evolution", json=request_data)
        assert response.status_code == 422  # Validation error

    def test_similarity_network_endpoint(self, client: TestClient) -> None:
        """Test similarity network building endpoint."""
        request_data = {
            "artist_id": "artist_12345",
            "max_depth": 2,
            "similarity_threshold": 0.3,
            "max_nodes": 50,
        }

        response = client.post("/api/graph/similarity-network", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "artist_id" in data
        assert data["artist_id"] == "artist_12345"
        assert "max_depth" in data
        assert data["max_depth"] == 2
        assert "nodes" in data
        assert "edges" in data
        assert "status" in data
        assert data["status"] == "not_implemented"
        assert "timestamp" in data

    def test_similarity_network_depth_validation(self, client: TestClient) -> None:
        """Test similarity network with depth validation."""
        # Test minimum depth
        request_data = {
            "artist_id": "artist_12345",
            "max_depth": 1,
            "similarity_threshold": 0.3,
            "max_nodes": 20,
        }

        response = client.post("/api/graph/similarity-network", json=request_data)
        assert response.status_code == 200

        # Test maximum depth
        request_data["max_depth"] = 5
        response = client.post("/api/graph/similarity-network", json=request_data)
        assert response.status_code == 200

        # Test exceeding max depth
        request_data["max_depth"] = 10  # exceeds max of 5
        response = client.post("/api/graph/similarity-network", json=request_data)
        assert response.status_code == 422  # Validation error

    def test_similarity_network_node_limits(self, client: TestClient) -> None:
        """Test similarity network with node count limits."""
        # Test minimum nodes
        request_data = {
            "artist_id": "artist_12345",
            "max_depth": 2,
            "similarity_threshold": 0.5,
            "max_nodes": 10,
        }

        response = client.post("/api/graph/similarity-network", json=request_data)
        assert response.status_code == 200

        # Test maximum nodes
        request_data["max_nodes"] = 200
        response = client.post("/api/graph/similarity-network", json=request_data)
        assert response.status_code == 200

        # Test exceeding max nodes
        request_data["max_nodes"] = 500  # exceeds max of 200
        response = client.post("/api/graph/similarity-network", json=request_data)
        assert response.status_code == 422  # Validation error

    def test_graph_stats_endpoint(self, client: TestClient) -> None:
        """Test graph statistics endpoint."""
        response = client.get("/api/graph/stats")
        assert response.status_code == 200

        data = response.json()
        assert "statistics" in data
        stats = data["statistics"]
        assert "total_nodes" in stats
        assert "total_edges" in stats
        assert "node_types" in stats
        assert "edge_types" in stats
        assert "status" in data
        assert "timestamp" in data

    def test_graph_api_status_endpoint(self, client: TestClient) -> None:
        """Test Graph Analytics API status endpoint."""
        response = client.get("/api/graph/status")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert data["status"] in ["initialized", "not_initialized"]
        assert "features" in data
        assert "centrality_metrics" in data["features"]
        assert "community_detection" in data["features"]
        assert "genre_evolution" in data["features"]
        assert "similarity_networks" in data["features"]
        assert "statistics" in data["features"]
        assert "phase" in data
        assert data["phase"] == "4.1.3"
        assert "timestamp" in data

    def test_similarity_threshold_boundaries(self, client: TestClient) -> None:
        """Test similarity network with threshold boundaries."""
        # Test minimum threshold
        request_data = {
            "artist_id": "artist_12345",
            "max_depth": 2,
            "similarity_threshold": 0.0,
            "max_nodes": 50,
        }

        response = client.post("/api/graph/similarity-network", json=request_data)
        assert response.status_code == 200

        # Test maximum threshold
        request_data["similarity_threshold"] = 1.0
        response = client.post("/api/graph/similarity-network", json=request_data)
        assert response.status_code == 200


class TestGraphAPIIntegration:
    """Integration tests for Graph Analytics API."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a test client for the Discovery service."""
        from discovery.discovery import app

        return TestClient(app)

    def test_graph_api_in_openapi_docs(self, client: TestClient) -> None:
        """Test that Graph API endpoints appear in OpenAPI documentation."""
        response = client.get("/openapi.json")
        assert response.status_code == 200

        openapi_spec = response.json()
        assert "/api/graph/centrality" in openapi_spec["paths"]
        assert "/api/graph/communities" in openapi_spec["paths"]
        assert "/api/graph/genre-evolution" in openapi_spec["paths"]
        assert "/api/graph/similarity-network" in openapi_spec["paths"]
        assert "/api/graph/stats" in openapi_spec["paths"]
        assert "/api/graph/status" in openapi_spec["paths"]

        # Check that Graph Analytics tag exists
        tags = [tag["name"] for tag in openapi_spec.get("tags", [])]
        assert "Graph Analytics" in tags

    def test_graph_response_consistency(self, client: TestClient) -> None:
        """Test that all graph endpoints return consistent response format."""
        endpoints_and_data = [
            ("/api/graph/centrality", {"metric": "pagerank", "limit": 10, "node_type": "artist"}),
            ("/api/graph/communities", {"algorithm": "louvain", "min_community_size": 5}),
            ("/api/graph/genre-evolution", {"genre": "Jazz", "start_year": 1950, "end_year": 2000}),
            ("/api/graph/similarity-network", {"artist_id": "test", "max_depth": 2, "max_nodes": 20}),
        ]

        for endpoint, request_data in endpoints_and_data:
            response = client.post(endpoint, json=request_data)
            assert response.status_code == 200

            data = response.json()
            assert "status" in data
            assert "timestamp" in data
            # ISO 8601 format check
            assert "T" in data["timestamp"]

    def test_multiple_concurrent_graph_operations(self, client: TestClient) -> None:
        """Test handling multiple concurrent graph analytics requests."""
        request_data = {
            "metric": "pagerank",
            "limit": 20,
            "node_type": "artist",
        }

        # Simulate concurrent requests
        responses = []
        for _ in range(5):
            response = client.post("/api/graph/centrality", json=request_data)
            responses.append(response)

        # All requests should succeed
        for response in responses:
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "not_implemented"

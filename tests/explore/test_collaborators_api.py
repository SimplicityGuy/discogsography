"""Tests for GET /api/collaborators/{artist_id} endpoint."""

from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from neo4j.exceptions import ClientError as Neo4jClientError


class TestCollaboratorsEndpoint:
    """Test the collaborators API endpoint."""

    def test_collaborators_success(
        self,
        test_client: TestClient,
        sample_collaborators_data: dict[str, Any],
    ) -> None:
        """GET /api/collaborators/123 returns 200 with collaborator data."""
        identity = {"artist_id": "123", "artist_name": "Radiohead"}
        collaborators = sample_collaborators_data["collaborators"]
        total = sample_collaborators_data["total"]

        with (
            patch(
                "api.routers.explore.collaborator_queries.get_artist_identity",
                new_callable=AsyncMock,
                return_value=identity,
            ),
            patch(
                "api.routers.explore.collaborator_queries.get_collaborators",
                new_callable=AsyncMock,
                return_value=collaborators,
            ),
            patch(
                "api.routers.explore.collaborator_queries.count_collaborators",
                new_callable=AsyncMock,
                return_value=total,
            ),
        ):
            response = test_client.get("/api/collaborators/123")

        assert response.status_code == 200
        data = response.json()
        assert data["artist_id"] == "123"
        assert data["artist_name"] == "Radiohead"
        assert len(data["collaborators"]) == 2
        assert data["total"] == 42

        # Verify collaborator structure
        collab = data["collaborators"][0]
        assert collab["artist_id"] == "456"
        assert collab["artist_name"] == "Thom Yorke"
        assert collab["release_count"] == 5
        assert collab["first_year"] == 1993
        assert collab["last_year"] == 2011
        assert isinstance(collab["yearly_counts"], list)

    def test_collaborators_not_found(self, test_client: TestClient) -> None:
        """GET /api/collaborators/999 returns 404 when artist does not exist."""
        with patch(
            "api.routers.explore.collaborator_queries.get_artist_identity",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = test_client.get("/api/collaborators/999")

        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_collaborators_service_not_ready(self, test_client: TestClient) -> None:
        """GET /api/collaborators/123 returns 503 when driver is None."""
        import api.routers.explore as explore_module

        original_driver = explore_module._neo4j_driver
        explore_module._neo4j_driver = None

        response = test_client.get("/api/collaborators/123")
        assert response.status_code == 503

        explore_module._neo4j_driver = original_driver

    def test_collaborators_limit_param(self, test_client: TestClient) -> None:
        """GET /api/collaborators/123?limit=5 passes limit to query."""
        identity = {"artist_id": "123", "artist_name": "Radiohead"}

        mock_get_collabs = AsyncMock(return_value=[])
        with (
            patch(
                "api.routers.explore.collaborator_queries.get_artist_identity",
                new_callable=AsyncMock,
                return_value=identity,
            ),
            patch(
                "api.routers.explore.collaborator_queries.get_collaborators",
                mock_get_collabs,
            ),
            patch(
                "api.routers.explore.collaborator_queries.count_collaborators",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            response = test_client.get("/api/collaborators/123?limit=5")

        assert response.status_code == 200
        # Verify the limit was passed through
        mock_get_collabs.assert_awaited_once()
        call_args = mock_get_collabs.call_args
        assert call_args[1].get("limit") == 5 or (len(call_args[0]) >= 3 and call_args[0][2] == 5)

    def test_collaborators_empty(self, test_client: TestClient) -> None:
        """GET /api/collaborators/123 returns empty list when no collaborators."""
        identity = {"artist_id": "123", "artist_name": "Solo Artist"}

        with (
            patch(
                "api.routers.explore.collaborator_queries.get_artist_identity",
                new_callable=AsyncMock,
                return_value=identity,
            ),
            patch(
                "api.routers.explore.collaborator_queries.get_collaborators",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "api.routers.explore.collaborator_queries.count_collaborators",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            response = test_client.get("/api/collaborators/123")

        assert response.status_code == 200
        data = response.json()
        assert data["artist_id"] == "123"
        assert data["artist_name"] == "Solo Artist"
        assert data["collaborators"] == []
        assert data["total"] == 0

    def test_collaborators_limit_validation_too_high(self, test_client: TestClient) -> None:
        """GET /api/collaborators/123?limit=200 returns 422 (exceeds max)."""
        response = test_client.get("/api/collaborators/123?limit=200")
        assert response.status_code == 422

    def test_collaborators_limit_validation_too_low(self, test_client: TestClient) -> None:
        """GET /api/collaborators/123?limit=0 returns 422 (below min)."""
        response = test_client.get("/api/collaborators/123?limit=0")
        assert response.status_code == 422

    def test_collaborators_timeout(self, test_client: TestClient) -> None:
        """GET /api/collaborators/123 returns 504 on Neo4j timeout."""
        identity = {"artist_id": "123", "artist_name": "Radiohead"}

        with (
            patch(
                "api.routers.explore.collaborator_queries.get_artist_identity",
                new_callable=AsyncMock,
                return_value=identity,
            ),
            patch(
                "api.routers.explore.collaborator_queries.get_collaborators",
                new_callable=AsyncMock,
                side_effect=Neo4jClientError("TransactionTimedOut"),
            ),
            patch(
                "api.routers.explore.collaborator_queries.count_collaborators",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            response = test_client.get("/api/collaborators/123")

        assert response.status_code == 504
        assert "timed out" in response.json()["error"].lower()

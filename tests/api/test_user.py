"""Tests for user endpoints in the API service (api/routers/user.py)."""

import time
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class TestUserCollectionEndpoint:
    """Tests for GET /api/user/collection."""

    def test_collection_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/collection")
        assert response.status_code in (401, 403)

    def test_collection_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = ([{"id": "r1", "name": "OK Computer"}], 1)
        with patch("api.routers.user.get_user_collection", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/collection", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "releases" in data
        assert "total" in data
        assert data["total"] == 1

    def test_collection_no_driver_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.routers.user as user_module

        original = user_module._neo4j_driver
        user_module._neo4j_driver = None
        try:
            response = test_client.get("/api/user/collection", headers=auth_headers)
            assert response.status_code == 503
        finally:
            user_module._neo4j_driver = original


class TestUserWantlistEndpoint:
    """Tests for GET /api/user/wantlist."""

    def test_wantlist_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/wantlist")
        assert response.status_code in (401, 403)

    def test_wantlist_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = ([{"id": "r2", "name": "Kid A"}], 1)
        with patch("api.routers.user.get_user_wantlist", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/wantlist", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "releases" in data

    def test_wantlist_no_driver_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.routers.user as user_module

        original = user_module._neo4j_driver
        user_module._neo4j_driver = None
        try:
            response = test_client.get("/api/user/wantlist", headers=auth_headers)
            assert response.status_code == 503
        finally:
            user_module._neo4j_driver = original


class TestUserRecommendationsEndpoint:
    """Tests for GET /api/user/recommendations."""

    def test_recommendations_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/recommendations")
        assert response.status_code in (401, 403)

    def test_recommendations_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = [{"id": "r3", "name": "Amnesiac"}]
        with patch("api.routers.user.get_user_recommendations", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/recommendations", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "recommendations" in data
        assert data["total"] == 1

    def test_recommendations_artist_normalizes_scores(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        """Artist strategy normalizes raw count scores to 0-1 range."""
        mock_result = [
            {"id": "r1", "title": "Album A", "score": 130},
            {"id": "r2", "title": "Album B", "score": 65},
            {"id": "r3", "title": "Album C", "score": 0},
        ]
        with patch("api.routers.user.get_user_recommendations", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/recommendations", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        scores = [r["score"] for r in data["recommendations"]]
        assert scores[0] == 1.0  # max score normalized to 1
        assert scores[1] == 0.5  # 65/130
        assert scores[2] == 0.0  # 0/130
        assert all(0 <= s <= 1 for s in scores)

    def test_recommendations_artist_empty_skips_normalization(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        """Empty results skip normalization without error."""
        with patch("api.routers.user.get_user_recommendations", new=AsyncMock(return_value=[])):
            response = test_client.get("/api/user/recommendations", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["recommendations"] == []


class TestUserCollectionStatsEndpoint:
    """Tests for GET /api/user/collection/stats."""

    def test_stats_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/collection/stats")
        assert response.status_code in (401, 403)

    def test_stats_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_stats = {"genres": [], "decades": [], "labels": []}
        with patch("api.routers.user.get_user_collection_stats", new=AsyncMock(return_value=mock_stats)):
            response = test_client.get("/api/user/collection/stats", headers=auth_headers)
        assert response.status_code == 200


class TestUserCollectionTimelineEndpoint:
    """Tests for GET /api/user/collection/timeline."""

    def test_timeline_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/collection/timeline")
        assert response.status_code in (401, 403)

    def test_timeline_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = {
            "timeline": [{"year": 1985, "count": 3, "genres": {"Rock": 3}, "top_labels": ["4AD"], "top_styles": ["Post-Punk"]}],
            "insights": {"peak_year": 1985, "dominant_genre": "Rock", "genre_diversity_score": 0.0, "style_drift_rate": 0.0},
        }
        with patch("api.routers.user.get_user_collection_timeline", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/collection/timeline", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "timeline" in data
        assert "insights" in data
        assert data["timeline"][0]["year"] == 1985

    def test_timeline_decade_bucket(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = {"timeline": [], "insights": {"peak_year": None, "dominant_genre": None, "genre_diversity_score": 0.0, "style_drift_rate": 0.0}}
        with patch("api.routers.user.get_user_collection_timeline", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/collection/timeline?bucket=decade", headers=auth_headers)
        assert response.status_code == 200

    def test_timeline_invalid_bucket(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        response = test_client.get("/api/user/collection/timeline?bucket=month", headers=auth_headers)
        assert response.status_code == 422

    def test_timeline_no_driver_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.routers.user as user_module

        original = user_module._neo4j_driver
        user_module._neo4j_driver = None
        try:
            response = test_client.get("/api/user/collection/timeline", headers=auth_headers)
            assert response.status_code == 503
        finally:
            user_module._neo4j_driver = original


class TestUserCollectionEvolutionEndpoint:
    """Tests for GET /api/user/collection/evolution."""

    def test_evolution_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/collection/evolution")
        assert response.status_code in (401, 403)

    def test_evolution_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = {
            "metric": "genre",
            "data": [{"year": 1985, "values": {"Electronic": 5, "Rock": 3}}],
            "summary": {"total_years": 1, "unique_values": 2},
        }
        with patch("api.routers.user.get_user_collection_evolution", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/collection/evolution", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["metric"] == "genre"
        assert "data" in data
        assert "summary" in data

    def test_evolution_style_metric(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = {"metric": "style", "data": [], "summary": {"total_years": 0, "unique_values": 0}}
        with patch("api.routers.user.get_user_collection_evolution", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/collection/evolution?metric=style", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["metric"] == "style"

    def test_evolution_invalid_metric(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        response = test_client.get("/api/user/collection/evolution?metric=artist", headers=auth_headers)
        assert response.status_code == 422

    def test_evolution_no_driver_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.routers.user as user_module

        original = user_module._neo4j_driver
        user_module._neo4j_driver = None
        try:
            response = test_client.get("/api/user/collection/evolution", headers=auth_headers)
            assert response.status_code == 503
        finally:
            user_module._neo4j_driver = original


class TestUserStatusEndpoint:
    """Tests for GET /api/user/status."""

    def test_status_no_auth_returns_all_false(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/status?ids=1,2,3")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        for rid in ["1", "2", "3"]:
            assert data["status"][rid]["in_collection"] is False
            assert data["status"][rid]["in_wantlist"] is False

    def test_status_with_auth(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = {"r1": {"in_collection": True, "in_wantlist": False}}
        with patch("api.routers.user.check_releases_user_status", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/status?ids=r1,r2", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"]["r1"]["in_collection"] is True
        assert data["status"]["r2"]["in_collection"] is False  # default

    def test_status_empty_ids(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/status?ids=,,,")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == {}


class TestB64UrlDecode:
    """Tests for api.auth.b64url_decode."""

    def test_decode_with_padding_needed(self) -> None:
        """Padding branch executes when length % 4 != 0."""
        from api.auth import b64url_decode

        # "YQ" decodes to b"a" but needs 2 padding chars ("YQ==")
        result = b64url_decode("YQ")
        assert result == b"a"

    def test_decode_aligned_no_padding(self) -> None:
        """No padding when length already divisible by 4."""
        from api.auth import b64url_decode

        # "AAAA" is 4 chars, already aligned
        result = b64url_decode("AAAA")
        assert result == b"\x00\x00\x00"


class TestVerifyJwt:
    """Tests for api.auth.decode_token."""

    def test_wrong_part_count_raises(self) -> None:
        """Raises ValueError when token doesn't have 3 parts."""
        import pytest

        from api.auth import decode_token

        with pytest.raises(ValueError):
            decode_token("only.two", "secret")
        with pytest.raises(ValueError):
            decode_token("a.b.c.d", "secret")

    def test_bad_signature_raises(self) -> None:
        """Raises ValueError when signature doesn't match."""
        import pytest

        from api.auth import decode_token
        from tests.api.conftest import TEST_JWT_SECRET, make_test_jwt

        token = make_test_jwt(secret="wrong-secret")  # noqa: S106
        with pytest.raises(ValueError):
            decode_token(token, TEST_JWT_SECRET)

    def test_invalid_json_payload_raises(self) -> None:
        """Raises ValueError when body decodes to non-JSON bytes."""
        import base64
        import hashlib
        import hmac

        import pytest

        from api.auth import decode_token

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        secret = "test-secret"
        header = b64url(b'{"alg":"HS256"}')
        body = b64url(b"not-valid-json!")
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(secret.encode(), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"

        with pytest.raises(ValueError):
            decode_token(token, secret)

    def test_expired_token_raises(self) -> None:
        """Raises ValueError when token is expired."""
        import pytest

        from api.auth import decode_token
        from tests.api.conftest import TEST_JWT_SECRET, make_test_jwt

        expired_token = make_test_jwt(exp=1)  # epoch 1970
        with pytest.raises(ValueError):
            decode_token(expired_token, TEST_JWT_SECRET)

    def test_valid_token_returns_payload(self) -> None:
        """Happy path: returns the payload dict for a valid token."""
        from api.auth import decode_token
        from tests.api.conftest import TEST_JWT_SECRET, TEST_USER_ID, make_test_jwt

        token = make_test_jwt()
        result = decode_token(token, TEST_JWT_SECRET)
        assert result["sub"] == TEST_USER_ID


class TestRequireUser:
    """Tests for api.routers.user._require_user via endpoints."""

    def test_jwt_secret_none_returns_503(self, test_client: TestClient) -> None:
        """Line 77: _require_user raises 503 when _jwt_secret is None."""
        import api.dependencies as dependencies_module

        original = dependencies_module._jwt_secret
        dependencies_module._jwt_secret = None
        try:
            response = test_client.get(
                "/api/user/collection",
                headers={"Authorization": "Bearer anything"},
            )
            assert response.status_code == 503
        finally:
            dependencies_module._jwt_secret = original

    def test_bad_token_returns_401(self, test_client: TestClient) -> None:
        """Line 82: _require_user raises 401 when _verify_jwt returns None (bad sig)."""
        import base64
        import hashlib
        import hmac
        import json

        # Build a token with a wrong signature
        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256"}, separators=(",", ":")).encode())
        body = b64url(json.dumps({"sub": "uid", "exp": 9_999_999_999}, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(b"wrong-secret", signing_input, hashlib.sha256).digest())
        bad_token = f"{header}.{body}.{sig}"

        response = test_client.get(
            "/api/user/collection",
            headers={"Authorization": f"Bearer {bad_token}"},
        )
        assert response.status_code == 401


class TestUserEndpointsNoNeo4j:
    """Tests for user endpoints that return 503 when neo4j driver is None."""

    def test_recommendations_no_driver_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        """Line 118: user_recommendations returns 503 when _neo4j_driver is None."""
        import api.routers.user as user_module

        original = user_module._neo4j_driver
        user_module._neo4j_driver = None
        try:
            response = test_client.get("/api/user/recommendations", headers=auth_headers)
            assert response.status_code == 503
        finally:
            user_module._neo4j_driver = original

    def test_collection_stats_no_driver_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        """Line 129: user_collection_stats returns 503 when _neo4j_driver is None."""
        import api.routers.user as user_module

        original = user_module._neo4j_driver
        user_module._neo4j_driver = None
        try:
            response = test_client.get("/api/user/collection/stats", headers=auth_headers)
            assert response.status_code == 503
        finally:
            user_module._neo4j_driver = original


class TestReleaseStatusIdsLimit:
    """Tests for GET /api/user/status — 100-ID limit."""

    def test_over_100_ids_returns_422(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        ids = ",".join(str(i) for i in range(101))
        response = test_client.get(f"/api/user/status?ids={ids}", headers=auth_headers)
        assert response.status_code == 422
        assert "Too many IDs" in response.json()["error"]

    def test_exactly_100_ids_allowed(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        from unittest.mock import AsyncMock, patch

        ids = ",".join(str(i) for i in range(100))
        with patch("api.routers.user.check_releases_user_status", new=AsyncMock(return_value={})):
            response = test_client.get(f"/api/user/status?ids={ids}", headers=auth_headers)
        assert response.status_code == 200

    def test_error_message_format(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        ids = ",".join(str(i) for i in range(101))
        data = test_client.get(f"/api/user/status?ids={ids}", headers=auth_headers).json()
        assert data["error"] == "Too many IDs: maximum is 100"


class TestTimelineCache:
    """Tests for in-memory cache helpers (_get_cached / _set_cached) in user.py."""

    def test_get_cached_returns_none_for_missing_key(self) -> None:
        """_get_cached returns None when key is absent."""
        from api.routers.user import _get_cached, _timeline_cache

        _timeline_cache.clear()
        assert _get_cached("no-such-key") is None

    def test_get_cached_returns_none_for_expired_entry(self) -> None:
        """Lines 53-55: _get_cached evicts and returns None for TTL-expired entries."""
        from api.routers import user as user_module

        user_module._timeline_cache.clear()
        # Insert an entry with a timestamp in the distant past (far beyond TTL)
        expired_ts = time.monotonic() - user_module._TIMELINE_CACHE_TTL - 1
        user_module._timeline_cache["stale"] = (expired_ts, {"data": "old"})

        result = user_module._get_cached("stale")
        assert result is None
        assert "stale" not in user_module._timeline_cache

    def test_get_cached_moves_to_end_on_hit(self) -> None:
        """Lines 57-58: cache hit moves the key to the end (LRU order)."""
        from api.routers import user as user_module

        user_module._timeline_cache.clear()
        user_module._timeline_cache["first"] = (time.monotonic(), {"a": 1})
        user_module._timeline_cache["second"] = (time.monotonic(), {"b": 2})

        result = user_module._get_cached("first")
        assert result == {"a": 1}
        # "first" should now be last (most-recently used)
        assert list(user_module._timeline_cache.keys())[-1] == "first"

    def test_set_cached_evicts_oldest_when_full(self) -> None:
        """Line 65: _set_cached evicts the oldest entry when at capacity."""
        from api.routers import user as user_module

        user_module._timeline_cache.clear()
        original_max = user_module._TIMELINE_CACHE_MAX
        user_module._TIMELINE_CACHE_MAX = 2
        try:
            user_module._set_cached("key1", {"v": 1})
            user_module._set_cached("key2", {"v": 2})
            # Adding a third entry should evict "key1" (the oldest)
            user_module._set_cached("key3", {"v": 3})
            assert "key1" not in user_module._timeline_cache
            assert "key2" in user_module._timeline_cache
            assert "key3" in user_module._timeline_cache
        finally:
            user_module._TIMELINE_CACHE_MAX = original_max
            user_module._timeline_cache.clear()


class TestUserRecommendationsMultiStrategy:
    """Tests for GET /api/user/recommendations?strategy=multi (lines 109-148)."""

    def test_multi_strategy_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        """Lines 109-142: multi-signal recommendation strategy."""
        artist_results = [
            {"id": "r1", "title": "Album A", "artist": "Artist X", "label": "Label Z", "year": 2000, "genres": ["Rock"], "score": 3},
        ]
        label_results = [
            {
                "id": "r2",
                "title": "Album B",
                "artist": "Artist Y",
                "label": "Label Z",
                "year": 2001,
                "genres": ["Pop"],
                "score": 0.5,
                "source": "label: Label Z",
            },
        ]
        blindspot_results: list[dict] = []
        collector_counts: dict[str, int] = {"r1": 100, "r2": 50}

        with (
            patch("api.routers.user.get_user_recommendations", new=AsyncMock(return_value=artist_results)),
            patch("api.routers.user.get_label_affinity_candidates", new=AsyncMock(return_value=label_results)),
            patch("api.routers.user.get_blindspot_candidates", new=AsyncMock(return_value=blindspot_results)),
            patch("api.routers.user.get_collector_counts", new=AsyncMock(return_value=collector_counts)),
            patch("api.routers.user.merge_recommendation_candidates", return_value=[{"id": "r1"}, {"id": "r2"}]),
        ):
            response = test_client.get("/api/user/recommendations?strategy=multi", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["strategy"] == "multi"
        assert data["total"] == 2

    def test_multi_strategy_empty_candidates_skips_collector_counts(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        """When all candidates have no id, collector_counts call is skipped."""
        with (
            patch("api.routers.user.get_user_recommendations", new=AsyncMock(return_value=[])),
            patch("api.routers.user.get_label_affinity_candidates", new=AsyncMock(return_value=[])),
            patch("api.routers.user.get_blindspot_candidates", new=AsyncMock(return_value=[])),
            patch("api.routers.user.get_collector_counts", new=AsyncMock(return_value={})) as mock_cc,
            patch("api.routers.user.merge_recommendation_candidates", return_value=[]),
        ):
            response = test_client.get("/api/user/recommendations?strategy=multi", headers=auth_headers)
        assert response.status_code == 200
        # get_collector_counts should NOT have been called (all_ids is empty)
        mock_cc.assert_not_awaited()


class TestTimelineCacheHit:
    """Tests for cached timeline/evolution responses."""

    def test_timeline_returns_cached_result(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        """Line 173: timeline endpoint returns cached value without querying Neo4j."""
        from api.routers import user as user_module

        cache_key = f"timeline:{0x00000000_00000000_00000000_00000001!r}:year"
        # Use the real TEST_USER_ID from conftest
        from tests.api.conftest import TEST_USER_ID

        cache_key = f"timeline:{TEST_USER_ID}:year"
        cached_data = {
            "timeline": [{"year": 2000, "count": 5, "genres": {}, "top_labels": [], "top_styles": []}],
            "insights": {"peak_year": 2000, "dominant_genre": None, "genre_diversity_score": 0.0, "style_drift_rate": 0.0},
        }
        user_module._set_cached(cache_key, cached_data)
        try:
            with patch("api.routers.user.get_user_collection_timeline", new=AsyncMock()) as mock_timeline:
                response = test_client.get("/api/user/collection/timeline", headers=auth_headers)
            assert response.status_code == 200
            # Should NOT have called the DB query
            mock_timeline.assert_not_awaited()
        finally:
            user_module._timeline_cache.pop(cache_key, None)

    def test_evolution_returns_cached_result(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        """Line 190: evolution endpoint returns cached value without querying Neo4j."""
        from api.routers import user as user_module
        from tests.api.conftest import TEST_USER_ID

        cache_key = f"evolution:{TEST_USER_ID}:genre"
        cached_data = {"metric": "genre", "data": [], "summary": {"total_years": 0, "unique_values": 0}}
        user_module._set_cached(cache_key, cached_data)
        try:
            with patch("api.routers.user.get_user_collection_evolution", new=AsyncMock()) as mock_evo:
                response = test_client.get("/api/user/collection/evolution", headers=auth_headers)
            assert response.status_code == 200
            assert response.json()["metric"] == "genre"
            mock_evo.assert_not_awaited()
        finally:
            user_module._timeline_cache.pop(cache_key, None)


class TestGetOptionalUserInvalidToken:
    """Tests for _get_optional_user with an invalid token (user router)."""

    def test_invalid_token_returns_false_flags(self, test_client: TestClient) -> None:
        """user.py:42-43 — bad token on optional-auth /status falls back to all-False."""
        response = test_client.get(
            "/api/user/status?ids=1,2",
            headers={"Authorization": "Bearer not.a.valid.jwt"},
        )
        assert response.status_code == 200
        data = response.json()
        for _rid, flags in data["status"].items():
            assert flags["in_collection"] is False
            assert flags["in_wantlist"] is False

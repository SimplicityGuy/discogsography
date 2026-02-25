"""Tests for explore service user personalization queries."""

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# Set env vars before importing explore modules
os.environ.setdefault("NEO4J_ADDRESS", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "testpassword")

from explore.user_queries import (
    check_releases_user_status,
    get_user_collection,
    get_user_collection_stats,
    get_user_recommendations,
    get_user_wantlist,
)


def _make_driver(rows: list[dict[str, Any]]) -> MagicMock:
    """Build a mock AsyncResilientNeo4jDriver that returns given rows."""
    driver = MagicMock()
    mock_session = AsyncMock()
    mock_result = AsyncMock()

    async def _aiter(_self: Any) -> Any:  # type: ignore[override]
        for row in rows:
            yield row

    mock_result.__aiter__ = _aiter
    mock_result.single = AsyncMock(return_value=rows[0] if rows else None)

    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock(return_value=mock_result)

    driver.session = AsyncMock(return_value=mock_session)
    return driver


class TestCheckReleasesUserStatus:
    """Tests for check_releases_user_status."""

    @pytest.mark.asyncio
    async def test_empty_ids_returns_empty(self) -> None:
        driver = MagicMock()
        result = await check_releases_user_status(driver, "user-1", [])
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_status_dict(self) -> None:
        rows = [
            {"release_id": "10", "in_collection": True, "in_wantlist": False},
            {"release_id": "20", "in_collection": False, "in_wantlist": True},
        ]
        driver = _make_driver(rows)
        result = await check_releases_user_status(driver, "user-1", ["10", "20"])

        assert result["10"]["in_collection"] is True
        assert result["10"]["in_wantlist"] is False
        assert result["20"]["in_collection"] is False
        assert result["20"]["in_wantlist"] is True


class TestJwtVerification:
    """Tests for api.auth.decode_token."""

    def test_valid_token_returns_payload(self) -> None:
        import base64
        import hashlib
        import hmac
        import json

        from api.auth import decode_token

        secret = "test-secret"

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body_data = {"sub": "user-123", "exp": 9999999999}
        body = b64url(json.dumps(body_data, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"

        payload = decode_token(token, secret)
        assert payload["sub"] == "user-123"

    def test_wrong_secret_raises(self) -> None:
        import base64
        import hashlib
        import hmac
        import json

        import pytest

        from api.auth import decode_token

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256"}, separators=(",", ":")).encode())
        body = b64url(json.dumps({"sub": "x"}, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(b"correct-secret", signing_input, hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"

        with pytest.raises(ValueError):
            decode_token(token, "wrong-secret")

    def test_malformed_token_raises(self) -> None:
        import pytest

        from api.auth import decode_token

        with pytest.raises(ValueError):
            decode_token("not.a.valid.jwt.parts", "secret")
        with pytest.raises(ValueError):
            decode_token("only.two", "secret")

    def test_expired_token_raises(self) -> None:
        import base64
        import hashlib
        import hmac
        import json

        import pytest

        from api.auth import decode_token

        secret = "test-secret"

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256"}, separators=(",", ":")).encode())
        # exp = 1 (epoch 1970-01-01 00:00:01 UTC, long expired)
        body = b64url(json.dumps({"sub": "user", "exp": 1}, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"

        with pytest.raises(ValueError):
            decode_token(token, secret)


class TestB64UrlDecode:
    """Tests for api.auth.b64url_decode."""

    def test_decode_with_padding_needed(self) -> None:
        from api.auth import b64url_decode

        # base64url of b"a" without padding is "YQ"
        result = b64url_decode("YQ")
        assert result == b"a"

    def test_decode_already_aligned(self) -> None:
        from api.auth import b64url_decode

        # "AAAA" decodes to 3 zero bytes
        result = b64url_decode("AAAA")
        assert result == b"\x00\x00\x00"

    def test_roundtrip_with_urlsafe_chars(self) -> None:
        import base64

        from api.auth import b64url_decode

        original = b"hello world!"
        encoded = base64.urlsafe_b64encode(original).rstrip(b"=").decode("ascii")
        assert b64url_decode(encoded) == original


def _make_driver_with_rows(rows: list[dict[str, Any]], count_record: dict[str, Any] | None = None) -> MagicMock:
    """Build a mock driver that returns rows from async iteration and count from single()."""
    driver = MagicMock()
    mock_session = AsyncMock()
    mock_result = AsyncMock()

    async def _aiter(_self: Any) -> Any:
        for row in rows:
            yield row

    mock_result.__aiter__ = _aiter
    mock_result.single = AsyncMock(return_value=count_record)

    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock(return_value=mock_result)

    driver.session = AsyncMock(return_value=mock_session)
    return driver


class TestGetUserCollection:
    """Tests for get_user_collection."""

    @pytest.mark.asyncio
    async def test_returns_results_and_total(self) -> None:
        rows = [
            {
                "id": "r1",
                "title": "Test Album",
                "year": 2020,
                "artist": "Test Artist",
                "label": "Test Label",
                "rating": 4,
                "date_added": "2023-01-01",
                "folder_id": 1,
            }
        ]
        driver = _make_driver_with_rows(rows, count_record={"total": 1})

        results, total = await get_user_collection(driver, "user-1", limit=50, offset=0)

        assert len(results) == 1
        assert total == 1
        assert results[0]["title"] == "Test Album"

    @pytest.mark.asyncio
    async def test_empty_collection(self) -> None:
        driver = _make_driver_with_rows([], count_record={"total": 0})

        results, total = await get_user_collection(driver, "user-1")

        assert results == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_count_record_none_returns_zero(self) -> None:
        driver = _make_driver_with_rows([], count_record=None)

        _results, total = await get_user_collection(driver, "user-1")

        assert total == 0


class TestGetUserWantlist:
    """Tests for get_user_wantlist."""

    @pytest.mark.asyncio
    async def test_returns_results_and_total(self) -> None:
        rows = [
            {
                "id": "r2",
                "title": "Wanted Album",
                "year": 2018,
                "artist": "Some Artist",
                "label": None,
                "rating": 0,
                "date_added": "2022-06-01",
            }
        ]
        driver = _make_driver_with_rows(rows, count_record={"total": 1})

        results, total = await get_user_wantlist(driver, "user-1", limit=50, offset=0)

        assert len(results) == 1
        assert total == 1
        assert results[0]["title"] == "Wanted Album"

    @pytest.mark.asyncio
    async def test_empty_wantlist(self) -> None:
        driver = _make_driver_with_rows([], count_record={"total": 0})

        results, total = await get_user_wantlist(driver, "user-1")

        assert results == []
        assert total == 0


class TestGetUserRecommendations:
    """Tests for get_user_recommendations."""

    @pytest.mark.asyncio
    async def test_returns_recommendations(self) -> None:
        rows = [
            {
                "id": "rec1",
                "title": "Recommended Album",
                "year": 2021,
                "artist": "Great Artist",
                "label": "Great Label",
                "genres": ["Rock"],
                "score": 5,
            }
        ]
        driver = _make_driver_with_rows(rows)

        results = await get_user_recommendations(driver, "user-1", limit=20)

        assert len(results) == 1
        assert results[0]["title"] == "Recommended Album"

    @pytest.mark.asyncio
    async def test_empty_recommendations(self) -> None:
        driver = _make_driver_with_rows([])

        results = await get_user_recommendations(driver, "user-1")

        assert results == []


class TestGetUserCollectionStats:
    """Tests for get_user_collection_stats."""

    @pytest.mark.asyncio
    async def test_returns_stats_structure(self) -> None:
        genre_rows = [{"name": "Rock", "count": 20}, {"name": "Jazz", "count": 5}]
        decade_rows = [{"decade": 1990, "count": 10}, {"decade": 2000, "count": 15}]
        label_rows = [{"name": "Warp", "count": 8}]
        count_record = {"total": 25}

        # Create driver that returns different rows for each query
        driver = MagicMock()
        mock_session = AsyncMock()

        # Track which query is being run
        call_count = [0]

        async def mock_run(_cypher: str, _params: dict[str, Any]) -> Any:
            call_count[0] += 1
            result = AsyncMock()

            # Determine which query based on call order:
            # 1=genre, 2=decade, 3=label, 4=total
            if call_count[0] == 1:  # genre
                rows = genre_rows
            elif call_count[0] == 2:  # decade
                rows = decade_rows
            elif call_count[0] == 3:  # label
                rows = label_rows
            else:  # total count
                rows = []
                result.single = AsyncMock(return_value=count_record)

            async def _aiter(_self: Any) -> Any:
                for row in rows:
                    yield row

            result.__aiter__ = _aiter
            if call_count[0] != 4:
                result.single = AsyncMock(return_value=None)
            return result

        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.run = mock_run

        driver.session = AsyncMock(return_value=mock_session)

        stats = await get_user_collection_stats(driver, "user-1")

        assert "total" in stats
        assert "by_genre" in stats
        assert "by_decade" in stats
        assert "by_label" in stats

    @pytest.mark.asyncio
    async def test_empty_stats(self) -> None:
        driver = _make_driver_with_rows([], count_record={"total": 0})

        stats = await get_user_collection_stats(driver, "user-1")

        assert stats["total"] == 0
        assert stats["by_genre"] == []
        assert stats["by_decade"] == []
        assert stats["by_label"] == []


class TestUserEndpointsInExplore:
    """Tests for explore user HTTP endpoints."""

    def test_collection_requires_auth(self, test_client: Any) -> None:
        response = test_client.get("/api/user/collection")
        assert response.status_code in (401, 403, 503)

    def test_wantlist_requires_auth(self, test_client: Any) -> None:
        response = test_client.get("/api/user/wantlist")
        assert response.status_code in (401, 403, 503)

    def test_recommendations_requires_auth(self, test_client: Any) -> None:
        response = test_client.get("/api/user/recommendations")
        assert response.status_code in (401, 403, 503)

    def test_collection_stats_requires_auth(self, test_client: Any) -> None:
        response = test_client.get("/api/user/collection/stats")
        assert response.status_code in (401, 403, 503)

    def test_user_status_no_auth_returns_false_flags(self, test_client: Any) -> None:
        response = test_client.get("/api/user/status?ids=123,456")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        # Without auth, all flags should be False
        for _rid, flags in data["status"].items():
            assert flags["in_collection"] is False
            assert flags["in_wantlist"] is False

    def test_user_status_empty_ids(self, test_client: Any) -> None:
        response = test_client.get("/api/user/status?ids=,,,")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == {}

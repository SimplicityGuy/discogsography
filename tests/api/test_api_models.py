"""Tests for API service Pydantic models."""

from pydantic import ValidationError
import pytest

from api.models import LoginRequest, LoginResponse, RegisterRequest


class TestRegisterRequest:
    """Tests for RegisterRequest model."""

    def test_valid_registration(self) -> None:
        """Test valid registration data."""
        req = RegisterRequest(email="test@example.com", password="securepassword")  # noqa: S106
        assert req.email == "test@example.com"
        assert req.password == "securepassword"

    def test_invalid_email(self) -> None:
        """Test that invalid email raises ValidationError."""
        with pytest.raises(ValidationError):
            RegisterRequest(email="not-an-email", password="securepassword")  # noqa: S106

    def test_short_password(self) -> None:
        """Test that short password raises ValidationError (< 8 chars)."""
        with pytest.raises(ValidationError):
            RegisterRequest(email="test@example.com", password="short")  # noqa: S106

    def test_minimum_password_length(self) -> None:
        """Test that 8-character password is accepted."""
        req = RegisterRequest(email="test@example.com", password="12345678")  # noqa: S106
        assert req.password == "12345678"

    def test_email_normalization(self) -> None:
        """Test that email is normalized to lowercase."""
        req = RegisterRequest(email="Test@Example.COM", password="securepassword")  # noqa: S106
        assert req.email == "test@example.com"


class TestLoginRequest:
    """Tests for LoginRequest model."""

    def test_valid_login(self) -> None:
        """Test valid login data."""
        req = LoginRequest(email="test@example.com", password="mypassword")  # noqa: S106
        assert req.email == "test@example.com"
        assert req.password == "mypassword"

    def test_email_normalization(self) -> None:
        """Test that login email is normalized to lowercase."""
        req = LoginRequest(email="USER@EXAMPLE.COM", password="password")  # noqa: S106
        assert req.email == "user@example.com"

    def test_empty_password_accepted(self) -> None:
        """LoginRequest allows empty password (validation is in auth logic)."""
        req = LoginRequest(email="test@example.com", password="")
        assert req.password == ""


class TestLoginResponse:
    """Tests for LoginResponse model."""

    def test_valid_response(self) -> None:
        """Test valid login response."""
        resp = LoginResponse(access_token="token123", expires_in=3600)  # noqa: S106
        assert resp.access_token == "token123"
        assert resp.token_type == "bearer"
        assert resp.expires_in == 3600

    def test_default_token_type(self) -> None:
        """Test that token_type defaults to 'bearer'."""
        resp = LoginResponse(access_token="t", expires_in=1800)  # noqa: S106
        assert resp.token_type == "bearer"


class TestTasteModels:
    """Tests for taste fingerprint Pydantic models."""

    def test_heatmap_cell_valid(self) -> None:
        from api.models import HeatmapCell

        cell = HeatmapCell(genre="Rock", decade=1990, count=42)
        assert cell.genre == "Rock"
        assert cell.decade == 1990
        assert cell.count == 42

    def test_heatmap_response_valid(self) -> None:
        from api.models import HeatmapCell, HeatmapResponse

        resp = HeatmapResponse(
            genres=["Rock", "Jazz"],
            decades=[1990, 2000],
            cells=[HeatmapCell(genre="Rock", decade=1990, count=5)],
            total=5,
        )
        assert len(resp.genres) == 2
        assert len(resp.cells) == 1

    def test_obscurity_score_valid(self) -> None:
        from api.models import ObscurityScore

        score = ObscurityScore(
            overall=0.73,
            most_obscure=[{"release_id": "r1", "title": "Rare LP", "score": 0.99}],
            most_mainstream=[{"release_id": "r2", "title": "Best Of", "score": 0.05}],
        )
        assert 0.0 <= score.overall <= 1.0

    def test_taste_drift_year_valid(self) -> None:
        from api.models import TasteDriftYear

        year = TasteDriftYear(year=2023, genres={"Rock": 5, "Jazz": 3})
        assert year.genres["Rock"] == 5

    def test_blind_spot_valid(self) -> None:
        from api.models import BlindSpot

        spot = BlindSpot(
            genre="Reggae",
            decade=1970,
            reason="You collect 12 Dub releases but zero Reggae from the 1970s",
            score=0.85,
        )
        assert spot.score == 0.85

    def test_fingerprint_response_valid(self) -> None:
        from api.models import FingerprintResponse, HeatmapCell, ObscurityScore, TasteDriftYear

        fp = FingerprintResponse(
            total_items=50,
            heatmap_genres=["Rock"],
            heatmap_decades=[1990],
            heatmap_cells=[HeatmapCell(genre="Rock", decade=1990, count=50)],
            obscurity=ObscurityScore(overall=0.5, most_obscure=[], most_mainstream=[]),
            taste_drift=[TasteDriftYear(year=2023, genres={"Rock": 50})],
            top_labels=[{"name": "Warp", "count": 10}],
            peak_decade=1990,
        )
        assert fp.total_items == 50

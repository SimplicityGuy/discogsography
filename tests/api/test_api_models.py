"""Tests for API service Pydantic models."""

from pydantic import ValidationError
import pytest

from api.models import LoginRequest, LoginResponse, PathNode, PathResponse, RegisterRequest


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


class TestPathModels:
    def test_path_node_required_fields(self) -> None:
        node = PathNode(id="1", name="Miles Davis", type="artist")
        assert node.id == "1"
        assert node.name == "Miles Davis"
        assert node.type == "artist"
        assert node.rel is None

    def test_path_node_with_rel(self) -> None:
        node = PathNode(id="201", name="Kind of Blue", type="release", rel="BY")
        assert node.rel == "BY"

    def test_path_response_found(self) -> None:
        nodes = [
            PathNode(id="1", name="Miles Davis", type="artist"),
            PathNode(id="2", name="Daft Punk", type="artist", rel="BY"),
        ]
        resp = PathResponse(found=True, length=1, path=nodes)
        assert resp.found is True
        assert resp.length == 1
        assert len(resp.path) == 2

    def test_path_response_not_found(self) -> None:
        resp = PathResponse(found=False, length=None, path=[])
        assert resp.found is False
        assert resp.length is None
        assert resp.path == []


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
            cells=[
                HeatmapCell(genre="Rock", decade=1990, count=5),
                HeatmapCell(genre="Jazz", decade=2000, count=3),
            ],
            total=8,
        )
        assert len(resp.cells) == 2
        assert resp.total == 8

    def test_obscurity_score_valid(self) -> None:
        from api.models import ObscurityScore

        score = ObscurityScore(
            score=0.73,
            median_collectors=150.0,
            total_releases=42,
        )
        assert 0.0 <= score.score <= 1.0
        assert score.median_collectors == 150.0
        assert score.total_releases == 42

    def test_taste_drift_year_valid(self) -> None:
        from api.models import TasteDriftYear

        drift = TasteDriftYear(year="2023", top_genre="Rock", count=5)
        assert drift.top_genre == "Rock"
        assert drift.count == 5

    def test_blind_spot_valid(self) -> None:
        from api.models import BlindSpot

        spot = BlindSpot(
            genre="Reggae",
            artist_overlap=12,
            example_release="King Tubby Meets Rockers Uptown",
        )
        assert spot.genre == "Reggae"
        assert spot.artist_overlap == 12
        assert spot.example_release == "King Tubby Meets Rockers Uptown"

    def test_fingerprint_response_valid(self) -> None:
        from api.models import FingerprintResponse, HeatmapCell, ObscurityScore, TasteDriftYear

        fp = FingerprintResponse(
            heatmap=[HeatmapCell(genre="Rock", decade=1990, count=50)],
            obscurity=ObscurityScore(score=0.5, median_collectors=200.0, total_releases=50),
            drift=[TasteDriftYear(year="2023", top_genre="Rock", count=50)],
            blind_spots=[],
            peak_decade=1990,
        )
        assert fp.peak_decade == 1990
        assert len(fp.heatmap) == 1
        assert fp.obscurity.score == 0.5


# --- Admin Phase 2 Models ---


class TestAdminUserStatsModels:
    """Tests for user stats response models."""

    def test_daily_registration(self):
        from api.models import DailyRegistration

        obj = DailyRegistration(date="2026-03-18", count=5)
        assert obj.date == "2026-03-18"
        assert obj.count == 5

    def test_weekly_registration(self):
        from api.models import WeeklyRegistration

        obj = WeeklyRegistration(week_start="2026-03-17", count=12)
        assert obj.week_start == "2026-03-17"
        assert obj.count == 12

    def test_monthly_registration(self):
        from api.models import MonthlyRegistration

        obj = MonthlyRegistration(month="2026-03", count=34)
        assert obj.month == "2026-03"
        assert obj.count == 34

    def test_registration_time_series(self):
        from api.models import RegistrationTimeSeries

        obj = RegistrationTimeSeries(daily=[], weekly=[], monthly=[])
        assert obj.daily == []

    def test_user_stats_response(self):
        from api.models import UserStatsResponse

        obj = UserStatsResponse(
            total_users=150,
            active_7d=42,
            active_30d=89,
            oauth_connection_rate=0.63,
            registrations={"daily": [], "weekly": [], "monthly": []},
        )
        assert obj.total_users == 150
        assert obj.oauth_connection_rate == 0.63


class TestSyncActivityModels:
    """Tests for sync activity response models."""

    def test_sync_period_stats(self):
        from api.models import SyncPeriodStats

        obj = SyncPeriodStats(
            total_syncs=28,
            syncs_per_day=4.0,
            avg_items_synced=142.5,
            failure_rate=0.07,
            total_failures=2,
        )
        assert obj.syncs_per_day == 4.0

    def test_sync_activity_response(self):
        from api.models import SyncActivityResponse, SyncPeriodStats

        period = SyncPeriodStats(
            total_syncs=0,
            syncs_per_day=0.0,
            avg_items_synced=0.0,
            failure_rate=0.0,
            total_failures=0,
        )
        obj = SyncActivityResponse(period_7d=period, period_30d=period)
        assert obj.period_7d.total_syncs == 0


class TestStorageModels:
    """Tests for storage utilization response models."""

    def test_storage_source_ok(self):
        from api.models import Neo4jStorage

        obj = Neo4jStorage(status="ok", nodes=[], relationships=[], store_sizes=None)
        assert obj.status == "ok"

    def test_storage_source_error(self):
        from api.models import StorageSourceError

        obj = StorageSourceError(status="error", error="connection failed")
        assert obj.status == "error"

    def test_storage_response(self):
        from api.models import StorageResponse, StorageSourceError

        err = StorageSourceError(status="error", error="down")
        obj = StorageResponse(neo4j=err.model_dump(), postgresql=err.model_dump(), redis=err.model_dump())
        assert obj.neo4j["status"] == "error"

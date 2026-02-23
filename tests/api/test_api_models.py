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

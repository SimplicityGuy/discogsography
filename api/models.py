"""Pydantic models for the API service."""

from datetime import datetime
import re
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    """User registration request."""

    email: str
    password: str = Field(min_length=8, description="Password (minimum 8 characters)")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Validate and normalize email address."""
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address")
        return v


class LoginRequest(BaseModel):
    """User login request."""

    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalize email address to lowercase."""
        return v.strip().lower()


class LoginResponse(BaseModel):
    """User login response with JWT access token."""

    access_token: str
    token_type: str = "bearer"  # noqa: S105  # nosec B105
    expires_in: int  # seconds until expiration


class UserResponse(BaseModel):
    """User information response."""

    id: UUID
    email: str
    is_active: bool
    created_at: datetime


class SnapshotNode(BaseModel):
    """A single node in a graph snapshot."""

    id: str
    type: str


class SnapshotRequest(BaseModel):
    """Request body for saving a graph snapshot."""

    nodes: list[SnapshotNode]
    center: SnapshotNode

    @field_validator("nodes")
    @classmethod
    def nodes_not_empty(cls, v: list[SnapshotNode]) -> list[SnapshotNode]:
        if not v:
            raise ValueError("nodes must not be empty")
        return v


class SnapshotResponse(BaseModel):
    """Response after saving a snapshot."""

    token: str
    url: str
    expires_at: str


class SnapshotRestoreResponse(BaseModel):
    """Response when restoring a snapshot."""

    nodes: list[SnapshotNode]
    center: SnapshotNode
    created_at: str

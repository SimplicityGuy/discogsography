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


class PathNode(BaseModel):
    """A single node in a shortest-path result."""

    id: str
    name: str
    type: str
    rel: str | None = None  # relationship type leading TO this node (None for start node)


class PathResponse(BaseModel):
    """Response for GET /api/path."""

    found: bool
    length: int | None
    path: list[PathNode]


# --- Label DNA models ---


class GenreWeight(BaseModel):
    """A genre with its share of a label's catalog."""

    name: str
    count: int
    percentage: float


class StyleWeight(BaseModel):
    """A style with its share of a label's catalog."""

    name: str
    count: int
    percentage: float


class FormatWeight(BaseModel):
    """A physical/digital format with its share of a label's catalog."""

    name: str
    count: int
    percentage: float


class DecadeCount(BaseModel):
    """Release count for a single decade."""

    decade: int
    count: int
    percentage: float


class LabelDNA(BaseModel):
    """Full fingerprint for a record label."""

    label_id: str
    label_name: str
    release_count: int
    artist_count: int
    artist_diversity: float  # unique artists / releases (0-1 scale, higher = more diverse)
    active_years: list[int]  # sorted list of years with releases
    peak_decade: int | None  # decade with most releases
    prolificacy: float  # releases per active year
    genres: list[GenreWeight]
    styles: list[StyleWeight]
    formats: list[FormatWeight]
    decades: list[DecadeCount]


class SimilarLabel(BaseModel):
    """A label with its similarity score to a target label."""

    label_id: str
    label_name: str
    similarity: float  # cosine similarity 0-1
    release_count: int
    shared_genres: list[str]


class SimilarLabelsResponse(BaseModel):
    """Response for GET /api/label/{label_id}/similar."""

    label_id: str
    label_name: str
    similar: list[SimilarLabel]


class LabelCompareEntry(BaseModel):
    """One label's DNA in a side-by-side comparison."""

    dna: LabelDNA


class LabelCompareResponse(BaseModel):
    """Response for GET /api/label/dna/compare."""

    labels: list[LabelCompareEntry]

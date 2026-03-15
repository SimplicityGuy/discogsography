"""Pydantic models for the API service."""

from datetime import datetime
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


# ---------------------------------------------------------------------------
# Taste Fingerprint models
# ---------------------------------------------------------------------------


class HeatmapCell(BaseModel):
    """Single cell in a genre x decade heatmap."""

    genre: str
    decade: int
    count: int


class HeatmapResponse(BaseModel):
    """Genre x decade heatmap for a user's collection."""

    cells: list[HeatmapCell]
    total: int


class ObscurityScore(BaseModel):
    """How obscure a user's collection is (0 = mainstream, 1 = maximally obscure)."""

    score: float = Field(ge=0.0, le=1.0)
    median_collectors: float
    total_releases: int


class TasteDriftYear(BaseModel):
    """Top genre for a single year of additions."""

    year: str
    top_genre: str
    count: int


class BlindSpot(BaseModel):
    """A genre the user's favourite artists release in but the user hasn't collected."""

    genre: str
    artist_overlap: int
    example_release: str | None = None


class FingerprintResponse(BaseModel):
    """Full taste fingerprint combining all sub-queries."""

    heatmap: list[HeatmapCell]
    obscurity: ObscurityScore
    drift: list[TasteDriftYear]
    blind_spots: list[BlindSpot]
    peak_decade: int | None = None


# ---------------------------------------------------------------------------
# Recommender models
# ---------------------------------------------------------------------------


class SimilarArtist(BaseModel):
    """An artist with its similarity score to a target artist."""

    artist_id: str
    artist_name: str
    similarity: float  # weighted cosine similarity 0-1
    breakdown: dict[str, float]  # per-dimension scores: genre, style, label, collaborator
    release_count: int
    shared_genres: list[str]
    shared_labels: list[str]


class SimilarArtistsResponse(BaseModel):
    """Response for GET /api/recommend/similar/artist/{artist_id}."""

    artist_id: str
    artist_name: str
    similar: list[SimilarArtist]


class EntityRef(BaseModel):
    """Reference to a graph entity (artist, label, genre, style)."""

    id: str
    name: str
    type: str


class DiscoveryNode(BaseModel):
    """A discovered node from personalized graph traversal."""

    id: str
    name: str
    type: str
    score: float
    path: list[str]
    reason: str


class ExploreFromHereResponse(BaseModel):
    """Response for GET /api/recommend/explore/{entity_type}/{entity_id}."""

    model_config = ConfigDict(populate_by_name=True)

    from_entity: EntityRef = Field(alias="from")
    discoveries: list[DiscoveryNode]


class EnhancedRecommendation(BaseModel):
    """A release recommendation with multi-signal scoring."""

    id: str
    title: str | None = None
    artist: str | None = None
    label: str | None = None
    year: int | None = None
    genres: list[str] = Field(default_factory=list)
    score: float
    reasons: list[str] = Field(default_factory=list)


class EnhancedRecommendationsResponse(BaseModel):
    """Response for GET /api/user/recommendations?strategy=multi."""

    recommendations: list[EnhancedRecommendation]
    total: int
    strategy: str = "multi"

"""Pydantic models for the API service."""

from datetime import datetime
import re
from typing import Any
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


# --- Admin Models ---


class AdminLoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105  # nosec B105
    expires_in: int


class ExtractionHistoryResponse(BaseModel):
    id: UUID
    triggered_by: UUID
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None = None
    record_counts: dict[str, int] | None
    error_message: str | None
    extractor_version: str | None
    created_at: datetime


class ExtractionListResponse(BaseModel):
    extractions: list[ExtractionHistoryResponse]
    total: int
    offset: int
    limit: int


class ExtractionTriggerResponse(BaseModel):
    id: UUID
    status: str


class DlqPurgeResponse(BaseModel):
    queue: str
    messages_purged: int


# --- Admin Phase 2 Response Models ---


class DailyRegistration(BaseModel):
    """User registration counts per day."""

    date: str
    count: int


class WeeklyRegistration(BaseModel):
    """User registration counts per week."""

    week_start: str
    count: int


class MonthlyRegistration(BaseModel):
    """User registration counts per month."""

    month: str
    count: int


class RegistrationTimeSeries(BaseModel):
    """Time series of user registrations at multiple granularities."""

    daily: list[DailyRegistration]
    weekly: list[WeeklyRegistration]
    monthly: list[MonthlyRegistration]


class UserStatsResponse(BaseModel):
    """Response model for admin user statistics endpoint."""

    total_users: int
    active_7d: int
    active_30d: int
    oauth_connection_rate: float
    registrations: dict[str, Any]


class SyncPeriodStats(BaseModel):
    """Sync activity statistics for a time period."""

    total_syncs: int
    syncs_per_day: float
    avg_items_synced: float
    failure_rate: float
    total_failures: int


class SyncActivityResponse(BaseModel):
    """Response model for admin sync activity endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    period_7d: SyncPeriodStats
    period_30d: SyncPeriodStats


class NodeCount(BaseModel):
    """Neo4j node label with count."""

    label: str
    count: int


class RelationshipCount(BaseModel):
    """Neo4j relationship type with count."""

    type: str
    count: int


class StoreSizes(BaseModel):
    """Neo4j store size breakdown."""

    total: str
    nodes: str
    relationships: str
    strings: str


class Neo4jStorage(BaseModel):
    """Neo4j storage utilization details."""

    status: str
    nodes: list[NodeCount]
    relationships: list[RelationshipCount]
    store_sizes: StoreSizes | None


class TableSize(BaseModel):
    """PostgreSQL table size details."""

    name: str
    row_count: int
    size: str
    index_size: str


class PostgresStorage(BaseModel):
    """PostgreSQL storage utilization details."""

    status: str
    tables: list[TableSize]
    total_size: str


class RedisKeyPrefix(BaseModel):
    """Redis key prefix with count."""

    prefix: str
    count: int


class RedisStorage(BaseModel):
    """Redis storage utilization details."""

    status: str
    memory_used: str
    memory_peak: str
    total_keys: int
    keys_by_prefix: list[RedisKeyPrefix]


class StorageSourceError(BaseModel):
    """Error response for a storage source that could not be queried."""

    status: str = "error"
    error: str


class StorageResponse(BaseModel):
    """Response model for admin storage utilization endpoint."""

    neo4j: dict[str, Any]
    postgresql: dict[str, Any]
    redis: dict[str, Any]


class RaritySignal(BaseModel):
    """A single rarity signal score and its weight."""

    score: float
    weight: float


class RarityResponse(BaseModel):
    """Full rarity breakdown for a single release."""

    release_id: int
    title: str
    artist: str
    year: int | None
    rarity_score: float
    tier: str
    hidden_gem_score: float | None
    breakdown: dict[str, RaritySignal]


class RarityListItem(BaseModel):
    """A release in a rarity list (leaderboard, artist, label)."""

    release_id: int
    title: str
    artist: str
    year: int | None
    rarity_score: float
    tier: str
    hidden_gem_score: float | None = None


class RarityListResponse(BaseModel):
    """Paginated list of rarity-scored releases."""

    items: list[RarityListItem]
    total: int
    page: int
    page_size: int


# --- Metrics History models (Phase 3) ---


class QueueHistoryResponse(BaseModel):
    """Response for GET /api/admin/queues/history."""

    model_config = ConfigDict(extra="forbid")

    range: str
    granularity: str
    queues: dict[str, Any]
    dlq_summary: dict[str, Any]


class HealthHistoryResponse(BaseModel):
    """Response for GET /api/admin/health/history."""

    model_config = ConfigDict(extra="forbid")

    range: str
    granularity: str
    services: dict[str, Any]
    api_endpoints: dict[str, Any]

"""Pydantic response models for the insights service."""

from datetime import datetime

from pydantic import BaseModel


class ArtistCentralityItem(BaseModel):
    """A single artist's centrality ranking."""

    rank: int
    artist_id: str
    artist_name: str
    edge_count: int


class GenreTrendItem(BaseModel):
    """Release count for a genre in a specific decade."""

    decade: int
    release_count: int


class GenreTrendsResponse(BaseModel):
    """Genre trend data across decades."""

    genre: str
    trends: list[GenreTrendItem]
    peak_decade: int | None = None


class LabelLongevityItem(BaseModel):
    """A label's longevity ranking."""

    rank: int
    label_id: str
    label_name: str
    first_year: int
    last_year: int | None
    years_active: int
    total_releases: int
    peak_decade: int | None = None
    still_active: bool = False


class AnniversaryItem(BaseModel):
    """A release with a notable anniversary this month."""

    master_id: str
    title: str
    artist_name: str | None = None
    release_year: int
    anniversary: int


class DataCompletenessItem(BaseModel):
    """Data completeness metrics for an entity type."""

    entity_type: str
    total_count: int
    with_image: int = 0
    with_year: int = 0
    with_country: int = 0
    with_genre: int = 0
    completeness_pct: float = 0.0


class ComputationStatus(BaseModel):
    """Status of a specific insight computation."""

    insight_type: str
    last_computed: datetime | None = None
    status: str
    duration_ms: int | None = None

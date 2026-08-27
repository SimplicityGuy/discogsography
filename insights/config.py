"""Analytics engine configuration owned by the insights service."""

from dataclasses import dataclass, field
from os import getenv
from typing import cast

from common.config import _build_postgres_connstr, _build_redis_url, get_secret, resolve_postgres_pool_sizes


@dataclass(frozen=True)
class InsightsConfig:
    """Configuration for scheduled analytics computation."""

    api_base_url: str
    postgres_host: str
    postgres_username: str
    postgres_password: str = field(repr=False)
    postgres_database: str
    postgres_pool_min_size: int = 1
    postgres_pool_max_size: int = 4
    redis_host: str = "redis://localhost:6379/0"
    schedule_hours: int = 24
    milestone_years: tuple[int, ...] = (25, 30, 40, 50, 75, 100)
    internal_secret: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> "InsightsConfig":
        """Create configuration from environment variables."""
        postgres_username = get_secret("POSTGRES_USERNAME")
        postgres_password = get_secret("POSTGRES_PASSWORD")
        postgres_database = getenv("POSTGRES_DATABASE")
        missing_vars = [
            name
            for name, value in (
                ("POSTGRES_HOST", getenv("POSTGRES_HOST")),
                ("POSTGRES_USERNAME", postgres_username),
                ("POSTGRES_PASSWORD", postgres_password),
                ("POSTGRES_DATABASE", postgres_database),
            )
            if not value
        ]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        try:
            schedule_hours = int(getenv("INSIGHTS_SCHEDULE_HOURS", "24"))
            schedule_hours = schedule_hours if schedule_hours >= 1 else 24
        except ValueError:
            schedule_hours = 24
        try:
            parsed = sorted({int(year.strip()) for year in getenv("INSIGHTS_MILESTONE_YEARS", "25,30,40,50,75,100").split(",") if year.strip()})
            milestone_years = tuple(parsed) if parsed else (25, 30, 40, 50, 75, 100)
        except ValueError:
            milestone_years = (25, 30, 40, 50, 75, 100)
        pool_min, pool_max = resolve_postgres_pool_sizes(default_min=1, default_max=4)
        return cls(
            api_base_url=getenv("API_BASE_URL", "http://api:8004"),
            postgres_host=_build_postgres_connstr(),
            postgres_username=cast("str", postgres_username),
            postgres_password=cast("str", postgres_password),
            postgres_database=cast("str", postgres_database),
            postgres_pool_min_size=pool_min,
            postgres_pool_max_size=pool_max,
            redis_host=_build_redis_url(),
            schedule_hours=schedule_hours,
            milestone_years=milestone_years,
            internal_secret=get_secret("INSIGHTS_INTERNAL_SECRET") or None,
        )

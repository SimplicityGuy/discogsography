"""Catalog API configuration owned by the API service."""

from dataclasses import dataclass, field
from os import getenv
from typing import cast

from common.config import (
    _build_neo4j_uri,
    _build_postgres_connstr,
    _build_redis_url,
    _coerce_port,
    get_secret,
    resolve_postgres_pool_sizes,
)


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable with a stable fallback."""
    try:
        return int(getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class ApiConfig:
    """Configuration for the catalog API."""

    postgres_host: str
    postgres_username: str
    postgres_password: str = field(repr=False)
    postgres_database: str
    jwt_secret_key: str = field(repr=False)
    neo4j_host: str
    neo4j_username: str
    neo4j_password: str = field(repr=False)
    postgres_pool_min_size: int = 2
    postgres_pool_max_size: int = 8
    redis_host: str = "redis://redis:6379/0"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 30
    discogs_user_agent: str = "discogsography/1.0 +https://github.com/SimplicityGuy/discogsography"
    discogs_oauth_callback_url: str | None = None
    app_base_url: str = "http://localhost:8006"
    cors_origins: list[str] | None = None
    snapshot_ttl_days: int = 28
    snapshot_max_nodes: int = 100
    encryption_master_key: str | None = field(default=None, repr=False)
    insights_internal_secret: str | None = field(default=None, repr=False)
    resend_api_key: str | None = field(default=None, repr=False)
    resend_sender_email: str = "noreply@discogsography.com"
    resend_sender_name: str = "Discogsography"
    extractor_host: str = "extractor-discogs"
    extractor_health_port: int = 8000
    rabbitmq_management_host: str = "rabbitmq"
    rabbitmq_management_port: int = 15672
    rabbitmq_username: str = "discogsography"
    rabbitmq_password: str = field(default="discogsography", repr=False)
    metrics_retention_days: int = 366
    metrics_collection_interval: int = 300

    @classmethod
    def from_env(cls) -> "ApiConfig":
        """Create configuration from environment variables."""
        postgres_username = get_secret("POSTGRES_USERNAME")
        postgres_password = get_secret("POSTGRES_PASSWORD")
        postgres_database = getenv("POSTGRES_DATABASE")
        jwt_secret_key = get_secret("JWT_SECRET_KEY")
        neo4j_username = get_secret("NEO4J_USERNAME")
        neo4j_password = get_secret("NEO4J_PASSWORD")
        missing_vars = [
            name
            for name, value in (
                ("POSTGRES_HOST", getenv("POSTGRES_HOST")),
                ("POSTGRES_USERNAME", postgres_username),
                ("POSTGRES_PASSWORD", postgres_password),
                ("POSTGRES_DATABASE", postgres_database),
                ("JWT_SECRET_KEY", jwt_secret_key),
                ("NEO4J_HOST", getenv("NEO4J_HOST")),
                ("NEO4J_USERNAME", neo4j_username),
                ("NEO4J_PASSWORD", neo4j_password),
            )
            if not value
        ]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        jwt_algorithm = getenv("JWT_ALGORITHM", "HS256")
        if jwt_algorithm != "HS256":
            raise ValueError(f"Unsupported JWT algorithm: {jwt_algorithm}. Only HS256 is supported.")
        cors_origins_raw = getenv("CORS_ORIGINS")
        cors_origins = [origin.strip() for origin in cors_origins_raw.split(",") if origin.strip()] if cors_origins_raw else None
        pool_min, pool_max = resolve_postgres_pool_sizes(default_min=2, default_max=8)
        return cls(
            postgres_host=_build_postgres_connstr(),
            postgres_username=cast("str", postgres_username),
            postgres_password=cast("str", postgres_password),
            postgres_database=cast("str", postgres_database),
            jwt_secret_key=cast("str", jwt_secret_key),
            neo4j_host=_build_neo4j_uri(),
            neo4j_username=cast("str", neo4j_username),
            neo4j_password=cast("str", neo4j_password),
            postgres_pool_min_size=pool_min,
            postgres_pool_max_size=pool_max,
            redis_host=_build_redis_url(),
            jwt_algorithm=jwt_algorithm,
            jwt_expire_minutes=_env_int("JWT_EXPIRE_MINUTES", 30),
            discogs_user_agent=getenv("DISCOGS_USER_AGENT", "discogsography/1.0 +https://github.com/SimplicityGuy/discogsography"),
            discogs_oauth_callback_url=getenv("DISCOGS_OAUTH_CALLBACK_URL") or None,
            app_base_url=getenv("APP_BASE_URL", "http://localhost:8006").rstrip("/"),
            cors_origins=cors_origins,
            snapshot_ttl_days=_env_int("SNAPSHOT_TTL_DAYS", 28),
            snapshot_max_nodes=_env_int("SNAPSHOT_MAX_NODES", 100),
            encryption_master_key=get_secret("ENCRYPTION_MASTER_KEY") or None,
            insights_internal_secret=get_secret("INSIGHTS_INTERNAL_SECRET") or None,
            resend_api_key=get_secret("RESEND_API_KEY") or None,
            resend_sender_email=getenv("RESEND_SENDER_EMAIL", "noreply@discogsography.com"),
            resend_sender_name=getenv("RESEND_SENDER_NAME", "Discogsography"),
            extractor_host=getenv("EXTRACTOR_HOST", "extractor-discogs"),
            extractor_health_port=_coerce_port(getenv("EXTRACTOR_HEALTH_PORT", "8000"), 8000),
            rabbitmq_management_host=getenv("RABBITMQ_MANAGEMENT_HOST", getenv("RABBITMQ_HOST", "rabbitmq")),
            rabbitmq_management_port=_coerce_port(getenv("RABBITMQ_MANAGEMENT_PORT", "15672"), 15672),
            rabbitmq_username=get_secret("RABBITMQ_USERNAME", "discogsography"),
            rabbitmq_password=get_secret("RABBITMQ_PASSWORD", "discogsography"),
            metrics_retention_days=_env_int("METRICS_RETENTION_DAYS", 366),
            metrics_collection_interval=_env_int("METRICS_COLLECTION_INTERVAL", 300),
        )

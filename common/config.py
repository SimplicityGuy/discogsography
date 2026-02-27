"""Configuration management for discogsography services."""

from dataclasses import dataclass
import logging
from os import getenv
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Any, cast, overload
from urllib.parse import quote as _url_quote
import warnings


if TYPE_CHECKING:
    from collections.abc import Sequence  # pragma: no cover

import orjson
import structlog


logger = structlog.get_logger(__name__)


@overload
def get_secret(env_var: str, default: str) -> str: ...  # pragma: no cover


@overload
def get_secret(env_var: str, default: None = None) -> str | None: ...  # pragma: no cover


def get_secret(env_var: str, default: str | None = None) -> str | None:
    """Read a secret from a _FILE path if set, else fall back to env var.

    Supports Docker Compose runtime secrets via the _FILE convention:
    if <VAR>_FILE is set, reads the secret value from that file path.
    Falls back to the plain <VAR> environment variable otherwise.
    """
    file_path = getenv(f"{env_var}_FILE")
    if file_path:
        try:
            return Path(file_path).read_text().strip()
        except OSError as exc:
            raise ValueError(f"Cannot read secret file for {env_var}: {file_path!r}") from exc
    return getenv(env_var) if default is None else getenv(env_var, default)


def _build_amqp_url() -> str:
    """Build AMQP connection URL from component secrets and environment variables.

    Reads credentials via the standard _FILE secret convention (Docker secrets),
    falling back to plain environment variables, then to defaults.
    """
    user = get_secret("RABBITMQ_USERNAME", "discogsography")
    password = get_secret("RABBITMQ_PASSWORD", "discogsography")
    host = getenv("RABBITMQ_HOST", "rabbitmq")
    port = getenv("RABBITMQ_PORT", "5672")
    return f"amqp://{_url_quote(user, safe='')}:{_url_quote(password, safe='')}@{host}:{port}/%2F"


@dataclass(frozen=True)
class ExtractorConfig:
    """Configuration for the extractor service."""

    amqp_connection: str
    discogs_root: Path
    max_temp_size: int = int(1e9)  # 1000 MB
    periodic_check_days: int = 15  # Default to 15 days

    @classmethod
    def from_env(cls) -> "ExtractorConfig":
        """Create configuration from environment variables."""
        amqp_connection = _build_amqp_url()

        discogs_root = Path(getenv("DISCOGS_ROOT", "/discogs-data"))

        # Parse periodic check interval from environment
        periodic_check_days = 15  # Default
        periodic_check_env = getenv("PERIODIC_CHECK_DAYS")
        if periodic_check_env:
            try:
                periodic_check_days = int(periodic_check_env)
                if periodic_check_days < 1:
                    log = structlog.get_logger()
                    log.warning("⚠️ Invalid PERIODIC_CHECK_DAYS value. Using default of 15 days.", value=periodic_check_env)
                    periodic_check_days = 15
            except ValueError:
                log = structlog.get_logger()
                log.warning("⚠️ Invalid PERIODIC_CHECK_DAYS value. Using default of 15 days.", value=periodic_check_env)
                periodic_check_days = 15

        return cls(
            amqp_connection=amqp_connection,
            discogs_root=discogs_root,
            periodic_check_days=periodic_check_days,
        )


@dataclass(frozen=True)
class GraphinatorConfig:
    """Configuration for the graphinator service."""

    amqp_connection: str
    neo4j_address: str
    neo4j_username: str
    neo4j_password: str

    @classmethod
    def from_env(cls) -> "GraphinatorConfig":
        """Create configuration from environment variables."""
        amqp_connection = _build_amqp_url()
        neo4j_address = getenv("NEO4J_ADDRESS")
        neo4j_username = get_secret("NEO4J_USERNAME")
        neo4j_password = get_secret("NEO4J_PASSWORD")

        missing_vars = []
        if not neo4j_address:
            missing_vars.append("NEO4J_ADDRESS")
        if not neo4j_username:
            missing_vars.append("NEO4J_USERNAME")
        if not neo4j_password:
            missing_vars.append("NEO4J_PASSWORD")

        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        return cls(
            amqp_connection=amqp_connection,
            neo4j_address=cast("str", neo4j_address),
            neo4j_username=cast("str", neo4j_username),
            neo4j_password=cast("str", neo4j_password),
        )


@dataclass(frozen=True)
class TableinatorConfig:
    """Configuration for the tableinator service."""

    amqp_connection: str
    postgres_address: str
    postgres_username: str
    postgres_password: str
    postgres_database: str

    @classmethod
    def from_env(cls) -> "TableinatorConfig":
        """Create configuration from environment variables."""
        amqp_connection = _build_amqp_url()
        postgres_address = getenv("POSTGRES_ADDRESS")
        postgres_username = get_secret("POSTGRES_USERNAME")
        postgres_password = get_secret("POSTGRES_PASSWORD")
        postgres_database = getenv("POSTGRES_DATABASE")

        missing_vars = []
        if not postgres_address:
            missing_vars.append("POSTGRES_ADDRESS")
        if not postgres_username:
            missing_vars.append("POSTGRES_USERNAME")
        if not postgres_password:
            missing_vars.append("POSTGRES_PASSWORD")
        if not postgres_database:
            missing_vars.append("POSTGRES_DATABASE")

        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        return cls(
            amqp_connection=amqp_connection,
            postgres_address=cast("str", postgres_address),
            postgres_username=cast("str", postgres_username),
            postgres_password=cast("str", postgres_password),
            postgres_database=cast("str", postgres_database),
        )


# AMQP Configuration shared across all services
AMQP_EXCHANGE = "discogsography-exchange"
AMQP_EXCHANGE_TYPE = "topic"  # Use topic for routing by data type
AMQP_QUEUE_PREFIX_GRAPHINATOR = "discogsography-graphinator"
AMQP_QUEUE_PREFIX_TABLEINATOR = "discogsography-tableinator"

# Data types that will be processed
DATA_TYPES = ["artists", "labels", "masters", "releases"]


def orjson_serializer(msg: dict[str, Any], **_kwargs: Any) -> str:
    """Custom JSON serializer using orjson for consistency with Rust extractor.

    Handles non-serializable types like exceptions by converting them to strings.
    """

    def default(obj: Any) -> Any:
        """Convert non-serializable objects to strings."""
        if isinstance(obj, Exception):
            return f"{type(obj).__name__}: {obj!s}"
        return str(obj)

    return orjson.dumps(msg, option=orjson.OPT_SORT_KEYS, default=default).decode("utf-8")


def setup_logging(
    service_name: str,
    level: str | None = None,
    log_file: Path | None = None,
) -> None:
    """Set up structured logging configuration with correlation IDs and service context.

    This configures structlog to:
    - Include correlation IDs from contextvars in all log entries
    - Add service-specific context (name, version, environment)
    - Output structured JSON logs to console and optionally to file
    - Support distributed tracing via request IDs

    Args:
        service_name: Name of the service for logging context
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
               If None, reads from LOG_LEVEL environment variable, defaults to INFO.
        log_file: Optional file path for logging output
    """

    # Read from environment variable if level not provided, default to INFO
    if level is None:
        level = getenv("LOG_LEVEL", "INFO").upper()

    # Configure structlog processors
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: Sequence[Any] = [
        # Merge contextvars (correlation IDs, request context) into log entries
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.CallsiteParameterAdder(
            parameters=[structlog.processors.CallsiteParameter.LINENO],
            additional_ignores=["structlog"],
        ),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Bind service-specific context that will be included in all log entries
    structlog.contextvars.bind_contextvars(
        service=service_name,
        environment=getenv("ENVIRONMENT", "development"),
    )

    # Set up standard logging handlers
    handlers: list[logging.Handler] = []

    # Console handler with JSON output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.dict_tracebacks,
                structlog.processors.JSONRenderer(serializer=orjson_serializer),
            ],
        )
    )
    handlers.append(console_handler)

    # File handler if specified
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=shared_processors,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.dict_tracebacks,
                    structlog.processors.JSONRenderer(serializer=orjson_serializer),
                ],
            )
        )
        handlers.append(file_handler)

    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        handlers=handlers,
        force=True,
    )

    # Suppress verbose pika logs
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("pika.adapters").setLevel(logging.WARNING)
    logging.getLogger("pika.adapters.utils.io_services_utils").setLevel(logging.WARNING)
    logging.getLogger("pika.adapters.utils.connection_workflow").setLevel(logging.WARNING)
    logging.getLogger("pika.adapters.blocking_connection").setLevel(logging.WARNING)
    logging.getLogger("pika.connection").setLevel(logging.WARNING)

    # Suppress Neo4j schema warnings (unknown labels/relationships)
    # These warnings appear when database is empty or being populated
    # and don't indicate actual errors in the code
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
    logging.getLogger("neo4j").setLevel(logging.ERROR)  # Suppress all Neo4j warnings, keep errors

    # Suppress Neo4j Python warnings about single record results
    # This is expected behavior when using OPTIONAL MATCH patterns
    warnings.filterwarnings("ignore", message="Expected a result with a single record", category=UserWarning, module="neo4j")

    # Get structured logger
    log = structlog.get_logger()
    log.info("✅ Logging configured for service", service=service_name)


@dataclass(frozen=True)
class DashboardConfig:
    """Configuration for the dashboard service."""

    amqp_connection: str
    neo4j_address: str
    neo4j_username: str
    neo4j_password: str
    postgres_address: str
    postgres_username: str
    postgres_password: str
    postgres_database: str
    rabbitmq_username: str
    rabbitmq_password: str
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] | None = None  # None = default to localhost only
    cache_warming_enabled: bool = True  # Enable cache warming on service startup
    cache_webhook_secret: str | None = None  # Secret for cache invalidation webhooks

    @classmethod
    def from_env(cls) -> "DashboardConfig":
        """Create configuration from environment variables."""
        # Reuse other configs for consistency
        graphinator_config = GraphinatorConfig.from_env()
        tableinator_config = TableinatorConfig.from_env()

        # Redis configuration
        redis_url = getenv("REDIS_URL", "redis://localhost:6379/0")

        # Get RabbitMQ credentials
        rabbitmq_username = get_secret("RABBITMQ_USERNAME", "discogsography")
        rabbitmq_password = get_secret("RABBITMQ_PASSWORD", "discogsography")

        # CORS configuration
        cors_origins_env = getenv("CORS_ORIGINS")
        cors_origins = None
        if cors_origins_env:
            # Parse comma-separated list of origins
            cors_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]

        # Cache warming configuration
        cache_warming_enabled = getenv("CACHE_WARMING_ENABLED", "true").lower() in ("true", "1", "yes")

        # Cache invalidation webhook configuration
        cache_webhook_secret = getenv("CACHE_WEBHOOK_SECRET")

        return cls(
            amqp_connection=graphinator_config.amqp_connection,
            neo4j_address=graphinator_config.neo4j_address,
            neo4j_username=graphinator_config.neo4j_username,
            neo4j_password=graphinator_config.neo4j_password,
            postgres_address=tableinator_config.postgres_address,
            postgres_username=tableinator_config.postgres_username,
            postgres_password=tableinator_config.postgres_password,
            postgres_database=tableinator_config.postgres_database,
            redis_url=redis_url,
            rabbitmq_username=rabbitmq_username,
            rabbitmq_password=rabbitmq_password,
            cors_origins=cors_origins,
            cache_warming_enabled=cache_warming_enabled,
            cache_webhook_secret=cache_webhook_secret,
        )


@dataclass(frozen=True)
class ApiConfig:
    """Configuration for the API service."""

    postgres_address: str
    postgres_username: str
    postgres_password: str
    postgres_database: str
    jwt_secret_key: str
    redis_url: str = "redis://redis:6379/0"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 30
    discogs_user_agent: str = "discogsography/1.0 +https://github.com/SimplicityGuy/discogsography"
    neo4j_address: str | None = None
    neo4j_username: str | None = None
    neo4j_password: str | None = None
    cors_origins: list[str] | None = None
    snapshot_ttl_days: int = 28
    snapshot_max_nodes: int = 100
    oauth_encryption_key: str | None = None

    @classmethod
    def from_env(cls) -> "ApiConfig":
        """Create configuration from environment variables."""
        postgres_address = getenv("POSTGRES_ADDRESS")
        postgres_username = get_secret("POSTGRES_USERNAME")
        postgres_password = get_secret("POSTGRES_PASSWORD")
        postgres_database = getenv("POSTGRES_DATABASE")
        jwt_secret_key = get_secret("JWT_SECRET_KEY")

        missing_vars = []
        if not postgres_address:
            missing_vars.append("POSTGRES_ADDRESS")
        if not postgres_username:
            missing_vars.append("POSTGRES_USERNAME")
        if not postgres_password:
            missing_vars.append("POSTGRES_PASSWORD")
        if not postgres_database:
            missing_vars.append("POSTGRES_DATABASE")
        if not jwt_secret_key:
            missing_vars.append("JWT_SECRET_KEY")

        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        redis_url = getenv("REDIS_URL", "redis://redis:6379/0")
        jwt_algorithm = getenv("JWT_ALGORITHM", "HS256")
        if jwt_algorithm != "HS256":
            raise ValueError(f"Unsupported JWT algorithm: {jwt_algorithm}. Only HS256 is supported.")
        jwt_expire_minutes_str = getenv("JWT_EXPIRE_MINUTES", "30")
        try:
            jwt_expire_minutes = int(jwt_expire_minutes_str)
        except ValueError:
            jwt_expire_minutes = 30
        discogs_user_agent = getenv(
            "DISCOGS_USER_AGENT",
            "discogsography/1.0 +https://github.com/SimplicityGuy/discogsography",
        )
        neo4j_address = getenv("NEO4J_ADDRESS") or None
        neo4j_username = getenv("NEO4J_USERNAME") or None
        neo4j_password = getenv("NEO4J_PASSWORD") or None

        cors_origins_env = getenv("CORS_ORIGINS")
        cors_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()] if cors_origins_env else None

        snapshot_ttl_days_str = getenv("SNAPSHOT_TTL_DAYS", "28")
        try:
            snapshot_ttl_days = int(snapshot_ttl_days_str)
        except ValueError:
            snapshot_ttl_days = 28

        snapshot_max_nodes_str = getenv("SNAPSHOT_MAX_NODES", "100")
        try:
            snapshot_max_nodes = int(snapshot_max_nodes_str)
        except ValueError:
            snapshot_max_nodes = 100

        oauth_encryption_key = get_secret("OAUTH_ENCRYPTION_KEY") or None

        return cls(
            postgres_address=cast("str", postgres_address),
            postgres_username=cast("str", postgres_username),
            postgres_password=cast("str", postgres_password),
            postgres_database=cast("str", postgres_database),
            jwt_secret_key=cast("str", jwt_secret_key),
            redis_url=redis_url,
            jwt_algorithm=jwt_algorithm,
            jwt_expire_minutes=jwt_expire_minutes,
            discogs_user_agent=discogs_user_agent,
            neo4j_address=neo4j_address,
            neo4j_username=neo4j_username,
            neo4j_password=neo4j_password,
            cors_origins=cors_origins,
            snapshot_ttl_days=snapshot_ttl_days,
            snapshot_max_nodes=snapshot_max_nodes,
            oauth_encryption_key=oauth_encryption_key,
        )


@dataclass(frozen=True)
class CuratorConfig:
    """Configuration for the curator service."""

    postgres_address: str
    postgres_username: str
    postgres_password: str
    postgres_database: str
    neo4j_address: str
    neo4j_username: str
    neo4j_password: str
    discogs_user_agent: str = "discogsography/1.0 +https://github.com/SimplicityGuy/discogsography"
    cors_origins: list[str] | None = None

    @classmethod
    def from_env(cls) -> "CuratorConfig":
        """Create configuration from environment variables."""
        postgres_address = getenv("POSTGRES_ADDRESS")
        postgres_username = get_secret("POSTGRES_USERNAME")
        postgres_password = get_secret("POSTGRES_PASSWORD")
        postgres_database = getenv("POSTGRES_DATABASE")
        neo4j_address = getenv("NEO4J_ADDRESS")
        neo4j_username = get_secret("NEO4J_USERNAME")
        neo4j_password = get_secret("NEO4J_PASSWORD")

        missing_vars = []
        if not postgres_address:
            missing_vars.append("POSTGRES_ADDRESS")
        if not postgres_username:
            missing_vars.append("POSTGRES_USERNAME")
        if not postgres_password:
            missing_vars.append("POSTGRES_PASSWORD")
        if not postgres_database:
            missing_vars.append("POSTGRES_DATABASE")
        if not neo4j_address:
            missing_vars.append("NEO4J_ADDRESS")
        if not neo4j_username:
            missing_vars.append("NEO4J_USERNAME")
        if not neo4j_password:
            missing_vars.append("NEO4J_PASSWORD")

        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        discogs_user_agent = getenv(
            "DISCOGS_USER_AGENT",
            "discogsography/1.0 +https://github.com/SimplicityGuy/discogsography",
        )

        cors_origins_env = getenv("CORS_ORIGINS")
        cors_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()] if cors_origins_env else None

        return cls(
            postgres_address=cast("str", postgres_address),
            postgres_username=cast("str", postgres_username),
            postgres_password=cast("str", postgres_password),
            postgres_database=cast("str", postgres_database),
            neo4j_address=cast("str", neo4j_address),
            neo4j_username=cast("str", neo4j_username),
            neo4j_password=cast("str", neo4j_password),
            discogs_user_agent=discogs_user_agent,
            cors_origins=cors_origins,
        )


# Discovery service uses the same configuration as dashboard
DiscoveryConfig = DashboardConfig


@dataclass(frozen=True)
class ExploreConfig:
    """Configuration for the explore service."""

    neo4j_address: str
    neo4j_username: str
    neo4j_password: str
    jwt_secret_key: str | None = None  # Optional: required only for personalized user endpoints

    @classmethod
    def from_env(cls) -> "ExploreConfig":
        """Create configuration from environment variables."""
        neo4j_address = getenv("NEO4J_ADDRESS")
        neo4j_username = get_secret("NEO4J_USERNAME")
        neo4j_password = get_secret("NEO4J_PASSWORD")

        missing_vars = []
        if not neo4j_address:
            missing_vars.append("NEO4J_ADDRESS")
        if not neo4j_username:
            missing_vars.append("NEO4J_USERNAME")
        if not neo4j_password:
            missing_vars.append("NEO4J_PASSWORD")

        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        # Optional: enables personalized /api/user/* endpoints
        jwt_secret_key = get_secret("JWT_SECRET_KEY") or None

        return cls(
            neo4j_address=cast("str", neo4j_address),
            neo4j_username=cast("str", neo4j_username),
            neo4j_password=cast("str", neo4j_password),
            jwt_secret_key=jwt_secret_key,
        )


def get_config() -> DashboardConfig:
    """Get dashboard/discovery configuration from environment.

    Both dashboard and discovery services share the same configuration structure.
    """
    return DashboardConfig.from_env()

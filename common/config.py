"""Configuration management for discogsography services."""

from dataclasses import dataclass, field
import logging
from os import getenv
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Any, cast, overload
from urllib.parse import quote as _url_quote
import warnings


if TYPE_CHECKING:
    from collections.abc import Sequence  # pragma: no cover

from neo4j import TrustAll, TrustSystemCAs
import orjson
import structlog

from common import query_debug


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

    Reads the password via the standard _FILE secret convention (Docker secrets),
    falling back to plain environment variables, then to defaults.
    """
    user = get_secret("RABBITMQ_USERNAME", "discogsography")
    password = get_secret("RABBITMQ_PASSWORD", "discogsography")
    host = getenv("RABBITMQ_HOST", "rabbitmq")
    port = getenv("RABBITMQ_PORT", "5672")
    return f"amqp://{_url_quote(user, safe='')}:{_url_quote(password, safe='')}@{host}:{port}/%2F"


def _build_neo4j_uri() -> str:
    """Build Neo4j bolt URI from plain hostname environment variable."""
    host = getenv("NEO4J_HOST", "localhost")
    return f"bolt://{host}:7687"


def _coerce_port(value: str | None, default_port: int) -> int:
    """Parse a port string to int, falling back to default_port on anything invalid."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default_port


def parse_postgres_host_port(value: str | None, default_port: int = 5432) -> tuple[str, int]:
    """Split a POSTGRES_HOST value into a (host, port) pair.

    POSTGRES_HOST may carry an embedded port (e.g. a PgBouncer pooler configured
    as ``"pgbouncer:6432"``). When a port is embedded it always wins; otherwise
    ``default_port`` (normally POSTGRES_PORT, falling back to 5432) is used. The
    two ports are never concatenated.

    Accepted forms:

    - ``"host"``         -> ``(host, default_port)``
    - ``"host:6432"``    -> ``(host, 6432)``      (embedded port wins)
    - ``"[::1]"``        -> ``("::1", default_port)``
    - ``"[::1]:6432"``   -> ``("::1", 6432)``     (IPv6 in brackets)
    - ``"::1"``          -> ``("::1", default_port)`` (bare IPv6 literal, no port)
    - ``""`` / ``None``  -> ``("localhost", default_port)``
    """
    raw = (value or "").strip()
    if not raw:
        return "localhost", default_port

    # IPv6 in brackets: "[host]" or "[host]:port"
    if raw.startswith("["):
        end = raw.find("]")
        if end != -1:
            host = raw[1:end]
            rest = raw[end + 1 :]
            if rest.startswith(":") and rest[1:]:
                return host, _coerce_port(rest[1:], default_port)
            return host, default_port
        # Malformed bracket — fall through and treat the whole value as a host.

    # Bare IPv6 literal (more than one colon, no brackets) — no port to extract.
    if raw.count(":") > 1:
        return raw, default_port

    if ":" in raw:
        host, _, port_str = raw.partition(":")
        return (host or "localhost"), _coerce_port(port_str, default_port)

    return raw, default_port


def _coerce_pool_size(value: str | None, default: int) -> int:
    """Parse a pool-size string to a positive int, falling back to default on anything invalid."""
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 1 else default


def resolve_postgres_pool_sizes(default_min: int, default_max: int) -> tuple[int, int]:
    """Resolve ``(min, max)`` PostgreSQL pool sizes from env with budget-aware defaults.

    Every long-lived service shares a single PostgreSQL backend budget (in production
    a PgBouncer pooler in *session* mode pins one backend per client connection for its
    whole lifetime, with a hard per-database cap). The sum of every service's pool
    ``max`` is therefore the deployment's real connection footprint and must stay under
    that cap. Each service ships a conservative per-service default; an operator can
    additionally clamp the whole fleet with the shared ``POSTGRES_POOL_MIN_SIZE`` /
    ``POSTGRES_POOL_MAX_SIZE`` overrides without a code change.

    Values are clamped so ``1 <= min <= max``.
    """
    min_size = _coerce_pool_size(getenv("POSTGRES_POOL_MIN_SIZE"), default_min)
    max_size = _coerce_pool_size(getenv("POSTGRES_POOL_MAX_SIZE"), default_max)
    max_size = max(max_size, 1)
    min_size = min(min_size, max_size)
    return min_size, max_size


def _build_postgres_connstr() -> str:
    """Build a canonical ``host:port`` connection string for PostgreSQL.

    Reads POSTGRES_HOST (which may embed a port, e.g. ``"pgbouncer:6432"``) and
    POSTGRES_PORT (default 5432). An embedded port in POSTGRES_HOST takes
    precedence over POSTGRES_PORT; the two are never concatenated. IPv6 hosts are
    bracketed so the result round-trips through ``parse_postgres_host_port``.
    """
    default_port = _coerce_port(getenv("POSTGRES_PORT", "5432"), 5432)
    host, port = parse_postgres_host_port(getenv("POSTGRES_HOST", "localhost"), default_port)
    if ":" in host:  # IPv6 literal — bracket it for safe round-tripping.
        return f"[{host}]:{port}"
    return f"{host}:{port}"


def _build_redis_url() -> str:
    """Build Redis connection URL from component secrets and environment variables.

    Reads the password via the standard _FILE secret convention (Docker secrets),
    falling back to the plain REDIS_PASSWORD environment variable. The auth segment
    is omitted when no password is set so password-less local Redis keeps working.
    """
    password = get_secret("REDIS_PASSWORD")
    host = getenv("REDIS_HOST", "localhost")
    port = getenv("REDIS_PORT", "6379")
    if password:
        return f"redis://:{_url_quote(password, safe='')}@{host}:{port}/0"
    return f"redis://{host}:{port}/0"


def neo4j_security_kwargs() -> dict[str, Any]:
    """Build neo4j driver TLS/security kwargs from NEO4J_TLS_* environment variables.

    Controls Bolt transport encryption for every service's Neo4j driver:

    - TLS disabled (default)      -> {}  (plaintext bolt://, unchanged behavior)
    - enabled, verify (default)   -> encrypted=True + TrustSystemCAs() (verify cert vs system CAs)
    - enabled, verify disabled    -> encrypted=True + TrustAll() (encrypted, identity unverified)

    Only a case-insensitive "true" enables each flag (project boolean convention).
    """
    if getenv("NEO4J_TLS_ENABLED", "false").strip().lower() != "true":
        return {}

    if getenv("NEO4J_TLS_VERIFY", "true").strip().lower() == "true":
        logger.info("🛡️ Neo4j Bolt TLS enabled (encrypted, verifying server certificate)")
        return {"encrypted": True, "trusted_certificates": TrustSystemCAs()}

    logger.warning(
        "⚠️ Neo4j Bolt TLS enabled WITHOUT certificate verification — traffic is encrypted "
        "but the server identity is not verified (no MITM protection)"
    )
    return {"encrypted": True, "trusted_certificates": TrustAll()}


@dataclass(frozen=True)
class ExtractorConfig:
    """Configuration for the extractor service."""

    amqp_connection: str = field(repr=False)
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

    amqp_connection: str = field(repr=False)
    neo4j_host: str
    neo4j_username: str
    neo4j_password: str

    @classmethod
    def from_env(cls) -> "GraphinatorConfig":
        """Create configuration from environment variables."""
        amqp_connection = _build_amqp_url()
        neo4j_username = get_secret("NEO4J_USERNAME")
        neo4j_password = get_secret("NEO4J_PASSWORD")

        missing_vars = []
        if not getenv("NEO4J_HOST"):
            missing_vars.append("NEO4J_HOST")
        if not neo4j_username:
            missing_vars.append("NEO4J_USERNAME")
        if not neo4j_password:
            missing_vars.append("NEO4J_PASSWORD")

        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        return cls(
            amqp_connection=amqp_connection,
            neo4j_host=_build_neo4j_uri(),
            neo4j_username=cast("str", neo4j_username),
            neo4j_password=cast("str", neo4j_password),
        )


@dataclass(frozen=True)
class BrainzgraphinatorConfig:
    """Configuration for the brainzgraphinator service."""

    amqp_connection: str = field(repr=False)
    neo4j_host: str
    neo4j_username: str
    neo4j_password: str

    @classmethod
    def from_env(cls) -> "BrainzgraphinatorConfig":
        """Create configuration from environment variables."""
        amqp_connection = _build_amqp_url()
        neo4j_username = get_secret("NEO4J_USERNAME")
        neo4j_password = get_secret("NEO4J_PASSWORD")

        missing_vars = []
        if not getenv("NEO4J_HOST"):
            missing_vars.append("NEO4J_HOST")
        if not neo4j_username:
            missing_vars.append("NEO4J_USERNAME")
        if not neo4j_password:
            missing_vars.append("NEO4J_PASSWORD")

        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        return cls(
            amqp_connection=amqp_connection,
            neo4j_host=_build_neo4j_uri(),
            neo4j_username=cast("str", neo4j_username),
            neo4j_password=cast("str", neo4j_password),
        )


@dataclass(frozen=True)
class TableinatorConfig:
    """Configuration for the tableinator service."""

    amqp_connection: str = field(repr=False)
    postgres_host: str
    postgres_username: str
    postgres_password: str
    postgres_database: str
    # Connection-pool sizing. Tableinator batches writes through a BatchProcessor
    # whose semaphore caps concurrent flushes, so it never needs many connections.
    # Kept small to fit the shared PgBouncer backend budget (see resolve_postgres_pool_sizes).
    postgres_pool_min_size: int = 2
    postgres_pool_max_size: int = 12

    @classmethod
    def from_env(cls) -> "TableinatorConfig":
        """Create configuration from environment variables."""
        amqp_connection = _build_amqp_url()
        postgres_username = get_secret("POSTGRES_USERNAME")
        postgres_password = get_secret("POSTGRES_PASSWORD")
        postgres_database = getenv("POSTGRES_DATABASE")

        missing_vars = []
        if not getenv("POSTGRES_HOST"):
            missing_vars.append("POSTGRES_HOST")
        if not postgres_username:
            missing_vars.append("POSTGRES_USERNAME")
        if not postgres_password:
            missing_vars.append("POSTGRES_PASSWORD")
        if not postgres_database:
            missing_vars.append("POSTGRES_DATABASE")

        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        pool_min, pool_max = resolve_postgres_pool_sizes(default_min=2, default_max=12)

        return cls(
            amqp_connection=amqp_connection,
            postgres_host=_build_postgres_connstr(),
            postgres_username=cast("str", postgres_username),
            postgres_password=cast("str", postgres_password),
            postgres_database=cast("str", postgres_database),
            postgres_pool_min_size=pool_min,
            postgres_pool_max_size=pool_max,
        )


@dataclass(frozen=True)
class BrainztableinatorConfig:
    """Configuration for the brainztableinator service."""

    amqp_connection: str = field(repr=False)
    postgres_host: str
    postgres_username: str
    postgres_password: str
    postgres_database: str
    # Connection-pool sizing. Brainztableinator's RabbitMQ prefetch is coupled to this
    # max (see brainztableinator.py) so in-flight message handlers can never exceed the
    # connection capacity. Kept small to fit the shared PgBouncer backend budget.
    postgres_pool_min_size: int = 2
    postgres_pool_max_size: int = 12

    @classmethod
    def from_env(cls) -> "BrainztableinatorConfig":
        """Create configuration from environment variables."""
        amqp_connection = _build_amqp_url()
        postgres_username = get_secret("POSTGRES_USERNAME")
        postgres_password = get_secret("POSTGRES_PASSWORD")
        postgres_database = getenv("POSTGRES_DATABASE")

        missing_vars = []
        if not getenv("POSTGRES_HOST"):
            missing_vars.append("POSTGRES_HOST")
        if not postgres_username:
            missing_vars.append("POSTGRES_USERNAME")
        if not postgres_password:
            missing_vars.append("POSTGRES_PASSWORD")
        if not postgres_database:
            missing_vars.append("POSTGRES_DATABASE")

        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        pool_min, pool_max = resolve_postgres_pool_sizes(default_min=2, default_max=12)

        return cls(
            amqp_connection=amqp_connection,
            postgres_host=_build_postgres_connstr(),
            postgres_username=cast("str", postgres_username),
            postgres_password=cast("str", postgres_password),
            postgres_database=cast("str", postgres_database),
            postgres_pool_min_size=pool_min,
            postgres_pool_max_size=pool_max,
        )


# AMQP Configuration shared across all services
DISCOGS_EXCHANGE_PREFIX = getenv("DISCOGS_EXCHANGE_PREFIX", "discogsography-discogs")
AMQP_EXCHANGE_TYPE = "fanout"  # Fanout exchanges for decoupled pub/sub
AMQP_QUEUE_PREFIX_GRAPHINATOR = f"{DISCOGS_EXCHANGE_PREFIX}-graphinator"
AMQP_QUEUE_PREFIX_TABLEINATOR = f"{DISCOGS_EXCHANGE_PREFIX}-tableinator"

# Data types that will be processed
DATA_TYPES = ["artists", "labels", "masters", "releases"]

# MusicBrainz AMQP configuration
MUSICBRAINZ_EXCHANGE_PREFIX = getenv("MUSICBRAINZ_EXCHANGE_PREFIX", "discogsography-musicbrainz")
AMQP_QUEUE_PREFIX_BRAINZGRAPHINATOR = f"{MUSICBRAINZ_EXCHANGE_PREFIX}-brainzgraphinator"
AMQP_QUEUE_PREFIX_BRAINZTABLEINATOR = f"{MUSICBRAINZ_EXCHANGE_PREFIX}-brainztableinator"
MUSICBRAINZ_DATA_TYPES = ["artists", "labels", "release-groups", "releases"]


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

    # Warn if database profiling is active
    if query_debug.is_db_profiling():
        log.warning(
            "⚠️ Database profiling enabled — PROFILE/EXPLAIN plans will be logged for Cypher and SQL queries",
            db_profiling=True,
        )


@dataclass(frozen=True)
class DashboardConfig:
    """Configuration for the dashboard service."""

    amqp_connection: str = field(repr=False)
    neo4j_host: str
    neo4j_username: str
    neo4j_password: str
    postgres_host: str
    postgres_username: str
    postgres_password: str
    postgres_database: str
    rabbitmq_username: str
    rabbitmq_password: str
    redis_host: str = "redis://localhost:6379/0"
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
        redis_host = _build_redis_url()

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
        cache_webhook_secret = get_secret("CACHE_WEBHOOK_SECRET")

        return cls(
            amqp_connection=graphinator_config.amqp_connection,
            neo4j_host=graphinator_config.neo4j_host,
            neo4j_username=graphinator_config.neo4j_username,
            neo4j_password=graphinator_config.neo4j_password,
            postgres_host=tableinator_config.postgres_host,
            postgres_username=tableinator_config.postgres_username,
            postgres_password=tableinator_config.postgres_password,
            postgres_database=tableinator_config.postgres_database,
            redis_host=redis_host,
            rabbitmq_username=rabbitmq_username,
            rabbitmq_password=rabbitmq_password,
            cors_origins=cors_origins,
            cache_warming_enabled=cache_warming_enabled,
            cache_webhook_secret=cache_webhook_secret,
        )


@dataclass(frozen=True)
class ApiConfig:
    """Configuration for the API service."""

    postgres_host: str
    postgres_username: str
    postgres_password: str
    postgres_database: str
    jwt_secret_key: str
    neo4j_host: str
    neo4j_username: str
    neo4j_password: str
    # Connection-pool sizing. The API is user-facing; modest concurrency is enough and
    # it must share the PgBouncer backend budget with the importers (see resolve_postgres_pool_sizes).
    postgres_pool_min_size: int = 2
    postgres_pool_max_size: int = 8
    redis_host: str = "redis://redis:6379/0"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 30
    discogs_user_agent: str = "discogsography/1.0 +https://github.com/SimplicityGuy/discogsography"
    # Public URL Discogs should redirect to after the user authorizes the app.
    # When unset, the OAuth 1.0a "out-of-band" flow is used and the user has to
    # paste a verifier code shown by Discogs back into the app.
    discogs_oauth_callback_url: str | None = None
    cors_origins: list[str] | None = None
    snapshot_ttl_days: int = 28
    snapshot_max_nodes: int = 100
    encryption_master_key: str | None = None

    # Brevo email notifications
    brevo_api_key: str | None = None
    brevo_sender_email: str = "noreply@discogsography.com"
    brevo_sender_name: str = "Discogsography"

    # Admin dashboard — extractor connection
    extractor_host: str = "extractor"
    extractor_health_port: int = 8000

    # Admin dashboard — RabbitMQ management API
    rabbitmq_management_host: str = "rabbitmq"
    rabbitmq_management_port: int = 15672
    rabbitmq_username: str = "guest"
    rabbitmq_password: str = "guest"  # noqa: S105

    # Admin dashboard — metrics collection
    metrics_retention_days: int = 366
    metrics_collection_interval: int = 300  # seconds

    @classmethod
    def from_env(cls) -> "ApiConfig":
        """Create configuration from environment variables."""
        postgres_username = get_secret("POSTGRES_USERNAME")
        postgres_password = get_secret("POSTGRES_PASSWORD")
        postgres_database = getenv("POSTGRES_DATABASE")
        jwt_secret_key = get_secret("JWT_SECRET_KEY")

        neo4j_username = get_secret("NEO4J_USERNAME")
        neo4j_password = get_secret("NEO4J_PASSWORD")

        missing_vars = []
        if not getenv("POSTGRES_HOST"):
            missing_vars.append("POSTGRES_HOST")
        if not postgres_username:
            missing_vars.append("POSTGRES_USERNAME")
        if not postgres_password:
            missing_vars.append("POSTGRES_PASSWORD")
        if not postgres_database:
            missing_vars.append("POSTGRES_DATABASE")
        if not jwt_secret_key:
            missing_vars.append("JWT_SECRET_KEY")
        if not getenv("NEO4J_HOST"):
            missing_vars.append("NEO4J_HOST")
        if not neo4j_username:
            missing_vars.append("NEO4J_USERNAME")
        if not neo4j_password:
            missing_vars.append("NEO4J_PASSWORD")

        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        redis_host = _build_redis_url()
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
        discogs_oauth_callback_url = getenv("DISCOGS_OAUTH_CALLBACK_URL") or None

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

        pool_min, pool_max = resolve_postgres_pool_sizes(default_min=2, default_max=8)

        encryption_master_key = get_secret("ENCRYPTION_MASTER_KEY") or None
        brevo_api_key = get_secret("BREVO_API_KEY") or None
        brevo_sender_email = getenv("BREVO_SENDER_EMAIL", "noreply@discogsography.com")
        brevo_sender_name = getenv("BREVO_SENDER_NAME", "Discogsography")

        metrics_retention_days_str = getenv("METRICS_RETENTION_DAYS", "366")
        try:
            metrics_retention_days = int(metrics_retention_days_str)
        except ValueError:
            metrics_retention_days = 366

        metrics_collection_interval_str = getenv("METRICS_COLLECTION_INTERVAL", "300")
        try:
            metrics_collection_interval = int(metrics_collection_interval_str)
        except ValueError:
            metrics_collection_interval = 300

        return cls(
            postgres_host=_build_postgres_connstr(),
            postgres_username=cast("str", postgres_username),
            postgres_password=cast("str", postgres_password),
            postgres_database=cast("str", postgres_database),
            jwt_secret_key=cast("str", jwt_secret_key),
            redis_host=redis_host,
            jwt_algorithm=jwt_algorithm,
            jwt_expire_minutes=jwt_expire_minutes,
            discogs_user_agent=discogs_user_agent,
            discogs_oauth_callback_url=discogs_oauth_callback_url,
            neo4j_host=_build_neo4j_uri(),
            neo4j_username=cast("str", neo4j_username),
            neo4j_password=cast("str", neo4j_password),
            postgres_pool_min_size=pool_min,
            postgres_pool_max_size=pool_max,
            cors_origins=cors_origins,
            snapshot_ttl_days=snapshot_ttl_days,
            snapshot_max_nodes=snapshot_max_nodes,
            encryption_master_key=encryption_master_key,
            brevo_api_key=brevo_api_key,
            brevo_sender_email=brevo_sender_email,
            brevo_sender_name=brevo_sender_name,
            extractor_host=getenv("EXTRACTOR_HOST", "extractor"),
            extractor_health_port=int(getenv("EXTRACTOR_HEALTH_PORT", "8000")),
            rabbitmq_management_host=getenv("RABBITMQ_MANAGEMENT_HOST", getenv("RABBITMQ_HOST", "rabbitmq")),
            rabbitmq_management_port=int(getenv("RABBITMQ_MANAGEMENT_PORT", "15672")),
            rabbitmq_username=get_secret("RABBITMQ_USERNAME", "guest"),
            rabbitmq_password=get_secret("RABBITMQ_PASSWORD") or "guest",
            metrics_retention_days=metrics_retention_days,
            metrics_collection_interval=metrics_collection_interval,
        )


# Discovery service uses the same configuration as dashboard
DiscoveryConfig = DashboardConfig


@dataclass(frozen=True)
class ExploreConfig:
    """Configuration for the explore service.

    Explore serves static files only — no Neo4j connection required.
    """

    api_base_url: str = "http://api:8004"

    @classmethod
    def from_env(cls) -> "ExploreConfig":
        """Create configuration from environment variables."""
        api_base_url = getenv("API_BASE_URL", "http://api:8004")
        return cls(
            api_base_url=api_base_url,
        )


@dataclass(frozen=True)
class InsightsConfig:
    """Configuration for the insights service."""

    api_base_url: str
    postgres_host: str
    postgres_username: str
    postgres_password: str
    postgres_database: str
    # Connection-pool sizing. Insights runs periodic batch analytics jobs and only needs
    # a handful of connections; kept small to fit the shared PgBouncer backend budget.
    postgres_pool_min_size: int = 1
    postgres_pool_max_size: int = 4
    redis_host: str = "redis://localhost:6379/0"
    schedule_hours: int = 24
    milestone_years: tuple[int, ...] = (25, 30, 40, 50, 75, 100)

    @classmethod
    def from_env(cls) -> "InsightsConfig":
        """Create configuration from environment variables."""
        postgres_username = get_secret("POSTGRES_USERNAME")
        postgres_password = get_secret("POSTGRES_PASSWORD")
        postgres_database = getenv("POSTGRES_DATABASE")

        missing_vars = []
        if not getenv("POSTGRES_HOST"):
            missing_vars.append("POSTGRES_HOST")
        if not postgres_username:
            missing_vars.append("POSTGRES_USERNAME")
        if not postgres_password:
            missing_vars.append("POSTGRES_PASSWORD")
        if not postgres_database:
            missing_vars.append("POSTGRES_DATABASE")

        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        api_base_url = getenv("API_BASE_URL", "http://api:8004")

        schedule_hours_str = getenv("INSIGHTS_SCHEDULE_HOURS", "24")
        try:
            schedule_hours = int(schedule_hours_str)
            if schedule_hours < 1:
                schedule_hours = 24
        except ValueError:
            schedule_hours = 24

        milestone_years_str = getenv("INSIGHTS_MILESTONE_YEARS", "25,30,40,50,75,100")
        try:
            parsed = sorted({int(y.strip()) for y in milestone_years_str.split(",") if y.strip()})
            milestone_years = tuple(parsed) if parsed else (25, 30, 40, 50, 75, 100)
        except ValueError:
            milestone_years = (25, 30, 40, 50, 75, 100)

        redis_host = _build_redis_url()

        pool_min, pool_max = resolve_postgres_pool_sizes(default_min=1, default_max=4)

        return cls(
            api_base_url=api_base_url,
            postgres_host=_build_postgres_connstr(),
            postgres_username=cast("str", postgres_username),
            postgres_password=cast("str", postgres_password),
            postgres_database=cast("str", postgres_database),
            postgres_pool_min_size=pool_min,
            postgres_pool_max_size=pool_max,
            redis_host=redis_host,
            schedule_hours=schedule_hours,
            milestone_years=milestone_years,
        )


def get_config() -> DashboardConfig:
    """Get dashboard/discovery configuration from environment.

    Both dashboard and discovery services share the same configuration structure.
    """
    return DashboardConfig.from_env()

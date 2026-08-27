"""Configuration management for discogsography services."""

from importlib import import_module
import logging
from os import getenv
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Any, overload
from urllib.parse import quote as _url_quote
import warnings


if TYPE_CHECKING:
    from collections.abc import Sequence  # pragma: no cover

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
    """Build a Neo4j connection URI from environment variables.

    NEO4J_HOST accepts two forms:

    - a bare hostname (e.g. ``"localhost"`` or ``"neo4j"``) — wrapped as
      ``bolt://<host>:<NEO4J_PORT or 7687>``, the historical default.
    - a full connection URI (e.g. ``"neo4j+s://xxxxx.databases.neo4j.io"`` for
      Neo4j Aura) — detected by the presence of a ``scheme://`` prefix and
      passed through unchanged, so routing schemes (``neo4j://``,
      ``neo4j+s://``) and non-default ports are honored as documented.
    """
    host = getenv("NEO4J_HOST", "localhost")
    if "://" in host:
        return host
    port = getenv("NEO4J_PORT", "7687")
    return f"bolt://{host}:{port}"


def _coerce_port(value: str | None, default_port: int) -> int:
    """Parse a port string to int, falling back to default_port on anything invalid."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default_port


# Single boolean-parsing vocabulary for the whole module (matches the historical
# CACHE_WARMING_ENABLED convention) so every "enable this feature" flag agrees on
# what counts as truthy/falsey.
_TRUTHY_TOKENS = ("true", "1", "yes")
_FALSEY_TOKENS = ("false", "0", "no")


def _is_truthy(value: str | None) -> bool:
    """Return True when value is an explicit truthy token (permissive enable-flag parsing)."""
    return (value or "").strip().lower() in _TRUTHY_TOKENS


def _is_falsey(value: str | None) -> bool:
    """Return True when value is an explicit falsey token (default-secure disable-flag parsing)."""
    return (value or "").strip().lower() in _FALSEY_TOKENS


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

    NEO4J_TLS_ENABLED uses permissive truthy parsing ("true"/"1"/"yes", matching the
    CACHE_WARMING_ENABLED convention elsewhere in this module) so an operator who spells
    "enable" any of the usual ways actually enables TLS instead of silently staying plaintext.

    NEO4J_TLS_VERIFY is security-critical and default-secure: verification stays ON unless
    the value is an explicit falsey token ("false"/"0"/"no"). This avoids the fail-open bug
    where an operator typing "1"/"yes"/"on" to mean "verify" would otherwise land on
    TrustAll() (encrypted but MITM-able) instead of TrustSystemCAs().
    """
    neo4j = import_module("neo4j")

    if not _is_truthy(getenv("NEO4J_TLS_ENABLED", "false")):
        return {}

    if not _is_falsey(getenv("NEO4J_TLS_VERIFY", "true")):
        logger.info("🛡️ Neo4j Bolt TLS enabled (encrypted, verifying server certificate)")
        return {"encrypted": True, "trusted_certificates": neo4j.TrustSystemCAs()}

    logger.warning(
        "⚠️ Neo4j Bolt TLS enabled WITHOUT certificate verification — traffic is encrypted "
        "but the server identity is not verified (no MITM protection)"
    )
    return {"encrypted": True, "trusted_certificates": neo4j.TrustAll()}


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

    # Normalize and validate the level name (strip stray whitespace, e.g. from a
    # compose file) and fall back to INFO instead of crashing on an unrecognized
    # value ('TRACE', a typo, trailing punctuation, ...). getattr() is called
    # with an explicit default so an invalid name can never raise AttributeError.
    normalized_level = level.strip().upper()
    resolved_level = getattr(logging, normalized_level, None)
    invalid_level_value: str | None = None
    if not isinstance(resolved_level, int):
        invalid_level_value = level
        resolved_level = logging.INFO

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
        level=resolved_level,
        handlers=handlers,
        force=True,
    )

    if invalid_level_value is not None:
        logging.getLogger(__name__).warning(
            "⚠️ Unrecognized LOG_LEVEL %r; falling back to INFO",
            invalid_level_value,
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

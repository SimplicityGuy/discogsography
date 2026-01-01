"""Configuration management for discogsography services."""

import logging
import sys
from dataclasses import dataclass
from os import getenv
from pathlib import Path
from typing import Any

import orjson
import structlog


logger = structlog.get_logger(__name__)


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
        amqp_connection = getenv("AMQP_CONNECTION")
        if not amqp_connection:
            raise ValueError("AMQP_CONNECTION environment variable is required")

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
        amqp_connection = getenv("AMQP_CONNECTION")
        neo4j_address = getenv("NEO4J_ADDRESS")
        neo4j_username = getenv("NEO4J_USERNAME")
        neo4j_password = getenv("NEO4J_PASSWORD")

        missing_vars = []
        if not amqp_connection:
            missing_vars.append("AMQP_CONNECTION")
        if not neo4j_address:
            missing_vars.append("NEO4J_ADDRESS")
        if not neo4j_username:
            missing_vars.append("NEO4J_USERNAME")
        if not neo4j_password:
            missing_vars.append("NEO4J_PASSWORD")

        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        return cls(
            amqp_connection=amqp_connection,  # type: ignore
            neo4j_address=neo4j_address,  # type: ignore
            neo4j_username=neo4j_username,  # type: ignore
            neo4j_password=neo4j_password,  # type: ignore
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
        amqp_connection = getenv("AMQP_CONNECTION")
        postgres_address = getenv("POSTGRES_ADDRESS")
        postgres_username = getenv("POSTGRES_USERNAME")
        postgres_password = getenv("POSTGRES_PASSWORD")
        postgres_database = getenv("POSTGRES_DATABASE")

        missing_vars = []
        if not amqp_connection:
            missing_vars.append("AMQP_CONNECTION")
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
            amqp_connection=amqp_connection,  # type: ignore
            postgres_address=postgres_address,  # type: ignore
            postgres_username=postgres_username,  # type: ignore
            postgres_password=postgres_password,  # type: ignore
            postgres_database=postgres_database,  # type: ignore
        )


# AMQP Configuration shared across all services
AMQP_EXCHANGE = "discogsography-exchange"
AMQP_EXCHANGE_TYPE = "topic"  # Use topic for routing by data type
AMQP_QUEUE_PREFIX_GRAPHINATOR = "discogsography-graphinator"
AMQP_QUEUE_PREFIX_TABLEINATOR = "discogsography-tableinator"

# Data types that will be processed
DATA_TYPES = ["artists", "labels", "masters", "releases"]


def orjson_serializer(msg: dict[str, Any], **kwargs: Any) -> str:  # noqa: ARG001
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
    level: str | None = "INFO",
    log_file: Path | None = None,
) -> None:
    """Set up structured logging configuration to match Rust extractor format."""

    # Default to INFO if level is None
    if level is None:
        level = "INFO"

    # Configure structlog processors
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors = [
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
    rabbitmq_management_user: str
    rabbitmq_management_password: str

    @classmethod
    def from_env(cls) -> "DashboardConfig":
        """Create configuration from environment variables."""
        # Reuse other configs for consistency
        graphinator_config = GraphinatorConfig.from_env()
        tableinator_config = TableinatorConfig.from_env()

        # Get RabbitMQ management credentials
        rabbitmq_management_user = getenv("RABBITMQ_MANAGEMENT_USER", "discogsography")
        rabbitmq_management_password = getenv("RABBITMQ_MANAGEMENT_PASSWORD", "discogsography")

        return cls(
            amqp_connection=graphinator_config.amqp_connection,
            neo4j_address=graphinator_config.neo4j_address,
            neo4j_username=graphinator_config.neo4j_username,
            neo4j_password=graphinator_config.neo4j_password,
            postgres_address=tableinator_config.postgres_address,
            postgres_username=tableinator_config.postgres_username,
            postgres_password=tableinator_config.postgres_password,
            postgres_database=tableinator_config.postgres_database,
            rabbitmq_management_user=rabbitmq_management_user,
            rabbitmq_management_password=rabbitmq_management_password,
        )


def get_config() -> DashboardConfig:
    """Get dashboard configuration from environment."""
    return DashboardConfig.from_env()

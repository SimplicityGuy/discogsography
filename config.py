"""Configuration management for discogsography services."""

import logging
from dataclasses import dataclass
from os import getenv
from pathlib import Path


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractorConfig:
    """Configuration for the extractor service."""

    amqp_connection: str
    discogs_root: Path
    max_temp_size: int = int(1e9)  # 1000 MB

    @classmethod
    def from_env(cls) -> "ExtractorConfig":
        """Create configuration from environment variables."""
        amqp_connection = getenv("AMQP_CONNECTION")
        if not amqp_connection:
            raise ValueError("AMQP_CONNECTION environment variable is required")

        discogs_root = Path(getenv("DISCOGS_ROOT", "/discogs-data"))

        return cls(
            amqp_connection=amqp_connection,
            discogs_root=discogs_root,
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


def setup_logging(
    service_name: str,
    level: str = "INFO",
    log_file: Path | None = None,
) -> None:
    """Set up logging configuration."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=f"%(asctime)s - {service_name} - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )

    logger.info(f"Logging configured for {service_name}")

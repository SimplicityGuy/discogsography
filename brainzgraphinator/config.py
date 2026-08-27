"""MusicBrainz graph enricher configuration owned by this service."""

from dataclasses import dataclass, field
from os import getenv
from typing import cast

from common.config import _build_amqp_url, _build_neo4j_uri, get_secret


@dataclass(frozen=True)
class BrainzgraphinatorConfig:
    """Configuration for the MusicBrainz graph enricher."""

    amqp_connection: str = field(repr=False)
    neo4j_host: str
    neo4j_username: str
    neo4j_password: str = field(repr=False)

    @classmethod
    def from_env(cls) -> "BrainzgraphinatorConfig":
        """Create configuration from environment variables."""
        neo4j_username = get_secret("NEO4J_USERNAME")
        neo4j_password = get_secret("NEO4J_PASSWORD")
        missing_vars = [
            name
            for name, value in (
                ("NEO4J_HOST", getenv("NEO4J_HOST")),
                ("NEO4J_USERNAME", neo4j_username),
                ("NEO4J_PASSWORD", neo4j_password),
            )
            if not value
        ]
        if missing_vars:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )
        return cls(
            amqp_connection=_build_amqp_url(),
            neo4j_host=_build_neo4j_uri(),
            neo4j_username=cast("str", neo4j_username),
            neo4j_password=cast("str", neo4j_password),
        )

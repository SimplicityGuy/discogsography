"""MusicBrainz SQL loader configuration owned by this service."""

from dataclasses import dataclass, field
from os import getenv
from typing import cast

from common.config import (
    _build_amqp_url,
    _build_postgres_connstr,
    get_secret,
    resolve_postgres_pool_sizes,
)


@dataclass(frozen=True)
class BrainztableinatorConfig:
    """Configuration for the MusicBrainz SQL loader."""

    amqp_connection: str = field(repr=False)
    postgres_host: str
    postgres_username: str
    postgres_password: str = field(repr=False)
    postgres_database: str
    postgres_pool_min_size: int = 2
    postgres_pool_max_size: int = 12

    @classmethod
    def from_env(cls) -> "BrainztableinatorConfig":
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
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )
        pool_min, pool_max = resolve_postgres_pool_sizes(default_min=2, default_max=12)
        return cls(
            amqp_connection=_build_amqp_url(),
            postgres_host=_build_postgres_connstr(),
            postgres_username=cast("str", postgres_username),
            postgres_password=cast("str", postgres_password),
            postgres_database=cast("str", postgres_database),
            postgres_pool_min_size=pool_min,
            postgres_pool_max_size=pool_max,
        )

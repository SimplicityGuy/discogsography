"""Graph explorer configuration owned by the explore service."""

from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True)
class ExploreConfig:
    """Configuration for the static graph-explorer proxy."""

    api_base_url: str = "http://api:8004"

    @classmethod
    def from_env(cls) -> "ExploreConfig":
        """Create configuration from environment variables."""
        return cls(api_base_url=getenv("API_BASE_URL", "http://api:8004"))

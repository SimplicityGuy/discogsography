"""NLQ configuration — loaded from environment variables."""

from dataclasses import dataclass
from os import getenv

from common.config import get_secret


@dataclass(frozen=True)
class NLQConfig:
    """Configuration for the NLQ engine."""

    enabled: bool = False
    api_key: str | None = None
    model: str = "claude-sonnet-4-20250514"
    max_iterations: int = 5
    max_query_length: int = 500
    cache_ttl: int = 3600
    rate_limit: str = "10/minute"

    @property
    def is_available(self) -> bool:
        """Return True if NLQ is both enabled and has a valid API key."""
        return self.enabled and self.api_key is not None

    @classmethod
    def from_env(cls) -> "NLQConfig":
        """Create NLQ configuration from environment variables."""
        return cls(
            enabled=getenv("NLQ_ENABLED", "false").lower() == "true",
            api_key=get_secret("NLQ_API_KEY"),
            model=getenv("NLQ_MODEL", "claude-sonnet-4-20250514"),
            max_iterations=int(getenv("NLQ_MAX_ITERATIONS", "5")),
            max_query_length=int(getenv("NLQ_MAX_QUERY_LENGTH", "500")),
            cache_ttl=int(getenv("NLQ_CACHE_TTL", "3600")),
            rate_limit=getenv("NLQ_RATE_LIMIT", "10/minute"),
        )

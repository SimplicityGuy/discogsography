"""Tests for DiggerConfig — loaded from common.config."""

import pytest

from common.config import DiggerConfig


_REQUIRED = {
    "POSTGRES_HOST": "pg-host",
    "POSTGRES_USERNAME": "pg-user",
    "POSTGRES_PASSWORD": "pg-pass",
    "POSTGRES_DATABASE": "pg-db",
    "REDIS_HOST": "redis-host",
}


class TestDiggerConfigFromEnv:
    """Tests for DiggerConfig.from_env()."""

    def _set_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, val in _REQUIRED.items():
            monkeypatch.setenv(key, val)

    def test_from_env_with_all_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Config builds correctly when all required vars are present."""
        self._set_required(monkeypatch)

        cfg = DiggerConfig.from_env()

        assert cfg.postgres_host == "pg-host:5432"
        assert cfg.postgres_username == "pg-user"
        assert cfg.postgres_password == "pg-pass"
        assert cfg.postgres_database == "pg-db"
        assert cfg.redis_host == "redis://redis-host:6379/0"

    def test_from_env_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-required fields use documented defaults."""
        self._set_required(monkeypatch)
        # Remove optional vars to confirm defaults
        for var in [
            "DIGGER_SCRAPER_USER_AGENT",
            "DIGGER_RATE_BUDGET_PER_HOUR",
            "DIGGER_CB_WINDOW_SECONDS",
            "DIGGER_CB_FAILURE_PCT",
            "DIGGER_CB_COOLDOWN_SECONDS",
        ]:
            monkeypatch.delenv(var, raising=False)

        cfg = DiggerConfig.from_env()

        assert "discogsography-digger/0.1" in cfg.scraper_user_agent
        assert cfg.rate_budget_per_hour == 600
        assert cfg.circuit_breaker_window_seconds == 300
        assert cfg.circuit_breaker_failure_pct == 30
        assert cfg.circuit_breaker_cooldown_seconds == 1800

    def test_from_env_custom_optional(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Optional fields are overridden by environment variables."""
        self._set_required(monkeypatch)
        monkeypatch.setenv("DIGGER_SCRAPER_USER_AGENT", "my-agent/1.0")
        monkeypatch.setenv("DIGGER_RATE_BUDGET_PER_HOUR", "300")
        monkeypatch.setenv("DIGGER_CB_WINDOW_SECONDS", "120")
        monkeypatch.setenv("DIGGER_CB_FAILURE_PCT", "50")
        monkeypatch.setenv("DIGGER_CB_COOLDOWN_SECONDS", "900")

        cfg = DiggerConfig.from_env()

        assert cfg.scraper_user_agent == "my-agent/1.0"
        assert cfg.rate_budget_per_hour == 300
        assert cfg.circuit_breaker_window_seconds == 120
        assert cfg.circuit_breaker_failure_pct == 50
        assert cfg.circuit_breaker_cooldown_seconds == 900

    def test_from_env_missing_postgres_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ValueError raised listing POSTGRES_HOST when it is absent."""
        self._set_required(monkeypatch)
        monkeypatch.delenv("POSTGRES_HOST", raising=False)

        with pytest.raises(ValueError, match="POSTGRES_HOST"):
            DiggerConfig.from_env()

    def test_from_env_missing_postgres_username(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ValueError raised listing POSTGRES_USERNAME when it is absent."""
        self._set_required(monkeypatch)
        monkeypatch.delenv("POSTGRES_USERNAME", raising=False)

        with pytest.raises(ValueError, match="POSTGRES_USERNAME"):
            DiggerConfig.from_env()

    def test_from_env_missing_postgres_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ValueError raised listing POSTGRES_PASSWORD when it is absent."""
        self._set_required(monkeypatch)
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

        with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
            DiggerConfig.from_env()

    def test_from_env_missing_postgres_database(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ValueError raised listing POSTGRES_DATABASE when it is absent."""
        self._set_required(monkeypatch)
        monkeypatch.delenv("POSTGRES_DATABASE", raising=False)

        with pytest.raises(ValueError, match="POSTGRES_DATABASE"):
            DiggerConfig.from_env()

    def test_from_env_missing_redis_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ValueError raised listing REDIS_HOST when it is absent."""
        self._set_required(monkeypatch)
        monkeypatch.delenv("REDIS_HOST", raising=False)

        with pytest.raises(ValueError, match="REDIS_HOST"):
            DiggerConfig.from_env()

    def test_from_env_multiple_missing_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ValueError lists all missing required vars when several are absent."""
        for key in _REQUIRED:
            monkeypatch.delenv(key, raising=False)

        with pytest.raises(ValueError) as exc_info:
            DiggerConfig.from_env()

        message = str(exc_info.value)
        assert "POSTGRES_HOST" in message
        assert "POSTGRES_USERNAME" in message
        assert "POSTGRES_PASSWORD" in message
        assert "POSTGRES_DATABASE" in message
        assert "REDIS_HOST" in message

    def test_from_env_postgres_connstr_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """postgres_host uses host:5432 format from _build_postgres_connstr."""
        self._set_required(monkeypatch)
        monkeypatch.setenv("POSTGRES_HOST", "my-postgres-server")

        cfg = DiggerConfig.from_env()

        assert cfg.postgres_host == "my-postgres-server:5432"

    def test_from_env_redis_url_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """redis_host uses redis://host:6379/0 format from _build_redis_url."""
        self._set_required(monkeypatch)
        monkeypatch.setenv("REDIS_HOST", "my-redis-server")

        cfg = DiggerConfig.from_env()

        assert cfg.redis_host == "redis://my-redis-server:6379/0"

    def test_config_is_frozen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DiggerConfig dataclass is frozen — attribute assignment raises."""
        self._set_required(monkeypatch)
        cfg = DiggerConfig.from_env()

        with pytest.raises((AttributeError, TypeError)):
            cfg.rate_budget_per_hour = 999  # type: ignore[misc]

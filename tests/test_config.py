"""Tests for config module."""

from pathlib import Path

import pytest

from common import ExtractorConfig, GraphinatorConfig, TableinatorConfig, setup_logging


class TestExtractorConfig:
    """Test ExtractorConfig class."""

    def test_from_env_with_all_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test configuration loading with all environment variables set."""
        monkeypatch.setenv("AMQP_CONNECTION", "amqp://user:pass@host:5672/")
        monkeypatch.setenv("DISCOGS_ROOT", "/custom/path")
        monkeypatch.setenv("PERIODIC_CHECK_DAYS", "30")

        config = ExtractorConfig.from_env()

        assert config.amqp_connection == "amqp://user:pass@host:5672/"
        assert config.discogs_root == Path("/custom/path")
        assert config.periodic_check_days == 30
        assert config.max_temp_size == int(1e9)  # Default value

    def test_from_env_missing_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test configuration loading with missing required variables."""
        monkeypatch.delenv("AMQP_CONNECTION", raising=False)

        with pytest.raises(ValueError, match="AMQP_CONNECTION environment variable is required"):
            ExtractorConfig.from_env()

    def test_from_env_with_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test configuration loading with default values."""
        monkeypatch.setenv("AMQP_CONNECTION", "amqp://localhost/")
        monkeypatch.delenv("DISCOGS_ROOT", raising=False)
        monkeypatch.delenv("PERIODIC_CHECK_DAYS", raising=False)

        config = ExtractorConfig.from_env()

        assert config.amqp_connection == "amqp://localhost/"
        assert config.discogs_root == Path("/discogs-data")
        assert config.periodic_check_days == 15

    def test_from_env_invalid_periodic_days(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test configuration with invalid periodic check days."""
        monkeypatch.setenv("AMQP_CONNECTION", "amqp://localhost/")
        monkeypatch.setenv("PERIODIC_CHECK_DAYS", "not-a-number")

        # Should use default value, not raise exception
        config = ExtractorConfig.from_env()
        assert config.periodic_check_days == 15


class TestGraphinatorConfig:
    """Test GraphinatorConfig class."""

    def test_from_env_with_all_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test configuration loading with all environment variables set."""
        monkeypatch.setenv("AMQP_CONNECTION", "amqp://user:pass@host:5672/")
        monkeypatch.setenv("NEO4J_ADDRESS", "bolt://neo4j:7687")
        monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "secret")

        config = GraphinatorConfig.from_env()

        assert config.amqp_connection == "amqp://user:pass@host:5672/"
        assert config.neo4j_address == "bolt://neo4j:7687"
        assert config.neo4j_username == "neo4j"
        assert config.neo4j_password == "secret"

    def test_from_env_missing_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test configuration loading with missing required variables."""
        monkeypatch.delenv("NEO4J_ADDRESS", raising=False)

        with pytest.raises(ValueError, match=r"Missing required environment variables.*NEO4J_ADDRESS"):
            GraphinatorConfig.from_env()


class TestTableinatorConfig:
    """Test TableinatorConfig class."""

    def test_from_env_with_all_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test configuration loading with all environment variables set."""
        monkeypatch.setenv("AMQP_CONNECTION", "amqp://user:pass@host:5672/")
        monkeypatch.setenv("POSTGRES_ADDRESS", "pghost:5432")
        monkeypatch.setenv("POSTGRES_USERNAME", "pguser")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pgpass")
        monkeypatch.setenv("POSTGRES_DATABASE", "mydb")

        config = TableinatorConfig.from_env()

        assert config.amqp_connection == "amqp://user:pass@host:5672/"
        assert config.postgres_address == "pghost:5432"
        assert config.postgres_username == "pguser"
        assert config.postgres_password == "pgpass"
        assert config.postgres_database == "mydb"

    def test_from_env_missing_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test configuration loading with missing required variables."""
        monkeypatch.delenv("POSTGRES_ADDRESS", raising=False)

        with pytest.raises(ValueError, match=r"Missing required environment variables.*POSTGRES_ADDRESS"):
            TableinatorConfig.from_env()


class TestSetupLogging:
    """Test setup_logging function."""

    def test_setup_logging_creates_file(self, tmp_path: Path) -> None:
        """Test that logging setup creates log file."""
        import logging

        # Reset logging config before test
        logging.root.handlers = []

        log_file = tmp_path / "test.log"
        setup_logging("test_service", log_file=log_file)

        # Get the logger after setup
        logger = logging.getLogger()
        logger.info("🧪 Test message")

        # Flush handlers to ensure data is written
        for handler in logger.handlers:
            handler.flush()

        assert log_file.exists()
        content = log_file.read_text()
        assert "Test message" in content
        assert "test_service" in content

    def test_setup_logging_without_file(self) -> None:
        """Test logging setup without file."""
        setup_logging("test_service")

        # Get the logger after setup
        import logging

        logger = logging.getLogger()

        # Should not raise exception
        logger.info("🧪 Test message without file")

    def test_setup_logging_reads_log_level_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that logging setup reads LOG_LEVEL environment variable."""
        import logging

        # Reset logging config before test
        logging.root.handlers = []

        # Set LOG_LEVEL environment variable
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        setup_logging("test_service")

        logger = logging.getLogger()
        assert logger.level == logging.DEBUG

    def test_setup_logging_defaults_to_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that logging defaults to INFO when LOG_LEVEL is not set."""
        import logging

        # Reset logging config before test
        logging.root.handlers = []

        # Ensure LOG_LEVEL is not set
        monkeypatch.delenv("LOG_LEVEL", raising=False)

        setup_logging("test_service")

        logger = logging.getLogger()
        assert logger.level == logging.INFO

    def test_setup_logging_explicit_level_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that explicit level parameter overrides LOG_LEVEL environment variable."""
        import logging

        # Reset logging config before test
        logging.root.handlers = []

        # Set LOG_LEVEL environment variable
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        # Pass explicit level
        setup_logging("test_service", level="WARNING")

        logger = logging.getLogger()
        assert logger.level == logging.WARNING

    def test_setup_logging_handles_lowercase_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that logging handles lowercase LOG_LEVEL values."""
        import logging

        # Reset logging config before test
        logging.root.handlers = []

        # Set LOG_LEVEL environment variable with lowercase
        monkeypatch.setenv("LOG_LEVEL", "error")

        setup_logging("test_service")

        logger = logging.getLogger()
        assert logger.level == logging.ERROR


class TestExtractorConfigEdgeCases:
    """Test ExtractorConfig edge cases for PERIODIC_CHECK_DAYS validation."""

    def test_periodic_check_days_zero_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test PERIODIC_CHECK_DAYS=0 is invalid and defaults to 15 (lines 46-49)."""
        monkeypatch.setenv("PERIODIC_CHECK_DAYS", "0")

        config = ExtractorConfig.from_env()
        assert config.periodic_check_days == 15

    def test_periodic_check_days_negative_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test negative PERIODIC_CHECK_DAYS defaults to 15 (lines 46-49)."""
        monkeypatch.setenv("PERIODIC_CHECK_DAYS", "-5")

        config = ExtractorConfig.from_env()
        assert config.periodic_check_days == 15


class TestGraphinatorConfigMissingVars:
    """Test GraphinatorConfig individual missing variable branches."""

    def test_missing_amqp_connection_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test AMQP_CONNECTION missing raises ValueError (line 81)."""
        monkeypatch.delenv("AMQP_CONNECTION", raising=False)

        with pytest.raises(ValueError, match="AMQP_CONNECTION"):
            GraphinatorConfig.from_env()

    def test_missing_neo4j_username_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test NEO4J_USERNAME missing raises ValueError (line 85)."""
        monkeypatch.delenv("NEO4J_USERNAME", raising=False)

        with pytest.raises(ValueError, match="NEO4J_USERNAME"):
            GraphinatorConfig.from_env()

    def test_missing_neo4j_password_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test NEO4J_PASSWORD missing raises ValueError (line 87)."""
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

        with pytest.raises(ValueError, match="NEO4J_PASSWORD"):
            GraphinatorConfig.from_env()


class TestTableinatorConfigMissingVars:
    """Test TableinatorConfig individual missing variable branches."""

    def test_missing_amqp_connection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test AMQP_CONNECTION missing raises ValueError (line 121)."""
        monkeypatch.delenv("AMQP_CONNECTION", raising=False)

        with pytest.raises(ValueError, match="AMQP_CONNECTION"):
            TableinatorConfig.from_env()

    def test_missing_postgres_username(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test POSTGRES_USERNAME missing raises ValueError (line 125)."""
        monkeypatch.delenv("POSTGRES_USERNAME", raising=False)

        with pytest.raises(ValueError, match="POSTGRES_USERNAME"):
            TableinatorConfig.from_env()

    def test_missing_postgres_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test POSTGRES_PASSWORD missing raises ValueError (line 127)."""
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

        with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
            TableinatorConfig.from_env()

    def test_missing_postgres_database(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test POSTGRES_DATABASE missing raises ValueError (line 129)."""
        monkeypatch.delenv("POSTGRES_DATABASE", raising=False)

        with pytest.raises(ValueError, match="POSTGRES_DATABASE"):
            TableinatorConfig.from_env()


class TestDashboardConfig:
    """Test DashboardConfig from_env with optional settings."""

    def test_cors_origins_parsed_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test CORS_ORIGINS is parsed as a comma-separated list (lines 326-328)."""
        from common import DashboardConfig

        monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://example.com, https://app.example.com")

        config = DashboardConfig.from_env()

        assert config.cors_origins == ["http://localhost:3000", "https://example.com", "https://app.example.com"]

    def test_cache_warming_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test CACHE_WARMING_ENABLED=false disables cache warming (line 331)."""
        from common import DashboardConfig

        monkeypatch.setenv("CACHE_WARMING_ENABLED", "false")

        config = DashboardConfig.from_env()

        assert config.cache_warming_enabled is False

    def test_cache_webhook_secret_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test CACHE_WEBHOOK_SECRET is read from environment (line 334)."""
        from common import DashboardConfig

        monkeypatch.setenv("CACHE_WEBHOOK_SECRET", "mysecret123")

        config = DashboardConfig.from_env()

        assert config.cache_webhook_secret == "mysecret123"

    def test_redis_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test custom REDIS_URL is read from environment (line 317)."""
        from common import DashboardConfig

        monkeypatch.setenv("REDIS_URL", "redis://myredis:6380/1")

        config = DashboardConfig.from_env()

        assert config.redis_url == "redis://myredis:6380/1"


class TestExploreConfig:
    """Test ExploreConfig from_env."""

    def test_from_env_with_all_vars(self) -> None:
        """Test ExploreConfig with all required vars."""
        from common import ExploreConfig

        config = ExploreConfig.from_env()

        assert config.neo4j_address == "bolt://localhost:7687"
        assert config.neo4j_username == "test"
        assert config.neo4j_password == "test"

    def test_missing_neo4j_address(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test NEO4J_ADDRESS missing raises ValueError (line 375)."""
        from common import ExploreConfig

        monkeypatch.delenv("NEO4J_ADDRESS", raising=False)

        with pytest.raises(ValueError, match="NEO4J_ADDRESS"):
            ExploreConfig.from_env()

    def test_missing_neo4j_username(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test NEO4J_USERNAME missing raises ValueError (line 377)."""
        from common import ExploreConfig

        monkeypatch.delenv("NEO4J_USERNAME", raising=False)

        with pytest.raises(ValueError, match="NEO4J_USERNAME"):
            ExploreConfig.from_env()

    def test_missing_neo4j_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test NEO4J_PASSWORD missing raises ValueError (line 379)."""
        from common import ExploreConfig

        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

        with pytest.raises(ValueError, match="NEO4J_PASSWORD"):
            ExploreConfig.from_env()


class TestGetConfig:
    """Test get_config() function."""

    def test_get_config_returns_dashboard_config(self) -> None:
        """Test that get_config() returns a DashboardConfig instance (line 396)."""
        from common import DashboardConfig, get_config

        config = get_config()

        assert isinstance(config, DashboardConfig)


class TestApiConfig:
    """Test ApiConfig.from_env."""

    def test_from_env_with_all_required_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ApiConfig with all required environment variables."""
        from common.config import ApiConfig

        monkeypatch.setenv("POSTGRES_ADDRESS", "pghost:5432")
        monkeypatch.setenv("POSTGRES_USERNAME", "pguser")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pgpass")
        monkeypatch.setenv("POSTGRES_DATABASE", "mydb")
        monkeypatch.setenv("JWT_SECRET_KEY", "supersecret123")

        config = ApiConfig.from_env()

        assert config.postgres_address == "pghost:5432"
        assert config.postgres_username == "pguser"
        assert config.postgres_password == "pgpass"
        assert config.postgres_database == "mydb"
        assert config.jwt_secret_key == "supersecret123"

    def test_from_env_optional_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ApiConfig optional fields have correct defaults."""
        from common.config import ApiConfig

        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("JWT_ALGORITHM", raising=False)
        monkeypatch.delenv("JWT_EXPIRE_MINUTES", raising=False)
        monkeypatch.delenv("DISCOGS_USER_AGENT", raising=False)

        config = ApiConfig.from_env()

        assert config.redis_url == "redis://redis:6379/0"
        assert config.jwt_algorithm == "HS256"
        assert config.jwt_expire_minutes == 30
        assert "discogsography" in config.discogs_user_agent

    def test_from_env_custom_optional_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ApiConfig reads optional env vars."""
        from common.config import ApiConfig

        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.setenv("REDIS_URL", "redis://myredis:6380/1")
        monkeypatch.setenv("JWT_ALGORITHM", "HS256")
        monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
        monkeypatch.setenv("DISCOGS_USER_AGENT", "CustomAgent/2.0")

        config = ApiConfig.from_env()

        assert config.redis_url == "redis://myredis:6380/1"
        assert config.jwt_expire_minutes == 60
        assert config.discogs_user_agent == "CustomAgent/2.0"

    def test_from_env_invalid_jwt_expire_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that invalid JWT_EXPIRE_MINUTES falls back to 30."""
        from common.config import ApiConfig

        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.setenv("JWT_EXPIRE_MINUTES", "not-a-number")

        config = ApiConfig.from_env()

        assert config.jwt_expire_minutes == 30

    def test_from_env_missing_postgres_address(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test missing POSTGRES_ADDRESS raises ValueError."""
        from common.config import ApiConfig

        monkeypatch.delenv("POSTGRES_ADDRESS", raising=False)
        monkeypatch.setenv("JWT_SECRET_KEY", "secret")

        with pytest.raises(ValueError, match="POSTGRES_ADDRESS"):
            ApiConfig.from_env()

    def test_from_env_missing_jwt_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test missing JWT_SECRET_KEY raises ValueError."""
        from common.config import ApiConfig

        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

        with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
            ApiConfig.from_env()

    def test_from_env_missing_multiple_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test missing multiple vars lists them all."""
        from common.config import ApiConfig

        monkeypatch.delenv("POSTGRES_USERNAME", raising=False)
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

        with pytest.raises(ValueError) as exc_info:
            ApiConfig.from_env()

        error_msg = str(exc_info.value)
        assert "POSTGRES_USERNAME" in error_msg
        assert "JWT_SECRET_KEY" in error_msg


class TestCuratorConfig:
    """Test CuratorConfig.from_env."""

    def test_from_env_with_all_required_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test CuratorConfig with all required environment variables."""
        from common.config import CuratorConfig

        monkeypatch.setenv("POSTGRES_ADDRESS", "pghost:5432")
        monkeypatch.setenv("POSTGRES_USERNAME", "pguser")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pgpass")
        monkeypatch.setenv("POSTGRES_DATABASE", "mydb")
        monkeypatch.setenv("NEO4J_ADDRESS", "bolt://neo4j:7687")
        monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "neo4jpass")
        monkeypatch.setenv("JWT_SECRET_KEY", "jwtsecret")

        config = CuratorConfig.from_env()

        assert config.postgres_address == "pghost:5432"
        assert config.neo4j_address == "bolt://neo4j:7687"
        assert config.jwt_secret_key == "jwtsecret"

    def test_from_env_missing_jwt_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test missing JWT_SECRET_KEY raises ValueError."""
        from common.config import CuratorConfig

        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

        with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
            CuratorConfig.from_env()

    def test_from_env_missing_neo4j_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test missing Neo4j vars raises ValueError."""
        from common.config import CuratorConfig

        monkeypatch.delenv("NEO4J_ADDRESS", raising=False)

        with pytest.raises(ValueError, match="NEO4J_ADDRESS"):
            CuratorConfig.from_env()

    def test_from_env_custom_user_agent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test custom DISCOGS_USER_AGENT is read."""
        from common.config import CuratorConfig

        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.setenv("DISCOGS_USER_AGENT", "MyAgent/3.0")

        config = CuratorConfig.from_env()

        assert config.discogs_user_agent == "MyAgent/3.0"

    def test_from_env_missing_postgres_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test missing POSTGRES_PASSWORD raises ValueError."""
        from common.config import CuratorConfig

        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

        with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
            CuratorConfig.from_env()


class TestOrjsonSerializer:
    """Test orjson_serializer function."""

    def test_serializes_simple_dict(self) -> None:
        from common.config import orjson_serializer

        result = orjson_serializer({"key": "value", "number": 42})
        import json

        data = json.loads(result)
        assert data["key"] == "value"
        assert data["number"] == 42

    def test_keys_are_sorted(self) -> None:
        from common.config import orjson_serializer

        result = orjson_serializer({"z": 1, "a": 2, "m": 3})
        # Keys should appear in sorted order
        assert result.index('"a"') < result.index('"m"') < result.index('"z"')

    def test_serializes_exception_as_string(self) -> None:
        from common.config import orjson_serializer

        exc = ValueError("something went wrong")
        result = orjson_serializer({"error": exc})
        import json

        data = json.loads(result)
        assert "ValueError" in data["error"]
        assert "something went wrong" in data["error"]

    def test_serializes_non_serializable_as_string(self) -> None:
        from common.config import orjson_serializer

        class CustomObj:
            def __str__(self) -> str:
                return "custom_repr"

        result = orjson_serializer({"obj": CustomObj()})
        import json

        data = json.loads(result)
        assert data["obj"] == "custom_repr"

    def test_returns_string(self) -> None:
        from common.config import orjson_serializer

        result = orjson_serializer({"x": 1})
        assert isinstance(result, str)


class TestApiConfigFromEnv:
    """Test ApiConfig.from_env NEO4J optional variable branches."""

    def test_from_env_without_neo4j_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Lines 406-408: NEO4J_* vars absent → neo4j fields are None."""
        monkeypatch.setenv("POSTGRES_ADDRESS", "localhost:5432")
        monkeypatch.setenv("POSTGRES_USERNAME", "pguser")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pgpass")
        monkeypatch.setenv("POSTGRES_DATABASE", "pgdb")
        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.delenv("NEO4J_ADDRESS", raising=False)
        monkeypatch.delenv("NEO4J_USERNAME", raising=False)
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

        from common.config import ApiConfig

        config = ApiConfig.from_env()
        assert config.neo4j_address is None
        assert config.neo4j_username is None
        assert config.neo4j_password is None

    def test_from_env_with_neo4j_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """NEO4J_* vars present → neo4j fields are populated."""
        monkeypatch.setenv("POSTGRES_ADDRESS", "localhost:5432")
        monkeypatch.setenv("POSTGRES_USERNAME", "pguser")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pgpass")
        monkeypatch.setenv("POSTGRES_DATABASE", "pgdb")
        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.setenv("NEO4J_ADDRESS", "bolt://neo4j:7687")
        monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "neo4jpass")

        from common.config import ApiConfig

        config = ApiConfig.from_env()
        assert config.neo4j_address == "bolt://neo4j:7687"
        assert config.neo4j_username == "neo4j"
        assert config.neo4j_password == "neo4jpass"

    def test_from_env_missing_required_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing required var raises ValueError."""
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.setenv("POSTGRES_ADDRESS", "localhost:5432")
        monkeypatch.setenv("POSTGRES_USERNAME", "pguser")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pgpass")
        monkeypatch.setenv("POSTGRES_DATABASE", "pgdb")

        from common.config import ApiConfig

        with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
            ApiConfig.from_env()

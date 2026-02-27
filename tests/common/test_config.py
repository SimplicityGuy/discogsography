"""Tests for config module."""

from pathlib import Path

import pytest

from common import ExtractorConfig, GraphinatorConfig, TableinatorConfig, setup_logging
from common.config import get_secret


class TestExtractorConfig:
    """Test ExtractorConfig class."""

    def test_from_env_with_all_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test configuration loading with all environment variables set."""
        monkeypatch.setenv("RABBITMQ_USERNAME", "user")
        monkeypatch.setenv("RABBITMQ_PASSWORD", "pass")
        monkeypatch.setenv("RABBITMQ_HOST", "host")
        monkeypatch.setenv("RABBITMQ_PORT", "5672")
        monkeypatch.setenv("DISCOGS_ROOT", "/custom/path")
        monkeypatch.setenv("PERIODIC_CHECK_DAYS", "30")

        config = ExtractorConfig.from_env()

        assert config.amqp_connection == "amqp://user:pass@host:5672/%2F"
        assert config.discogs_root == Path("/custom/path")
        assert config.periodic_check_days == 30
        assert config.max_temp_size == int(1e9)  # Default value

    def test_from_env_uses_credential_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test AMQP URL is built from defaults when credentials not set."""
        monkeypatch.delenv("RABBITMQ_USERNAME", raising=False)
        monkeypatch.delenv("RABBITMQ_PASSWORD", raising=False)
        monkeypatch.delenv("RABBITMQ_HOST", raising=False)
        monkeypatch.delenv("RABBITMQ_PORT", raising=False)

        config = ExtractorConfig.from_env()

        assert config.amqp_connection == "amqp://discogsography:discogsography@rabbitmq:5672/%2F"

    def test_from_env_with_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test configuration loading with default values."""
        monkeypatch.delenv("DISCOGS_ROOT", raising=False)
        monkeypatch.delenv("PERIODIC_CHECK_DAYS", raising=False)

        config = ExtractorConfig.from_env()

        assert config.discogs_root == Path("/discogs-data")
        assert config.periodic_check_days == 15

    def test_from_env_invalid_periodic_days(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test configuration with invalid periodic check days."""
        monkeypatch.setenv("PERIODIC_CHECK_DAYS", "not-a-number")

        # Should use default value, not raise exception
        config = ExtractorConfig.from_env()
        assert config.periodic_check_days == 15


class TestGraphinatorConfig:
    """Test GraphinatorConfig class."""

    def test_from_env_with_all_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test configuration loading with all environment variables set."""
        monkeypatch.setenv("RABBITMQ_USERNAME", "user")
        monkeypatch.setenv("RABBITMQ_PASSWORD", "pass")
        monkeypatch.setenv("RABBITMQ_HOST", "host")
        monkeypatch.setenv("RABBITMQ_PORT", "5672")
        monkeypatch.setenv("NEO4J_ADDRESS", "bolt://neo4j:7687")
        monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "secret")

        config = GraphinatorConfig.from_env()

        assert config.amqp_connection == "amqp://user:pass@host:5672/%2F"
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
        monkeypatch.setenv("RABBITMQ_USERNAME", "user")
        monkeypatch.setenv("RABBITMQ_PASSWORD", "pass")
        monkeypatch.setenv("RABBITMQ_HOST", "host")
        monkeypatch.setenv("RABBITMQ_PORT", "5672")
        monkeypatch.setenv("POSTGRES_ADDRESS", "pghost:5432")
        monkeypatch.setenv("POSTGRES_USERNAME", "pguser")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pgpass")
        monkeypatch.setenv("POSTGRES_DATABASE", "mydb")

        config = TableinatorConfig.from_env()

        assert config.amqp_connection == "amqp://user:pass@host:5672/%2F"
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

    def test_amqp_url_built_from_env_components(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test AMQP URL is constructed from RABBITMQ_USERNAME/PASSWORD/HOST/PORT."""
        monkeypatch.setenv("RABBITMQ_USERNAME", "myuser")
        monkeypatch.setenv("RABBITMQ_PASSWORD", "mypass")
        monkeypatch.setenv("RABBITMQ_HOST", "myrabbitmq")
        monkeypatch.setenv("RABBITMQ_PORT", "5673")

        config = GraphinatorConfig.from_env()

        assert config.amqp_connection == "amqp://myuser:mypass@myrabbitmq:5673/%2F"

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

    def test_amqp_url_built_from_env_components(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test AMQP URL is constructed from RABBITMQ_USERNAME/PASSWORD/HOST/PORT."""
        monkeypatch.setenv("RABBITMQ_USERNAME", "myuser")
        monkeypatch.setenv("RABBITMQ_PASSWORD", "mypass")
        monkeypatch.setenv("RABBITMQ_HOST", "myrabbitmq")
        monkeypatch.setenv("RABBITMQ_PORT", "5673")

        config = TableinatorConfig.from_env()

        assert config.amqp_connection == "amqp://myuser:mypass@myrabbitmq:5673/%2F"

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

        config = CuratorConfig.from_env()

        assert config.postgres_address == "pghost:5432"
        assert config.neo4j_address == "bolt://neo4j:7687"

    def test_from_env_missing_neo4j_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test missing Neo4j vars raises ValueError."""
        from common.config import CuratorConfig

        monkeypatch.delenv("NEO4J_ADDRESS", raising=False)

        with pytest.raises(ValueError, match="NEO4J_ADDRESS"):
            CuratorConfig.from_env()

    def test_from_env_custom_user_agent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test custom DISCOGS_USER_AGENT is read."""
        from common.config import CuratorConfig

        monkeypatch.setenv("DISCOGS_USER_AGENT", "MyAgent/3.0")

        config = CuratorConfig.from_env()

        assert config.discogs_user_agent == "MyAgent/3.0"

    def test_from_env_missing_postgres_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test missing POSTGRES_PASSWORD raises ValueError."""
        from common.config import CuratorConfig

        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

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


class TestApiConfigNewFields:
    """Tests for new ApiConfig fields added in the security hardening."""

    def test_snapshot_ttl_days_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from common.config import ApiConfig

        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.delenv("SNAPSHOT_TTL_DAYS", raising=False)
        assert ApiConfig.from_env().snapshot_ttl_days == 28

    def test_snapshot_ttl_days_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from common.config import ApiConfig

        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.setenv("SNAPSHOT_TTL_DAYS", "14")
        assert ApiConfig.from_env().snapshot_ttl_days == 14

    def test_snapshot_ttl_days_invalid_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from common.config import ApiConfig

        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.setenv("SNAPSHOT_TTL_DAYS", "not-a-number")
        assert ApiConfig.from_env().snapshot_ttl_days == 28

    def test_snapshot_max_nodes_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from common.config import ApiConfig

        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.delenv("SNAPSHOT_MAX_NODES", raising=False)
        assert ApiConfig.from_env().snapshot_max_nodes == 100

    def test_snapshot_max_nodes_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from common.config import ApiConfig

        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.setenv("SNAPSHOT_MAX_NODES", "50")
        assert ApiConfig.from_env().snapshot_max_nodes == 50

    def test_snapshot_max_nodes_invalid_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from common.config import ApiConfig

        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.setenv("SNAPSHOT_MAX_NODES", "bad")
        assert ApiConfig.from_env().snapshot_max_nodes == 100

    def test_oauth_encryption_key_none_when_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from common.config import ApiConfig

        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.delenv("OAUTH_ENCRYPTION_KEY", raising=False)
        assert ApiConfig.from_env().oauth_encryption_key is None

    def test_oauth_encryption_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from common.config import ApiConfig

        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.setenv("OAUTH_ENCRYPTION_KEY", "my-fernet-key")
        assert ApiConfig.from_env().oauth_encryption_key == "my-fernet-key"

    def test_jwt_algorithm_non_hs256_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from common.config import ApiConfig

        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.setenv("JWT_ALGORITHM", "RS256")
        with pytest.raises(ValueError, match="Unsupported JWT algorithm"):
            ApiConfig.from_env()

    def test_cors_origins_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from common.config import ApiConfig

        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com,https://other.example.com")
        config = ApiConfig.from_env()
        assert config.cors_origins == ["https://app.example.com", "https://other.example.com"]

    def test_cors_origins_none_when_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from common.config import ApiConfig

        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        assert ApiConfig.from_env().cors_origins is None


class TestCuratorConfigNoJwtRequired:
    """CuratorConfig no longer requires JWT_SECRET_KEY."""

    def test_curator_config_works_without_jwt_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from common.config import CuratorConfig

        monkeypatch.setenv("POSTGRES_ADDRESS", "pghost:5432")
        monkeypatch.setenv("POSTGRES_USERNAME", "pguser")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pgpass")
        monkeypatch.setenv("POSTGRES_DATABASE", "mydb")
        monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost/")
        monkeypatch.setenv("NEO4J_ADDRESS", "bolt://localhost:7687")
        monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "password")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        # Should not raise
        config = CuratorConfig.from_env()
        assert not hasattr(config, "jwt_secret_key") or config.jwt_secret_key is None  # type: ignore[attr-defined]


class TestConfigMissingVars:
    """Tests for individual missing-variable branches in ApiConfig and CuratorConfig."""

    def test_api_config_missing_postgres_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """config.py:390 — POSTGRES_PASSWORD missing fires the append."""
        from common.config import ApiConfig

        monkeypatch.setenv("POSTGRES_ADDRESS", "localhost")
        monkeypatch.setenv("POSTGRES_USERNAME", "user")
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        monkeypatch.setenv("POSTGRES_DATABASE", "db")
        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
            ApiConfig.from_env()

    def test_api_config_missing_postgres_database(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """config.py:392 — POSTGRES_DATABASE missing fires the append."""
        from common.config import ApiConfig

        monkeypatch.setenv("POSTGRES_ADDRESS", "localhost")
        monkeypatch.setenv("POSTGRES_USERNAME", "user")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pass")
        monkeypatch.delenv("POSTGRES_DATABASE", raising=False)
        monkeypatch.setenv("JWT_SECRET_KEY", "secret")
        with pytest.raises(ValueError, match="POSTGRES_DATABASE"):
            ApiConfig.from_env()

    def test_curator_config_missing_postgres_address(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """config.py:480 — POSTGRES_ADDRESS missing."""
        from common.config import CuratorConfig

        monkeypatch.delenv("POSTGRES_ADDRESS", raising=False)
        monkeypatch.setenv("POSTGRES_USERNAME", "user")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pass")
        monkeypatch.setenv("POSTGRES_DATABASE", "db")
        monkeypatch.setenv("NEO4J_ADDRESS", "bolt://localhost")
        monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "neo4jpass")
        with pytest.raises(ValueError, match="POSTGRES_ADDRESS"):
            CuratorConfig.from_env()

    def test_curator_config_missing_postgres_username(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """config.py:482 — POSTGRES_USERNAME missing."""
        from common.config import CuratorConfig

        monkeypatch.setenv("POSTGRES_ADDRESS", "localhost")
        monkeypatch.delenv("POSTGRES_USERNAME", raising=False)
        monkeypatch.setenv("POSTGRES_PASSWORD", "pass")
        monkeypatch.setenv("POSTGRES_DATABASE", "db")
        monkeypatch.setenv("NEO4J_ADDRESS", "bolt://localhost")
        monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "neo4jpass")
        with pytest.raises(ValueError, match="POSTGRES_USERNAME"):
            CuratorConfig.from_env()

    def test_curator_config_missing_postgres_database(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """config.py:486 — POSTGRES_DATABASE missing."""
        from common.config import CuratorConfig

        monkeypatch.setenv("POSTGRES_ADDRESS", "localhost")
        monkeypatch.setenv("POSTGRES_USERNAME", "user")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pass")
        monkeypatch.delenv("POSTGRES_DATABASE", raising=False)
        monkeypatch.setenv("NEO4J_ADDRESS", "bolt://localhost")
        monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "neo4jpass")
        with pytest.raises(ValueError, match="POSTGRES_DATABASE"):
            CuratorConfig.from_env()

    def test_curator_config_missing_neo4j_username(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """config.py:490 — NEO4J_USERNAME missing."""
        from common.config import CuratorConfig

        monkeypatch.setenv("POSTGRES_ADDRESS", "localhost")
        monkeypatch.setenv("POSTGRES_USERNAME", "user")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pass")
        monkeypatch.setenv("POSTGRES_DATABASE", "db")
        monkeypatch.setenv("NEO4J_ADDRESS", "bolt://localhost")
        monkeypatch.delenv("NEO4J_USERNAME", raising=False)
        monkeypatch.setenv("NEO4J_PASSWORD", "neo4jpass")
        with pytest.raises(ValueError, match="NEO4J_USERNAME"):
            CuratorConfig.from_env()

    def test_curator_config_missing_neo4j_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """config.py:492 — NEO4J_PASSWORD missing."""
        from common.config import CuratorConfig

        monkeypatch.setenv("POSTGRES_ADDRESS", "localhost")
        monkeypatch.setenv("POSTGRES_USERNAME", "user")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pass")
        monkeypatch.setenv("POSTGRES_DATABASE", "db")
        monkeypatch.setenv("NEO4J_ADDRESS", "bolt://localhost")
        monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
        with pytest.raises(ValueError, match="NEO4J_PASSWORD"):
            CuratorConfig.from_env()


class TestGetSecret:
    """Test get_secret() helper for Docker Compose runtime secrets."""

    def test_reads_from_file_when_file_env_set(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Returns file contents when <VAR>_FILE is set to a valid path."""
        secret_file = tmp_path / "my_secret.txt"
        secret_file.write_text("supersecret\n")
        monkeypatch.setenv("MY_VAR_FILE", str(secret_file))
        monkeypatch.delenv("MY_VAR", raising=False)

        result = get_secret("MY_VAR")

        assert result == "supersecret"

    def test_falls_back_to_plain_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns plain env var value when no <VAR>_FILE is set."""
        monkeypatch.delenv("MY_VAR_FILE", raising=False)
        monkeypatch.setenv("MY_VAR", "plainvalue")

        result = get_secret("MY_VAR")

        assert result == "plainvalue"

    def test_returns_none_when_neither_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when neither <VAR>_FILE nor <VAR> is set and no default."""
        monkeypatch.delenv("MY_VAR_FILE", raising=False)
        monkeypatch.delenv("MY_VAR", raising=False)

        result = get_secret("MY_VAR")

        assert result is None

    def test_returns_default_when_neither_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns default value when neither <VAR>_FILE nor <VAR> is set."""
        monkeypatch.delenv("MY_VAR_FILE", raising=False)
        monkeypatch.delenv("MY_VAR", raising=False)

        result = get_secret("MY_VAR", "mydefault")

        assert result == "mydefault"

    def test_raises_value_error_for_missing_secret_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Raises ValueError when <VAR>_FILE points to a non-existent file."""
        monkeypatch.setenv("MY_VAR_FILE", str(tmp_path / "nonexistent.txt"))
        monkeypatch.delenv("MY_VAR", raising=False)

        with pytest.raises(ValueError, match="Cannot read secret file for MY_VAR"):
            get_secret("MY_VAR")


class TestGetSecretViaFromEnv:
    """Test that get_secret() _FILE paths work end-to-end through config from_env() methods.

    These tests exercise the _FILE branch at each call site, complementing
    TestGetSecret which tests the helper function in isolation.
    """

    def test_graphinator_config_reads_credentials_from_files(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """GraphinatorConfig reads NEO4J_USERNAME and NEO4J_PASSWORD via _FILE."""
        username_file = tmp_path / "neo4j_user.txt"
        password_file = tmp_path / "neo4j_pass.txt"
        username_file.write_text("graph_user\n")
        password_file.write_text("graph_pass\n")

        monkeypatch.setenv("NEO4J_ADDRESS", "bolt://localhost:7687")
        monkeypatch.setenv("NEO4J_USERNAME_FILE", str(username_file))
        monkeypatch.setenv("NEO4J_PASSWORD_FILE", str(password_file))
        monkeypatch.delenv("NEO4J_USERNAME", raising=False)
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

        from common.config import GraphinatorConfig

        config = GraphinatorConfig.from_env()
        assert config.neo4j_username == "graph_user"
        assert config.neo4j_password == "graph_pass"

    def test_tableinator_config_reads_credentials_from_files(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """TableinatorConfig reads POSTGRES_USERNAME and POSTGRES_PASSWORD via _FILE."""
        user_file = tmp_path / "pg_user.txt"
        pass_file = tmp_path / "pg_pass.txt"
        user_file.write_text("table_user\n")
        pass_file.write_text("table_pass\n")

        monkeypatch.setenv("POSTGRES_ADDRESS", "localhost:5432")
        monkeypatch.setenv("POSTGRES_USERNAME_FILE", str(user_file))
        monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(pass_file))
        monkeypatch.setenv("POSTGRES_DATABASE", "mydb")
        monkeypatch.delenv("POSTGRES_USERNAME", raising=False)
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

        from common.config import TableinatorConfig

        config = TableinatorConfig.from_env()
        assert config.postgres_username == "table_user"
        assert config.postgres_password == "table_pass"

    def test_api_config_reads_credentials_from_files(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """ApiConfig reads POSTGRES_USERNAME, POSTGRES_PASSWORD, JWT_SECRET_KEY, and OAUTH_ENCRYPTION_KEY via _FILE."""
        user_file = tmp_path / "pg_user.txt"
        pass_file = tmp_path / "pg_pass.txt"
        jwt_file = tmp_path / "jwt.txt"
        oauth_file = tmp_path / "oauth.txt"
        user_file.write_text("api_user\n")
        pass_file.write_text("api_pass\n")
        jwt_file.write_text("api_jwt_secret\n")
        oauth_file.write_text("api_fernet_key\n")

        monkeypatch.setenv("POSTGRES_ADDRESS", "localhost:5432")
        monkeypatch.setenv("POSTGRES_USERNAME_FILE", str(user_file))
        monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(pass_file))
        monkeypatch.setenv("POSTGRES_DATABASE", "mydb")
        monkeypatch.setenv("JWT_SECRET_KEY_FILE", str(jwt_file))
        monkeypatch.setenv("OAUTH_ENCRYPTION_KEY_FILE", str(oauth_file))
        monkeypatch.delenv("POSTGRES_USERNAME", raising=False)
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("OAUTH_ENCRYPTION_KEY", raising=False)

        from common.config import ApiConfig

        config = ApiConfig.from_env()
        assert config.postgres_username == "api_user"
        assert config.postgres_password == "api_pass"
        assert config.jwt_secret_key == "api_jwt_secret"
        assert config.oauth_encryption_key == "api_fernet_key"

    def test_curator_config_reads_credentials_from_files(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """CuratorConfig reads POSTGRES and NEO4J credentials via _FILE."""
        pg_user_file = tmp_path / "pg_user.txt"
        pg_pass_file = tmp_path / "pg_pass.txt"
        neo_user_file = tmp_path / "neo_user.txt"
        neo_pass_file = tmp_path / "neo_pass.txt"
        pg_user_file.write_text("cur_pg_user\n")
        pg_pass_file.write_text("cur_pg_pass\n")
        neo_user_file.write_text("cur_neo_user\n")
        neo_pass_file.write_text("cur_neo_pass\n")

        monkeypatch.setenv("POSTGRES_ADDRESS", "localhost:5432")
        monkeypatch.setenv("POSTGRES_USERNAME_FILE", str(pg_user_file))
        monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(pg_pass_file))
        monkeypatch.setenv("POSTGRES_DATABASE", "mydb")
        monkeypatch.setenv("NEO4J_ADDRESS", "bolt://localhost:7687")
        monkeypatch.setenv("NEO4J_USERNAME_FILE", str(neo_user_file))
        monkeypatch.setenv("NEO4J_PASSWORD_FILE", str(neo_pass_file))
        monkeypatch.delenv("POSTGRES_USERNAME", raising=False)
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        monkeypatch.delenv("NEO4J_USERNAME", raising=False)
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

        from common.config import CuratorConfig

        config = CuratorConfig.from_env()
        assert config.postgres_username == "cur_pg_user"
        assert config.postgres_password == "cur_pg_pass"
        assert config.neo4j_username == "cur_neo_user"
        assert config.neo4j_password == "cur_neo_pass"

    def test_explore_config_reads_credentials_from_files(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """ExploreConfig reads NEO4J credentials and JWT key via _FILE."""
        neo_user_file = tmp_path / "neo_user.txt"
        neo_pass_file = tmp_path / "neo_pass.txt"
        jwt_file = tmp_path / "jwt.txt"
        neo_user_file.write_text("exp_neo_user\n")
        neo_pass_file.write_text("exp_neo_pass\n")
        jwt_file.write_text("exp_jwt_secret\n")

        monkeypatch.setenv("NEO4J_ADDRESS", "bolt://localhost:7687")
        monkeypatch.setenv("NEO4J_USERNAME_FILE", str(neo_user_file))
        monkeypatch.setenv("NEO4J_PASSWORD_FILE", str(neo_pass_file))
        monkeypatch.setenv("JWT_SECRET_KEY_FILE", str(jwt_file))
        monkeypatch.delenv("NEO4J_USERNAME", raising=False)
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

        from common.config import ExploreConfig

        config = ExploreConfig.from_env()
        assert config.neo4j_username == "exp_neo_user"
        assert config.neo4j_password == "exp_neo_pass"
        assert config.jwt_secret_key == "exp_jwt_secret"

    def test_dashboard_config_reads_rabbitmq_credentials_from_files(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """DashboardConfig reads RABBITMQ_USERNAME and RABBITMQ_PASSWORD via _FILE."""
        user_file = tmp_path / "rmq_user.txt"
        pass_file = tmp_path / "rmq_pass.txt"
        user_file.write_text("dash_rmq_user\n")
        pass_file.write_text("dash_rmq_pass\n")

        monkeypatch.setenv("RABBITMQ_USERNAME_FILE", str(user_file))
        monkeypatch.setenv("RABBITMQ_PASSWORD_FILE", str(pass_file))
        monkeypatch.delenv("RABBITMQ_USERNAME", raising=False)
        monkeypatch.delenv("RABBITMQ_PASSWORD", raising=False)

        from common.config import DashboardConfig

        config = DashboardConfig.from_env()
        assert config.rabbitmq_username == "dash_rmq_user"
        assert config.rabbitmq_password == "dash_rmq_pass"

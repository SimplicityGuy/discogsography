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

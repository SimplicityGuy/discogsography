"""Integration tests for discogsography services."""


class TestServiceIntegration:
    """Test service integration and configuration."""

    def test_extractor_import(self) -> None:
        """Test that extractor can be imported with proper env vars."""
        # Services should be importable when env vars are set
        import extractor.extractor

        assert hasattr(extractor.extractor, "main")

    def test_graphinator_import_requires_config(self) -> None:
        """Test that graphinator requires configuration."""
        # Should be importable now that config is not initialized at module level
        import graphinator.graphinator

        assert hasattr(graphinator.graphinator, "main")

    def test_tableinator_import_requires_config(self) -> None:
        """Test that tableinator requires configuration."""
        # Should be importable now that config is not initialized at module level
        import tableinator.tableinator

        assert hasattr(tableinator.tableinator, "main")

    def test_extractor_has_main_function(self) -> None:
        """Test extractor has main function."""
        from extractor.extractor import main

        # Should have main function
        assert callable(main)

    def test_service_configs_consistent(self) -> None:
        """Test that all services use consistent configuration."""
        from config import AMQP_EXCHANGE, AMQP_EXCHANGE_TYPE, DATA_TYPES

        # Verify shared constants
        assert AMQP_EXCHANGE == "discogsography-exchange"
        assert AMQP_EXCHANGE_TYPE == "topic"
        assert DATA_TYPES == ["artists", "labels", "masters", "releases"]

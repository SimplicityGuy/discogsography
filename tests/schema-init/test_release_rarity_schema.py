"""Tests for release_rarity schema definition."""

from postgres_schema import _INSIGHTS_TABLES


class TestReleaseRaritySchema:
    def test_release_rarity_table_defined(self) -> None:
        """Verify release_rarity table exists in _INSIGHTS_TABLES."""
        names = [name for name, _ddl in _INSIGHTS_TABLES]
        assert "insights.release_rarity table" in names

    def test_release_rarity_score_index_defined(self) -> None:
        """Verify rarity_score descending index exists."""
        names = [name for name, _ddl in _INSIGHTS_TABLES]
        assert "idx_release_rarity_score" in names

    def test_release_rarity_tier_index_defined(self) -> None:
        """Verify tier index exists."""
        names = [name for name, _ddl in _INSIGHTS_TABLES]
        assert "idx_release_rarity_tier" in names

    def test_release_rarity_gem_index_defined(self) -> None:
        """Verify hidden_gem_score index exists."""
        names = [name for name, _ddl in _INSIGHTS_TABLES]
        assert "idx_release_rarity_gem" in names

    def test_release_rarity_ddl_has_required_columns(self) -> None:
        """Verify DDL includes all required columns."""
        ddl = ""
        for name, stmt in _INSIGHTS_TABLES:
            if name == "insights.release_rarity table":
                ddl = stmt
                break
        for col in [
            "release_id",
            "title",
            "artist_name",
            "year",
            "rarity_score",
            "tier",
            "hidden_gem_score",
            "pressing_scarcity",
            "label_catalog",
            "format_rarity",
            "temporal_scarcity",
            "graph_isolation",
            "computed_at",
        ]:
            assert col in ddl, f"Column {col} missing from DDL"

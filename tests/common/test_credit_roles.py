"""Tests for credit role taxonomy."""

from common.credit_roles import ALL_CATEGORIES, ROLE_CATEGORIES, categorize_role


class TestCategorizeRole:
    """Test the categorize_role function."""

    def test_exact_match_producer(self) -> None:
        assert categorize_role("Producer") == "production"

    def test_exact_match_mastered_by(self) -> None:
        assert categorize_role("Mastered By") == "mastering"

    def test_exact_match_engineer(self) -> None:
        assert categorize_role("Engineer") == "engineering"

    def test_exact_match_guitar(self) -> None:
        assert categorize_role("Guitar") == "session"

    def test_exact_match_artwork(self) -> None:
        assert categorize_role("Artwork") == "design"

    def test_exact_match_management(self) -> None:
        assert categorize_role("Management") == "management"

    def test_case_insensitive(self) -> None:
        assert categorize_role("PRODUCER") == "production"
        assert categorize_role("mastered by") == "mastering"

    def test_substring_match(self) -> None:
        assert categorize_role("Recorded By, Mixed By") == "engineering"

    def test_unknown_role(self) -> None:
        assert categorize_role("Unknown Role") == "other"

    def test_empty_string(self) -> None:
        assert categorize_role("") == "other"

    def test_whitespace_handling(self) -> None:
        assert categorize_role("  Producer  ") == "production"

    def test_executive_producer(self) -> None:
        assert categorize_role("Executive Producer") == "production"

    def test_mixed_by(self) -> None:
        assert categorize_role("Mixed By") == "engineering"

    def test_lacquer_cut_by(self) -> None:
        assert categorize_role("Lacquer Cut By") == "mastering"

    def test_bass(self) -> None:
        assert categorize_role("Bass") == "session"

    def test_photography(self) -> None:
        assert categorize_role("Photography") == "design"

    def test_a_and_r(self) -> None:
        assert categorize_role("A&R") == "management"

    def test_remastered_by(self) -> None:
        assert categorize_role("Remastered By") == "mastering"

    def test_remix(self) -> None:
        assert categorize_role("Remix") == "engineering"


class TestAllCategories:
    """Test the ALL_CATEGORIES constant."""

    def test_includes_other(self) -> None:
        assert "other" in ALL_CATEGORIES

    def test_includes_all_defined_categories(self) -> None:
        for cat in ROLE_CATEGORIES:
            assert cat in ALL_CATEGORIES

    def test_length(self) -> None:
        assert len(ALL_CATEGORIES) == 7


class TestRoleCategories:
    """Test the ROLE_CATEGORIES dict."""

    def test_production_has_producer(self) -> None:
        assert "producer" in ROLE_CATEGORIES["production"]

    def test_engineering_has_engineer(self) -> None:
        assert "engineer" in ROLE_CATEGORIES["engineering"]

    def test_mastering_has_mastered_by(self) -> None:
        assert "mastered by" in ROLE_CATEGORIES["mastering"]

    def test_session_has_guitar(self) -> None:
        assert "guitar" in ROLE_CATEGORIES["session"]

    def test_design_has_artwork(self) -> None:
        assert "artwork" in ROLE_CATEGORIES["design"]

    def test_management_has_a_and_r(self) -> None:
        assert "a&r" in ROLE_CATEGORIES["management"]

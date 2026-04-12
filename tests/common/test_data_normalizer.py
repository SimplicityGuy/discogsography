from common.data_normalizer import (
    _parse_year_int,
    normalize_record,
)


class TestParseYearInt:
    """Test _parse_year_int function."""

    def test_none_returns_none(self) -> None:
        assert _parse_year_int(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_year_int("") is None

    def test_zero_returns_none(self) -> None:
        assert _parse_year_int(0) is None

    def test_zero_string_returns_none(self) -> None:
        assert _parse_year_int("0") is None

    def test_valid_year_int(self) -> None:
        assert _parse_year_int(1969) == 1969

    def test_valid_year_string(self) -> None:
        assert _parse_year_int("1969") == 1969

    def test_date_string(self) -> None:
        assert _parse_year_int("1969-09-26") == 1969

    def test_partial_date_string(self) -> None:
        assert _parse_year_int("1969-00-00") == 1969

    def test_invalid_string(self) -> None:
        assert _parse_year_int("Unknown") is None

    def test_whitespace_string(self) -> None:
        assert _parse_year_int("   ") is None


class TestNormalizeRecord:
    """Test normalize_record function."""

    def test_artists_passthrough(self) -> None:
        """Artists don't need year parsing — data passes through."""
        data = {"id": "1", "name": "Test", "sha256": "abc"}
        result = normalize_record("artists", data)
        assert result["id"] == "1"
        assert result["name"] == "Test"

    def test_labels_passthrough(self) -> None:
        """Labels don't need year parsing — data passes through."""
        data = {"id": "1", "name": "Test Label", "sha256": "abc"}
        result = normalize_record("labels", data)
        assert result["id"] == "1"

    def test_masters_year_parsing(self) -> None:
        """Masters parse year from the 'year' field."""
        data = {"id": "1", "title": "Test", "year": "1969", "sha256": "abc"}
        result = normalize_record("masters", data)
        assert result["year"] == 1969

    def test_masters_year_none(self) -> None:
        """Masters with no year field get year=None."""
        data = {"id": "1", "title": "Test", "sha256": "abc"}
        result = normalize_record("masters", data)
        assert result["year"] is None

    def test_releases_year_from_released(self) -> None:
        """Releases parse year from the 'released' field."""
        data = {"id": "1", "title": "Test", "released": "1969-09-26", "sha256": "abc"}
        result = normalize_record("releases", data)
        assert result["year"] == 1969

    def test_releases_no_released_field(self) -> None:
        """Releases with no released field get year=None."""
        data = {"id": "1", "title": "Test", "sha256": "abc"}
        result = normalize_record("releases", data)
        assert result["year"] is None

    def test_unknown_type_passthrough(self) -> None:
        """Unknown types pass through unchanged."""
        data = {"id": "1", "custom": "field"}
        result = normalize_record("unknown", data)
        assert result == {"id": "1", "custom": "field"}

"""Tests for data normalization utilities."""

from common.data_normalizer import (
    ensure_list,
    normalize_artist,
    normalize_id,
    normalize_item_with_id,
    normalize_label,
    normalize_master,
    normalize_nested_list,
    normalize_record,
    normalize_release,
    normalize_text,
)


class TestNormalizeId:
    """Test normalize_id function."""

    def test_string_id(self) -> None:
        """Test extracting ID from a string."""
        assert normalize_id("123") == "123"

    def test_dict_with_id(self) -> None:
        """Test extracting ID from dict with 'id' key."""
        assert normalize_id({"id": "123", "name": "Test"}) == "123"

    def test_dict_with_at_id(self) -> None:
        """Test extracting ID from dict with '@id' key (xmltodict format)."""
        assert normalize_id({"@id": "456", "name": "Test"}) == "456"

    def test_dict_prefers_id_over_at_id(self) -> None:
        """Test that 'id' is preferred over '@id'."""
        assert normalize_id({"id": "123", "@id": "456"}) == "123"

    def test_none_input(self) -> None:
        """Test handling None input."""
        assert normalize_id(None) is None

    def test_dict_without_id(self) -> None:
        """Test dict without ID returns None."""
        assert normalize_id({"name": "Test"}) is None


class TestNormalizeText:
    """Test normalize_text function."""

    def test_string_input(self) -> None:
        """Test string input returns as-is."""
        assert normalize_text("Hello") == "Hello"

    def test_dict_with_text(self) -> None:
        """Test extracting text from dict with '#text' key."""
        assert normalize_text({"#text": "Content", "@id": "123"}) == "Content"

    def test_none_input(self) -> None:
        """Test handling None input."""
        assert normalize_text(None) is None

    def test_dict_without_text(self) -> None:
        """Test dict without text returns None."""
        assert normalize_text({"id": "123"}) is None


class TestEnsureList:
    """Test ensure_list function."""

    def test_none_returns_empty_list(self) -> None:
        """Test None input returns empty list."""
        assert ensure_list(None) == []

    def test_list_returns_as_is(self) -> None:
        """Test list input returns as-is."""
        assert ensure_list([1, 2, 3]) == [1, 2, 3]

    def test_single_item_becomes_list(self) -> None:
        """Test single item is wrapped in a list."""
        assert ensure_list("item") == ["item"]
        assert ensure_list({"key": "value"}) == [{"key": "value"}]


class TestNormalizeNestedList:
    """Test normalize_nested_list function."""

    def test_nested_dict_format(self) -> None:
        """Test extracting from nested dict format (xmltodict)."""
        container = {"artist": [{"id": "1"}, {"id": "2"}]}
        result = normalize_nested_list(container, "artist")
        assert result == [{"id": "1"}, {"id": "2"}]

    def test_nested_dict_single_item(self) -> None:
        """Test extracting single item becomes a list."""
        container = {"artist": {"id": "1"}}
        result = normalize_nested_list(container, "artist")
        assert result == [{"id": "1"}]

    def test_flat_list_format(self) -> None:
        """Test flat list format (old rustextractor)."""
        container = ["Artist 1", "Artist 2"]
        result = normalize_nested_list(container, "artist")
        assert result == ["Artist 1", "Artist 2"]

    def test_none_container(self) -> None:
        """Test None container returns empty list."""
        assert normalize_nested_list(None, "artist") == []

    def test_missing_key(self) -> None:
        """Test missing key returns empty list."""
        container = {"other": "value"}
        assert normalize_nested_list(container, "artist") == []


class TestNormalizeItemWithId:
    """Test normalize_item_with_id function."""

    def test_string_becomes_id_dict(self) -> None:
        """Test string is converted to dict with id."""
        result = normalize_item_with_id("123")
        assert result == {"id": "123"}

    def test_dict_with_id_preserved(self) -> None:
        """Test dict with 'id' key is preserved."""
        result = normalize_item_with_id({"id": "123", "name": "Test"})
        assert result == {"id": "123", "name": "Test"}

    def test_at_id_converted(self) -> None:
        """Test '@id' is converted to 'id'."""
        result = normalize_item_with_id({"@id": "123", "@name": "Test"})
        assert result == {"id": "123", "name": "Test"}

    def test_text_content_extracted(self) -> None:
        """Test '#text' is converted to 'name'."""
        result = normalize_item_with_id({"id": "123", "#text": "John Lennon"})
        assert result == {"id": "123", "name": "John Lennon"}

    def test_no_id_returns_none(self) -> None:
        """Test dict without ID returns None."""
        result = normalize_item_with_id({"name": "Test"})
        assert result is None

    def test_none_input(self) -> None:
        """Test None input returns None."""
        assert normalize_item_with_id(None) is None


class TestNormalizeArtist:
    """Test normalize_artist function."""

    def test_basic_artist(self) -> None:
        """Test normalizing a basic artist."""
        artist_data = {
            "id": "123",
            "name": "The Beatles",
            "sha256": "abc123",
        }
        result = normalize_artist(artist_data)
        assert result["id"] == "123"
        assert result["name"] == "The Beatles"
        assert result["sha256"] == "abc123"

    def test_artist_with_members(self) -> None:
        """Test normalizing artist with members (xmltodict format)."""
        artist_data = {
            "id": "123",
            "name": "The Beatles",
            "sha256": "abc123",
            "members": {
                "name": [
                    {"id": "10", "#text": "John Lennon"},
                    {"id": "20", "#text": "Paul McCartney"},
                ]
            },
        }
        result = normalize_artist(artist_data)
        assert len(result["members"]) == 2
        assert result["members"][0] == {"id": "10", "name": "John Lennon"}
        assert result["members"][1] == {"id": "20", "name": "Paul McCartney"}

    def test_artist_with_groups(self) -> None:
        """Test normalizing artist with groups."""
        artist_data = {
            "id": "10",
            "name": "John Lennon",
            "sha256": "def456",
            "groups": {"name": [{"id": "123"}]},
        }
        result = normalize_artist(artist_data)
        assert result["groups"] == [{"id": "123"}]

    def test_artist_with_aliases(self) -> None:
        """Test normalizing artist with aliases."""
        artist_data = {
            "id": "123",
            "name": "The Beatles",
            "sha256": "abc123",
            "aliases": {"name": {"id": "456", "#text": "Beatles, The"}},
        }
        result = normalize_artist(artist_data)
        assert result["aliases"] == [{"id": "456", "name": "Beatles, The"}]


class TestNormalizeLabel:
    """Test normalize_label function."""

    def test_basic_label(self) -> None:
        """Test normalizing a basic label."""
        label_data = {
            "id": "100",
            "name": "EMI",
            "sha256": "xyz789",
        }
        result = normalize_label(label_data)
        assert result["id"] == "100"
        assert result["name"] == "EMI"

    def test_label_with_parent(self) -> None:
        """Test normalizing label with parent."""
        label_data = {
            "id": "100",
            "name": "Parlophone",
            "sha256": "xyz789",
            "parentLabel": {"id": "500", "#text": "EMI Group"},
        }
        result = normalize_label(label_data)
        assert result["parentLabel"] == {"id": "500", "name": "EMI Group"}

    def test_label_with_sublabels(self) -> None:
        """Test normalizing label with sublabels."""
        label_data = {
            "id": "500",
            "name": "EMI",
            "sha256": "xyz789",
            "sublabels": {
                "label": [
                    {"id": "100", "#text": "Parlophone"},
                    {"id": "200", "#text": "Columbia"},
                ]
            },
        }
        result = normalize_label(label_data)
        assert len(result["sublabels"]) == 2
        assert result["sublabels"][0]["id"] == "100"


class TestNormalizeMaster:
    """Test normalize_master function."""

    def test_basic_master(self) -> None:
        """Test normalizing a basic master."""
        master_data = {
            "id": "1000",
            "title": "Abbey Road",
            "year": "1969",
            "sha256": "abc123",
        }
        result = normalize_master(master_data)
        assert result["id"] == "1000"
        assert result["title"] == "Abbey Road"
        assert result["year"] == "1969"

    def test_master_with_artists(self) -> None:
        """Test normalizing master with artists."""
        master_data = {
            "id": "1000",
            "title": "Abbey Road",
            "sha256": "abc123",
            "artists": {"artist": {"id": "123", "name": "The Beatles"}},
        }
        result = normalize_master(master_data)
        assert result["artists"] == [{"id": "123", "name": "The Beatles"}]

    def test_master_with_genres_styles(self) -> None:
        """Test normalizing master with genres and styles."""
        master_data = {
            "id": "1000",
            "title": "Abbey Road",
            "sha256": "abc123",
            "genres": {"genre": ["Rock", "Pop"]},
            "styles": {"style": "Pop Rock"},
        }
        result = normalize_master(master_data)
        assert result["genres"] == ["Rock", "Pop"]
        assert result["styles"] == ["Pop Rock"]


class TestNormalizeRelease:
    """Test normalize_release function."""

    def test_basic_release(self) -> None:
        """Test normalizing a basic release."""
        release_data = {
            "id": "12345",
            "title": "Abbey Road",
            "sha256": "abc123",
        }
        result = normalize_release(release_data)
        assert result["id"] == "12345"
        assert result["title"] == "Abbey Road"

    def test_release_with_artists_and_labels(self) -> None:
        """Test normalizing release with artists and labels."""
        release_data = {
            "id": "12345",
            "title": "Abbey Road",
            "sha256": "abc123",
            "artists": {
                "artist": [
                    {"id": "123", "name": "The Beatles"},
                ]
            },
            "labels": {"label": {"id": "100", "@name": "EMI", "@catno": "PCS 7067"}},
        }
        result = normalize_release(release_data)
        assert result["artists"] == [{"id": "123", "name": "The Beatles"}]
        assert result["labels"][0]["id"] == "100"
        assert result["labels"][0]["name"] == "EMI"
        assert result["labels"][0]["catno"] == "PCS 7067"

    def test_release_with_master_id_dict(self) -> None:
        """Test normalizing release with master_id as dict."""
        release_data = {
            "id": "12345",
            "title": "Abbey Road",
            "sha256": "abc123",
            "master_id": {"#text": "1000"},
        }
        result = normalize_release(release_data)
        assert result["master_id"] == "1000"

    def test_release_with_master_id_string(self) -> None:
        """Test normalizing release with master_id as string."""
        release_data = {
            "id": "12345",
            "title": "Abbey Road",
            "sha256": "abc123",
            "master_id": "1000",
        }
        result = normalize_release(release_data)
        assert result["master_id"] == "1000"

    def test_release_with_genres_styles(self) -> None:
        """Test normalizing release with genres and styles."""
        release_data = {
            "id": "12345",
            "title": "Abbey Road",
            "sha256": "abc123",
            "genres": {"genre": "Rock"},
            "styles": {"style": ["Pop Rock", "Psychedelic Rock"]},
        }
        result = normalize_release(release_data)
        assert result["genres"] == ["Rock"]
        assert result["styles"] == ["Pop Rock", "Psychedelic Rock"]


class TestNormalizeRecord:
    """Test normalize_record function."""

    def test_dispatches_to_correct_normalizer(self) -> None:
        """Test that normalize_record dispatches to the correct normalizer."""
        artist_data = {"id": "1", "name": "Test", "sha256": "abc"}
        result = normalize_record("artists", artist_data)
        assert result["id"] == "1"
        assert result["name"] == "Test"

    def test_unknown_type_returns_as_is(self) -> None:
        """Test unknown data type returns data as-is."""
        data = {"id": "1", "custom": "field"}
        result = normalize_record("unknown", data)
        assert result == data

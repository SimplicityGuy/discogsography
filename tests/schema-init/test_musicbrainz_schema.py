"""Tests for MusicBrainz PostgreSQL schema definitions."""

from postgres_schema import _MUSICBRAINZ_INDEXES, _MUSICBRAINZ_TABLES


def test_musicbrainz_tables_defined():
    table_names = [name for name, _ in _MUSICBRAINZ_TABLES]
    assert "musicbrainz schema" in table_names
    assert "musicbrainz.artists table" in table_names
    assert "musicbrainz.labels table" in table_names
    assert "musicbrainz.releases table" in table_names
    assert "musicbrainz.relationships table" in table_names
    assert "musicbrainz.external_links table" in table_names


def test_musicbrainz_tables_use_if_not_exists():
    for name, sql in _MUSICBRAINZ_TABLES:
        if name != "musicbrainz schema":
            assert "IF NOT EXISTS" in sql, f"{name} missing IF NOT EXISTS"


def test_musicbrainz_indexes_defined():
    index_names = [name for name, _ in _MUSICBRAINZ_INDEXES]
    assert "idx_mb_artists_discogs_id" in index_names
    assert "idx_mb_labels_discogs_id" in index_names
    assert "idx_mb_releases_discogs_id" in index_names
    assert "idx_mb_rels_source" in index_names
    assert "idx_mb_links_mbid" in index_names


def test_musicbrainz_indexes_use_if_not_exists():
    for name, sql in _MUSICBRAINZ_INDEXES:
        assert "IF NOT EXISTS" in sql, f"{name} missing IF NOT EXISTS"


def test_relationships_has_unique_constraint():
    for name, sql in _MUSICBRAINZ_TABLES:
        if name == "musicbrainz.relationships table":
            assert "UNIQUE (source_mbid, target_mbid, relationship_type)" in sql


def test_external_links_has_unique_constraint():
    for name, sql in _MUSICBRAINZ_TABLES:
        if name == "musicbrainz.external_links table":
            assert "UNIQUE (mbid, entity_type, service_name)" in sql

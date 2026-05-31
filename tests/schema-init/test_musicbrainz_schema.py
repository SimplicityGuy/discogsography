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
    # ALTER migrations (e.g. widening columns to BIGINT) cannot use IF NOT EXISTS;
    # only CREATE TABLE statements must be idempotent via IF NOT EXISTS.
    for name, sql in _MUSICBRAINZ_TABLES:
        if "CREATE TABLE" in sql:
            assert "IF NOT EXISTS" in sql, f"{name} missing IF NOT EXISTS"


def test_musicbrainz_discogs_id_columns_are_bigint():
    # Discogs IDs are i64 from the extractor and now exceed int4 range (2.1B);
    # cross-reference columns must be BIGINT to avoid "integer out of range".
    expected = {
        "musicbrainz.artists table": "discogs_artist_id BIGINT",
        "musicbrainz.labels table": "discogs_label_id BIGINT",
        "musicbrainz.releases table": "discogs_release_id BIGINT",
        "musicbrainz.release_groups table": "discogs_master_id BIGINT",
    }
    found = dict.fromkeys(expected, False)
    for name, sql in _MUSICBRAINZ_TABLES:
        if name in expected:
            assert expected[name] in sql, f"{name} missing {expected[name]}"
            found[name] = True
    assert all(found.values()), f"missing tables: {[n for n, ok in found.items() if not ok]}"


def test_musicbrainz_has_bigint_widening_migrations():
    # Existing databases need explicit ALTER COLUMN ... TYPE BIGINT; CREATE TABLE
    # IF NOT EXISTS is a no-op on tables that already exist as INTEGER.
    migrations = [sql for name, sql in _MUSICBRAINZ_TABLES if "ALTER COLUMN" in sql]
    assert any("musicbrainz.artists ALTER COLUMN discogs_artist_id TYPE BIGINT" in m for m in migrations)
    assert any("musicbrainz.labels ALTER COLUMN discogs_label_id TYPE BIGINT" in m for m in migrations)
    assert any("musicbrainz.releases ALTER COLUMN discogs_release_id TYPE BIGINT" in m for m in migrations)
    assert any("musicbrainz.release_groups ALTER COLUMN discogs_master_id TYPE BIGINT" in m for m in migrations)


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
            assert "UNIQUE (source_mbid, target_mbid, source_entity_type, target_entity_type, relationship_type)" in sql


def test_external_links_has_unique_constraint():
    for name, sql in _MUSICBRAINZ_TABLES:
        if name == "musicbrainz.external_links table":
            assert "UNIQUE (mbid, entity_type, service_name, url)" in sql

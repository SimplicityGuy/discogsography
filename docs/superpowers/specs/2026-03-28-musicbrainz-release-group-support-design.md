# MusicBrainz Release-Group Support

## Overview

Add MusicBrainz release-group extraction and processing to the existing pipeline. Release-groups are the MusicBrainz equivalent of Discogs masters — they represent the abstract work that groups multiple releases (editions, remasters, etc.). This enables cross-referencing Discogs Master nodes with MusicBrainz metadata via Discogs URL relationships in the release-group data.

## Approach

**Approach C: Dedicated `ReleaseGroups` data type, enriching existing Discogs Master nodes in Neo4j.**

- Extractor downloads and parses `release-group.tar.xz`, publishes to `musicbrainz-release-groups` exchange
- Brainzgraphinator enriches existing Discogs `Master` nodes with MusicBrainz metadata (MBID, type, first release date)
- Brainztableinator stores all MB release-groups in a dedicated PostgreSQL table (including those without Discogs matches)

## Naming

| Context                       | Value                                       |
| ----------------------------- | ------------------------------------------- |
| Rust enum variant             | `ReleaseGroups`                             |
| Data type string (`as_str()`) | `"release-groups"`                          |
| RabbitMQ exchange             | `musicbrainz-release-groups`                |
| PostgreSQL table              | `musicbrainz.release_groups`                |
| MusicBrainz tarball           | `release-group.tar.xz`                      |
| JSONL filename                | `release-group` (inside `mbdump/`)          |
| Discogs ID field              | `discogs_master_id`                         |
| Neo4j node type               | `Master` (existing Discogs nodes, enriched) |

## Extractor (Rust)

### types.rs

Add `ReleaseGroups` variant to `DataType` enum:

- `as_str()` returns `"release-groups"`
- `FromStr` parses `"release-groups"` -> `DataType::ReleaseGroups`
- Add to `musicbrainz_types()`: `vec![Artists, Labels, ReleaseGroups, Releases]`
- Add `release_groups: u64` field to `ExtractionProgress`
- Update `increment()`, `get()`, `total()` for the new field

### musicbrainz_downloader.rs

- Add to `MB_FILE_PATTERNS`: `(DataType::ReleaseGroups, &["release-group.jsonl", "release-group.jsonl.xz", "mbdump-release-group.jsonl.xz"])`
- Add to `entity_keyword()`: `DataType::ReleaseGroups => "release-group"`
- Add `"release-group"` to `MB_ENTITIES` constant (controls download URLs)

### jsonl_parser.rs

New `parse_mb_release_group_line(line: &str) -> Result<DataMessage>`:

```
Input: one JSONL line from release-group dump
Output: DataMessage with normalized fields
```

Fields extracted:

- `discogs_master_id` — from Discogs URL relation via `extract_discogs_id(url, "master")`
- `name` — from `v["title"]` (release-groups use "title", not "name")
- `mb_type` — primary type: Album, Single, EP, Compilation, Broadcast, Other
- `secondary_types` — array: Compilation, Live, Remix, Soundtrack, etc.
- `first_release_date` — from `v["first-release-date"]`
- `disambiguation`
- `relations` — normalized entity rels via `extract_entity_rels()`
- `external_links` — non-Discogs URL rels via `extract_external_links()`

Follows the same pattern as `parse_mb_artist_line`, `parse_mb_label_line`, `parse_mb_release_line`.

### extractor.rs

- Add `DataType::ReleaseGroups => parse_mb_release_group_line` in the `parse_fn` match in `parse_mb_jsonl_file()`
- Exchange setup and file processing loops already iterate over `musicbrainz_types()`, so they automatically include `ReleaseGroups`

## Consumers (Python)

### common/config.py

Add `"release-groups"` to `MUSICBRAINZ_DATA_TYPES`:

```python
MUSICBRAINZ_DATA_TYPES = ["artists", "labels", "release-groups", "releases"]
```

### brainzgraphinator

New `enrich_release_group(tx, record) -> bool`:

1. Read `discogs_master_id` from record
1. If None, skip (no Discogs match) — increment `entities_skipped_no_discogs_match`
1. `MATCH (m:Master {id: $discogs_id})`
1. Set properties: `m.mbid`, `m.mb_type`, `m.mb_secondary_types`, `m.mb_first_release_date`, `m.mb_disambiguation`, `m.mb_updated_at`
1. If matched, increment `entities_enriched`

Register:

- `PROCESSORS["release-groups"] = enrich_release_group`
- Add `"release-groups": 0` to `message_counts`
- Add `"release-groups": 0` to `last_message_time`

### brainztableinator

New `process_release_group(conn, record) -> None`:

1. Insert/upsert into `musicbrainz.release_groups`
1. Insert relationships via `_insert_relationship(conn, mbid, "release-group", rel)`
1. Insert external links via `_insert_external_link(conn, mbid, "release-group", link)`

Register:

- `PROCESSORS["release-groups"] = process_release_group`
- Add `"release-groups": 0` to `message_counts`
- Add `"release-groups": 0` to `last_message_time`

## Database Schema

### PostgreSQL (schema-init/postgres_schema.py)

New table:

```sql
CREATE TABLE IF NOT EXISTS musicbrainz.release_groups (
    mbid UUID PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT,
    secondary_types JSONB,
    first_release_date TEXT,
    disambiguation TEXT,
    discogs_master_id INTEGER,
    data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
)
```

Relationships and external links use the existing shared `musicbrainz.relationships` and `musicbrainz.external_links` tables.

### Neo4j (schema-init/neo4j_schema.py)

Add MBID index on existing Master nodes:

```
CREATE INDEX master_mbid IF NOT EXISTS FOR (m:Master) ON (m.mbid)
```

No new node type — we enrich existing Discogs `Master` nodes.

## Documentation Updates

- `CLAUDE.md` — Update architecture notes: MusicBrainz exchanges from 3 to 4, add `musicbrainz-release-groups`
- `docs/architecture.md` — Update MusicBrainz exchanges list
- `.github/workflows/docker-compose-validate.yml` — Update expected services/exchange counts if validated

## Testing

- New `test_parse_mb_release_group_line_with_discogs` and `_no_discogs` unit tests in Rust
- New `test_parse_mb_jsonl_file_release_groups` integration test
- Python tests for `enrich_release_group` and `process_release_group` following existing patterns

## Not In Scope (This PR)

- No new Docker service — uses existing extractor-musicbrainz, brainzgraphinator, brainztableinator
- No API endpoint changes
- No Explore/Dashboard UI changes
- No MCP server changes

## Future Work

- **Explore service**: Add release-group/Master browsing and cross-reference display in the graph exploration UI
- **Dashboard service**: Add release-group processing metrics to the MusicBrainz monitoring panels
- **MCP server**: Expose release-group data and Master↔MusicBrainz cross-references to AI assistants
- **API**: Add release-group search/lookup endpoints

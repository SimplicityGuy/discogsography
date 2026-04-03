# MusicBrainz Release-Group Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MusicBrainz release-group extraction, parsing, and processing so Discogs Master nodes are enriched with MusicBrainz metadata and all release-groups are stored in PostgreSQL.

**Architecture:** New `ReleaseGroups` variant in the Rust `DataType` enum. Extractor downloads `release-group.tar.xz`, parses with `parse_mb_release_group_line()`, publishes to `musicbrainz-release-groups` exchange. Brainzgraphinator enriches existing Discogs `Master` nodes. Brainztableinator stores all release-groups in `musicbrainz.release_groups`.

**Tech Stack:** Rust (extractor), Python 3.13 (consumers), Neo4j (graph), PostgreSQL (analytics), RabbitMQ (messaging)

**Spec:** `docs/superpowers/specs/2026-03-28-musicbrainz-release-group-support-design.md`

______________________________________________________________________

### Task 1: Add ReleaseGroups to DataType enum (Rust)

**Files:**

- Modify: `extractor/src/types.rs`

- Test: `extractor/src/tests/types_tests.rs`

- [ ] **Step 1: Add ReleaseGroups variant to DataType enum**

In `extractor/src/types.rs`, add `ReleaseGroups` between `Masters` and `Releases` in the enum (line 12):

```rust
pub enum DataType {
    Artists,
    Labels,
    Masters,
    ReleaseGroups,
    Releases,
}
```

- [ ] **Step 2: Add to musicbrainz_types()**

Update `musicbrainz_types()` at line 24-26:

```rust
pub fn musicbrainz_types() -> Vec<DataType> {
    vec![DataType::Artists, DataType::Labels, DataType::ReleaseGroups, DataType::Releases]
}
```

- [ ] **Step 3: Add as_str() mapping**

Add to the match in `as_str()` at line 33:

```rust
DataType::ReleaseGroups => "release-groups",
```

- [ ] **Step 4: Add FromStr parsing**

Add to the match in `from_str()` at line 53:

```rust
"release-groups" => Ok(DataType::ReleaseGroups),
```

- [ ] **Step 5: Add to ExtractionProgress**

Add `release_groups` field to the struct at line 92:

```rust
pub struct ExtractionProgress {
    pub artists: u64,
    pub labels: u64,
    pub masters: u64,
    pub release_groups: u64,
    pub releases: u64,
}
```

Add to `increment()` match at line 101:

```rust
DataType::ReleaseGroups => self.release_groups += 1,
```

Add to `get()` match at line 110:

```rust
DataType::ReleaseGroups => self.release_groups,
```

Update `total()` at line 117:

```rust
self.artists + self.labels + self.masters + self.release_groups + self.releases
```

- [ ] **Step 6: Build to verify compilation**

Run: `cargo build --manifest-path extractor/Cargo.toml 2>&1 | tail -5`

Expected: Compilation succeeds (warnings about exhaustive matches in other files are expected — we fix those in subsequent tasks).

- [ ] **Step 7: Commit**

```bash
git add extractor/src/types.rs
git commit -m "feat: add ReleaseGroups variant to DataType enum"
```

______________________________________________________________________

### Task 2: Update MusicBrainz downloader for release-groups (Rust)

**Files:**

- Modify: `extractor/src/musicbrainz_downloader.rs`

- [ ] **Step 1: Add file pattern for release-groups**

Add to `MB_FILE_PATTERNS` at line 17 (before the Releases entry):

```rust
(DataType::ReleaseGroups, &["release-group.jsonl.xz", "mbdump-release-group.jsonl.xz", "release-group.jsonl"]),
```

- [ ] **Step 2: Add entity keyword**

Add to the match in `entity_keyword()` at line 25:

```rust
DataType::ReleaseGroups => "release-group",
```

- [ ] **Step 3: Add to MB_ENTITIES download list**

Update `MB_ENTITIES` at line 137:

```rust
const MB_ENTITIES: &[&str] = &["artist", "label", "release-group", "release"];
```

- [ ] **Step 4: Build to verify compilation**

Run: `cargo build --manifest-path extractor/Cargo.toml 2>&1 | tail -5`

Expected: Compilation succeeds.

- [ ] **Step 5: Commit**

```bash
git add extractor/src/musicbrainz_downloader.rs
git commit -m "feat: add release-group to MusicBrainz downloader"
```

______________________________________________________________________

### Task 3: Add parse_mb_release_group_line parser (Rust)

**Files:**

- Modify: `extractor/src/jsonl_parser.rs`

- Modify: `extractor/src/tests/jsonl_parser_tests.rs`

- [ ] **Step 1: Write failing tests for parse_mb_release_group_line**

Add to `extractor/src/tests/jsonl_parser_tests.rs`:

```rust
// ─── parse_mb_release_group_line ────────────────────────────────────────────

#[test]
fn test_parse_mb_release_group_line_with_discogs() {
    let line = r#"{"id":"1dc4c347-a1db-32aa-b14f-bc9cc507b843","title":"Abbey Road","primary-type":"Album","secondary-types":["Compilation"],"first-release-date":"1969-09-26","disambiguation":"","relations":[{"type":"discogs","target-type":"url","url":{"resource":"https://www.discogs.com/master/23853"}},{"type":"wikipedia","target-type":"url","url":{"resource":"https://en.wikipedia.org/wiki/Abbey_Road"}}]}"#;
    let msg = parse_mb_release_group_line(line).unwrap();
    assert_eq!(msg.id, "1dc4c347-a1db-32aa-b14f-bc9cc507b843");
    assert_eq!(msg.data["discogs_master_id"], 23853);
    assert_eq!(msg.data["name"], "Abbey Road");
    assert_eq!(msg.data["mb_type"], "Album");
    assert_eq!(msg.data["secondary_types"], serde_json::json!(["Compilation"]));
    assert_eq!(msg.data["first_release_date"], "1969-09-26");
    assert!(!msg.sha256.is_empty());
    let links = msg.data["external_links"].as_array().unwrap();
    assert_eq!(links.len(), 1);
    assert_eq!(links[0]["service"], "wikipedia");
}

#[test]
fn test_parse_mb_release_group_line_no_discogs() {
    let line = r#"{"id":"rg-mbid","title":"Unknown Album","primary-type":"Album","secondary-types":[],"first-release-date":"2020","disambiguation":"test","relations":[]}"#;
    let msg = parse_mb_release_group_line(line).unwrap();
    assert!(msg.data["discogs_master_id"].is_null());
    assert_eq!(msg.data["name"], "Unknown Album");
    assert_eq!(msg.data["mb_type"], "Album");
}

#[test]
fn test_parse_mb_release_group_line_invalid_json() {
    let result = parse_mb_release_group_line("not valid json");
    assert!(result.is_err());
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cargo test --manifest-path extractor/Cargo.toml 2>&1 | grep -E "FAIL|error|parse_mb_release_group"`

Expected: Compilation error — `parse_mb_release_group_line` not defined.

- [ ] **Step 3: Implement parse_mb_release_group_line**

Add to `extractor/src/jsonl_parser.rs`, after `parse_mb_release_line`:

```rust
/// Parse a single MusicBrainz JSONL release-group line into a [`DataMessage`].
pub fn parse_mb_release_group_line(line: &str) -> Result<DataMessage> {
    let v: Value = serde_json::from_str(line).context("Failed to parse release-group JSONL line")?;

    let mbid = v["id"].as_str().unwrap_or("unknown").to_string();
    let sha256 = hash_line(line);

    let all_rels = v["relations"].as_array().map(|a| a.as_slice()).unwrap_or(&[]);
    let url_rels = extract_url_rels(all_rels);
    let entity_rels = extract_entity_rels(all_rels);
    let discogs_master_id = find_discogs_id(&url_rels, "master");
    let external_links = extract_external_links(&url_rels);

    let data = serde_json::json!({
        "discogs_master_id": discogs_master_id,
        "name": v["title"],
        "mb_type": v["primary-type"],
        "secondary_types": v["secondary-types"],
        "first_release_date": v["first-release-date"],
        "disambiguation": v["disambiguation"],
        "relations": entity_rels,
        "external_links": external_links
    });

    Ok(DataMessage { id: mbid, sha256, data, raw_xml: None })
}
```

- [ ] **Step 4: Wire into parse_mb_jsonl_file**

Update the `parse_fn` match in `parse_mb_jsonl_file()` (around line 277). Replace the `Masters` arm:

```rust
let parse_fn: fn(&str) -> Result<DataMessage> = match data_type {
    DataType::Artists => parse_mb_artist_line,
    DataType::Labels => parse_mb_label_line,
    DataType::ReleaseGroups => parse_mb_release_group_line,
    DataType::Releases => parse_mb_release_line,
    DataType::Masters => {
        warn!("⚠️ MusicBrainz does not have a Masters data type; skipping file {:?}", path);
        return Ok(0);
    }
};
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cargo test --manifest-path extractor/Cargo.toml 2>&1 | tail -10`

Expected: All tests pass.

- [ ] **Step 6: Run clippy**

Run: `cargo clippy --manifest-path extractor/Cargo.toml -- -D warnings 2>&1 | tail -5`

Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add extractor/src/jsonl_parser.rs extractor/src/tests/jsonl_parser_tests.rs
git commit -m "feat: add parse_mb_release_group_line parser with tests"
```

______________________________________________________________________

### Task 4: Add release_groups PostgreSQL table

**Files:**

- Modify: `schema-init/postgres_schema.py`

- [ ] **Step 1: Add release_groups table to MUSICBRAINZ_TABLES**

In `schema-init/postgres_schema.py`, add a new entry before the `musicbrainz.relationships table` entry (before line 537):

```python
    (
        "musicbrainz.release_groups table",
        """CREATE TABLE IF NOT EXISTS musicbrainz.release_groups (
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
        )""",
    ),
```

- [ ] **Step 2: Run lint to verify syntax**

Run: `uv run ruff check schema-init/`

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add schema-init/postgres_schema.py
git commit -m "feat: add musicbrainz.release_groups PostgreSQL table"
```

______________________________________________________________________

### Task 5: Add Master MBID index in Neo4j

**Files:**

- Modify: `schema-init/neo4j_schema.py`

- [ ] **Step 1: Add master_mbid index**

In `schema-init/neo4j_schema.py`, add after the `release_mbid` index entry (after line 153):

```python
    (
        "master_mbid",
        "CREATE INDEX master_mbid IF NOT EXISTS FOR (m:Master) ON (m.mbid)",
    ),
```

- [ ] **Step 2: Run lint**

Run: `uv run ruff check schema-init/`

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add schema-init/neo4j_schema.py
git commit -m "feat: add Master MBID index for Neo4j"
```

______________________________________________________________________

### Task 6: Add release-groups to Python config

**Files:**

- Modify: `common/config.py`

- [ ] **Step 1: Add release-groups to MUSICBRAINZ_DATA_TYPES**

In `common/config.py`, update line 281:

```python
MUSICBRAINZ_DATA_TYPES = ["artists", "labels", "release-groups", "releases"]
```

- [ ] **Step 2: Run lint**

Run: `uv run ruff check common/`

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add common/config.py
git commit -m "feat: add release-groups to MUSICBRAINZ_DATA_TYPES"
```

______________________________________________________________________

### Task 7: Add release-group enrichment to brainzgraphinator

**Files:**

- Modify: `brainzgraphinator/brainzgraphinator.py`

- Modify: `tests/brainzgraphinator/conftest.py`

- Modify: `tests/brainzgraphinator/test_brainzgraphinator.py`

- [ ] **Step 1: Write failing tests**

Add fixture to `tests/brainzgraphinator/conftest.py`:

```python
@pytest.fixture
def sample_release_group_record():
    """Sample MusicBrainz release-group record for testing."""
    return {
        "mbid": "1dc4c347-a1db-32aa-b14f-bc9cc507b843",
        "discogs_master_id": 23853,
        "type": "Album",
        "secondary_types": ["Compilation"],
        "first_release_date": "1969-09-26",
        "disambiguation": "",
    }
```

Add tests to `tests/brainzgraphinator/test_brainzgraphinator.py` in the enrichment test class (after `test_enrich_release_no_discogs_id_skips`):

```python
    def test_enrich_release_group_with_match(self, mock_tx: MagicMock, sample_release_group_record: dict[str, Any]) -> None:
        """Release-group with discogs_master_id gets enriched on Master node."""
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = enrich_release_group(mock_tx, sample_release_group_record)
            assert result is True

        call_args = mock_tx.run.call_args_list[0]
        cypher = call_args[0][0]
        assert "MATCH (m:Master" in cypher
        assert "SET m.mbid" in cypher
        assert "m.mb_type" in cypher
        assert "m.mb_secondary_types" in cypher
        assert "m.mb_first_release_date" in cypher
        assert "m.mb_updated_at" in cypher

    def test_enrich_release_group_no_discogs_id_skips(self, mock_tx: MagicMock) -> None:
        """Release-group with no discogs_master_id is deliberately skipped."""
        record = {"mbid": "abc", "discogs_master_id": None}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = enrich_release_group(mock_tx, record)
            assert result is True
        mock_tx.run.assert_not_called()

    def test_enrich_release_group_no_neo4j_match(self, mock_tx: MagicMock) -> None:
        """Release-group with discogs_master_id but no Neo4j Master node is skipped."""
        mock_tx.run.return_value.single.return_value = None
        record = {"mbid": "abc", "discogs_master_id": 99999}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = enrich_release_group(mock_tx, record)
            assert result is True
```

Also update the import at top of test file to include `enrich_release_group`:

```python
from brainzgraphinator.brainzgraphinator import (
    ...,
    enrich_release_group,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/brainzgraphinator/ -k "release_group" -v 2>&1 | tail -10`

Expected: ImportError — `enrich_release_group` not found.

- [ ] **Step 3: Implement enrich_release_group**

Add to `brainzgraphinator/brainzgraphinator.py`, after `enrich_release` (before the PROCESSORS dict):

```python
def enrich_release_group(tx: Any, record: dict[str, Any]) -> bool:
    """Enrich an existing Master node with MusicBrainz release-group metadata.

    If discogs_master_id is None, skip — entity has no Discogs match.
    """
    discogs_id = record.get("discogs_master_id")
    if discogs_id is None:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1
        return True

    result = tx.run(
        "MATCH (m:Master {id: $discogs_id}) "
        "SET m.mbid = $mbid, "
        "    m.mb_type = $mb_type, "
        "    m.mb_secondary_types = $mb_secondary_types, "
        "    m.mb_first_release_date = $mb_first_release_date, "
        "    m.mb_disambiguation = $mb_disambiguation, "
        "    m.mb_updated_at = $mb_updated_at "
        "RETURN m.id AS matched_id",
        discogs_id=discogs_id,
        mbid=record.get("mbid"),
        mb_type=record.get("type"),
        mb_secondary_types=record.get("secondary_types", []),
        mb_first_release_date=record.get("first_release_date"),
        mb_disambiguation=record.get("disambiguation"),
        mb_updated_at=datetime.now(UTC).isoformat(),
    )
    matched = result.single()
    if matched:
        enrichment_stats["entities_enriched"] += 1
    else:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1

    return True
```

- [ ] **Step 4: Register in PROCESSORS and add tracking**

Update `message_counts` (line 32):

```python
message_counts = {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}
```

Update `last_message_time` (line 34):

```python
last_message_time = {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}
```

Update PROCESSORS dict (line 426):

```python
PROCESSORS: dict[str, Any] = {
    "artists": enrich_artist,
    "labels": enrich_label,
    "release-groups": enrich_release_group,
    "releases": enrich_release,
}
```

Add handler instance (after line 492):

```python
on_release_group_message = make_message_handler("release-groups", enrich_release_group)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/brainzgraphinator/ -v 2>&1 | tail -20`

Expected: All tests pass (including existing tests that check PROCESSORS has all types).

- [ ] **Step 6: Run lint and type check**

Run: `uv run ruff check brainzgraphinator/ && uv run mypy brainzgraphinator/`

Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add brainzgraphinator/brainzgraphinator.py tests/brainzgraphinator/conftest.py tests/brainzgraphinator/test_brainzgraphinator.py
git commit -m "feat: add release-group enrichment to brainzgraphinator"
```

______________________________________________________________________

### Task 8: Add release-group processing to brainztableinator

**Files:**

- Modify: `brainztableinator/brainztableinator.py`

- Modify: `tests/brainztableinator/test_brainztableinator.py`

- [ ] **Step 1: Write failing tests**

Add test to `tests/brainztableinator/test_brainztableinator.py` (follow existing test patterns for `process_artist`/`process_label`/`process_release`):

```python
class TestProcessReleaseGroup:
    """Tests for process_release_group function."""

    async def test_process_release_group_inserts_record(self, mock_async_pool: Any) -> None:
        """Release-group record is inserted into PostgreSQL."""
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_conn.cursor.return_value.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__aexit__ = AsyncMock(return_value=None)

        record = {
            "mbid": "1dc4c347-a1db-32aa-b14f-bc9cc507b843",
            "name": "Abbey Road",
            "mb_type": "Album",
            "secondary_types": ["Compilation"],
            "first_release_date": "1969-09-26",
            "disambiguation": "",
            "discogs_master_id": 23853,
            "relations": [],
            "external_links": [],
        }

        await process_release_group(mock_conn, record)

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        assert "musicbrainz.release_groups" in sql
        assert "ON CONFLICT (mbid) DO UPDATE" in sql

    async def test_process_release_group_with_relationships(self, mock_async_pool: Any) -> None:
        """Release-group with relations inserts relationship records."""
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_conn.cursor.return_value.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__aexit__ = AsyncMock(return_value=None)

        record = {
            "mbid": "rg-mbid",
            "name": "Test",
            "mb_type": "Album",
            "secondary_types": [],
            "first_release_date": None,
            "disambiguation": "",
            "discogs_master_id": None,
            "relations": [
                {"type": "tribute", "target_type": "artist", "target_mbid": "artist-mbid"}
            ],
            "external_links": [
                {"service": "wikipedia", "url": "https://en.wikipedia.org/wiki/Test"}
            ],
        }

        await process_release_group(mock_conn, record)

        # 1 main insert + 1 relationship + 1 external link = 3 execute calls
        assert mock_cursor.execute.call_count == 3
```

Update imports at top of test file to include `process_release_group`:

```python
from brainztableinator.brainztableinator import process_release_group
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/brainztableinator/ -k "release_group" -v 2>&1 | tail -10`

Expected: ImportError — `process_release_group` not found.

- [ ] **Step 3: Implement process_release_group**

Add to `brainztableinator/brainztableinator.py`, after `process_release` (before PROCESSORS dict):

```python
async def process_release_group(conn: Any, record: dict[str, Any]) -> None:
    """Insert or update a MusicBrainz release-group record in PostgreSQL."""
    mbid = record.get("mbid", record.get("id", ""))
    async with conn.cursor() as cursor:
        await cursor.execute(
            "INSERT INTO musicbrainz.release_groups "
            "(mbid, name, type, secondary_types, first_release_date, "
            "disambiguation, discogs_master_id, data) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (mbid) DO UPDATE SET "
            "name = EXCLUDED.name, type = EXCLUDED.type, "
            "secondary_types = EXCLUDED.secondary_types, "
            "first_release_date = EXCLUDED.first_release_date, "
            "disambiguation = EXCLUDED.disambiguation, "
            "discogs_master_id = EXCLUDED.discogs_master_id, "
            "data = EXCLUDED.data, updated_at = NOW()",
            (
                mbid,
                record.get("name", ""),
                record.get("mb_type", ""),
                Jsonb(record.get("secondary_types", [])),
                record.get("first_release_date"),
                record.get("disambiguation", ""),
                record.get("discogs_master_id"),
                Jsonb(record),
            ),
        )

    # Insert relationships
    for rel in record.get("relations", []):
        await _insert_relationship(conn, mbid, "release-group", rel)

    # Insert external links
    for link in record.get("external_links", []):
        await _insert_external_link(conn, mbid, "release-group", link)
```

- [ ] **Step 4: Register in PROCESSORS and add tracking**

Update `message_counts` (line 35):

```python
message_counts = {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}
```

Update `last_message_time` (line 37):

```python
last_message_time = {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}
```

Update PROCESSORS dict (line 595):

```python
PROCESSORS: dict[str, Any] = {
    "artists": process_artist,
    "labels": process_label,
    "release-groups": process_release_group,
    "releases": process_release,
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/brainztableinator/ -v 2>&1 | tail -20`

Expected: All tests pass.

- [ ] **Step 6: Run lint and type check**

Run: `uv run ruff check brainztableinator/ && uv run mypy brainztableinator/`

Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add brainztableinator/brainztableinator.py tests/brainztableinator/test_brainztableinator.py
git commit -m "feat: add release-group processing to brainztableinator"
```

______________________________________________________________________

### Task 9: Update documentation

**Files:**

- Modify: `CLAUDE.md`

- Modify: `docs/architecture.md`

- [ ] **Step 1: Update CLAUDE.md**

At line 48, change:

```
- **MusicBrainz exchanges**: `musicbrainz-{artists,labels,releases}` (3 fanout exchanges, no masters)
```

to:

```
- **MusicBrainz exchanges**: `musicbrainz-{artists,labels,release-groups,releases}` (4 fanout exchanges)
```

Also update line 45:

```
- **Extractor** supports two modes: `--source discogs` (XML → 4 fanout exchanges) and `--source musicbrainz` (JSONL → 4 fanout exchanges). It has zero knowledge of consumers.
```

- [ ] **Step 2: Update docs/architecture.md**

At lines 228-232, change:

```markdown
**MusicBrainz exchanges** (3, no masters):

- `musicbrainz-artists`: MusicBrainz artist data with Discogs cross-references
- `musicbrainz-labels`: MusicBrainz label data with Discogs cross-references
- `musicbrainz-releases`: MusicBrainz release data with Discogs cross-references
```

to:

```markdown
**MusicBrainz exchanges** (4):

- `musicbrainz-artists`: MusicBrainz artist data with Discogs cross-references
- `musicbrainz-labels`: MusicBrainz label data with Discogs cross-references
- `musicbrainz-release-groups`: MusicBrainz release-group data with Discogs master cross-references
- `musicbrainz-releases`: MusicBrainz release data with Discogs cross-references
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/architecture.md
git commit -m "docs: update architecture for release-group support"
```

______________________________________________________________________

### Task 10: Final verification

- [ ] **Step 1: Run full Rust test suite**

Run: `cargo test --manifest-path extractor/Cargo.toml 2>&1 | tail -15`

Expected: All tests pass.

- [ ] **Step 2: Run Rust clippy and fmt**

Run: `cargo clippy --manifest-path extractor/Cargo.toml -- -D warnings 2>&1 | tail -5`
Run: `cargo fmt --manifest-path extractor/Cargo.toml --check 2>&1 | head -5`

Expected: Clean (pre-existing fmt issues in other files are acceptable).

- [ ] **Step 3: Run Python test suites**

Run: `uv run pytest tests/brainzgraphinator/ tests/brainztableinator/ tests/schema_init/ -v 2>&1 | tail -20`

Expected: All tests pass.

- [ ] **Step 4: Run full lint**

Run: `uv run ruff check . && uv run mypy brainzgraphinator/ brainztableinator/ common/ schema-init/`

Expected: No errors.

- [ ] **Step 5: Run docker compose validation**

Run: `docker compose config --quiet 2>&1`

Expected: No errors.

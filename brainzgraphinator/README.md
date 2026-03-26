# Brainzgraphinator

Enriches existing Neo4j knowledge graph nodes with MusicBrainz metadata and creates new relationship edges.

## What It Does

- Consumes messages from `musicbrainz-artists`, `musicbrainz-labels`, `musicbrainz-releases` fanout exchanges
- For entities with a Discogs ID match: adds MBID, type, gender, dates, area, and other metadata as `mb_`-prefixed properties
- Creates new relationship edges (COLLABORATED_WITH, TAUGHT, TRIBUTE_TO, FOUNDED, SUPPORTED, SUBGROUP_OF, RENAMED_TO, enriched MEMBER_OF) between matched entities
- Skips entities and relationships without Discogs matches (see [design spec](../docs/superpowers/specs/2026-03-25-musicbrainz-integration-design.md) for rationale)
- All writes are idempotent — safe for re-import
- All MB-sourced edges carry `source: 'musicbrainz'` for provenance

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_HOST` | — | Neo4j hostname |
| `NEO4J_USERNAME` | — | Neo4j username |
| `NEO4J_PASSWORD` | — | Neo4j password (supports `_FILE` suffix for Docker secrets) |
| `RABBITMQ_HOST` | rabbitmq | RabbitMQ hostname |
| `RABBITMQ_USERNAME` | discogsography | RabbitMQ username |
| `RABBITMQ_PASSWORD` | discogsography | RabbitMQ password |
| `NEO4J_BATCH_MODE` | false | Enable batch processing |
| `NEO4J_BATCH_SIZE` | 100 | Messages per batch |
| `NEO4J_BATCH_FLUSH_INTERVAL` | 5.0 | Seconds between batch flushes |
| `CONSUMER_CANCEL_DELAY` | 300 | Seconds before canceling idle consumer |
| `STARTUP_DELAY` | 0 | Seconds to wait before starting |
| `LOG_LEVEL` | INFO | Logging level |

## Health

Port **8011**: `GET /health`

Returns enrichment statistics:
- `entities_enriched` — count of entities successfully enriched
- `entities_skipped_no_discogs_match` — count of entities skipped (no Discogs ID)
- `relationships_created` — count of new Neo4j edges created
- `relationships_skipped_missing_side` — count of edges skipped (one side missing Discogs match)

## Relationship Edge Types

| MusicBrainz Type | Neo4j Edge | Direction |
|-----------------|------------|-----------|
| member of band | `MEMBER_OF` | person → group |
| collaboration | `COLLABORATED_WITH` | artist ↔ artist |
| teacher | `TAUGHT` | teacher → student |
| tribute | `TRIBUTE_TO` | tribute act → original |
| founder | `FOUNDED` | person → group |
| supporting musician | `SUPPORTED` | supporter → main artist |
| subgroup | `SUBGROUP_OF` | subgroup → parent |
| artist rename | `RENAMED_TO` | old → new |

## Design Decisions

- **Discogs-matched entities only**: Entities without a Discogs URL in the MusicBrainz data are skipped entirely in Neo4j. They are stored in PostgreSQL by brainztableinator for future use.
- **Both sides required for edges**: Relationship edges are only created when both the source and target entity have Discogs IDs in our graph.
- **`mb_` prefix**: All MusicBrainz-sourced properties use the `mb_` prefix (e.g., `mb_type`, `mb_gender`) to clearly distinguish from Discogs-sourced data. The `mbid` property is the exception.

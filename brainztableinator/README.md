# Brainztableinator

Consumes MusicBrainz messages and stores all data in PostgreSQL.

## What It Does

- Consumes messages from `musicbrainz-artists`, `musicbrainz-labels`, `musicbrainz-releases` fanout exchanges
- Stores all MusicBrainz entities in the `musicbrainz` PostgreSQL schema — including entities without Discogs matches
- Stores relationships and external links (Wikipedia, Wikidata, AllMusic, Last.fm, IMDb)
- Idempotent writes via `ON CONFLICT DO UPDATE/NOTHING` — safe for re-import

## PostgreSQL Schema

| Table | Description |
|-------|-------------|
| `musicbrainz.artists` | MBID, name, type, gender, dates, area, discogs_artist_id |
| `musicbrainz.labels` | MBID, name, type, label_code, dates, discogs_label_id |
| `musicbrainz.releases` | MBID, name, barcode, status, discogs_release_id |
| `musicbrainz.relationships` | Source/target MBIDs, type, dates, attributes |
| `musicbrainz.external_links` | MBID, service name, URL |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | — | PostgreSQL hostname (host:port) |
| `POSTGRES_USERNAME` | — | PostgreSQL username |
| `POSTGRES_PASSWORD` | — | PostgreSQL password (supports `_FILE` suffix) |
| `POSTGRES_DATABASE` | discogsography | Database name |
| `RABBITMQ_HOST` | rabbitmq | RabbitMQ hostname |
| `RABBITMQ_USERNAME` | discogsography | RabbitMQ username |
| `RABBITMQ_PASSWORD` | discogsography | RabbitMQ password |
| `POSTGRES_BATCH_MODE` | false | Enable batch processing |
| `POSTGRES_BATCH_SIZE` | 100 | Messages per batch |
| `POSTGRES_BATCH_FLUSH_INTERVAL` | 5.0 | Seconds between batch flushes |
| `CONSUMER_CANCEL_DELAY` | 300 | Seconds before canceling idle consumer |
| `STARTUP_DELAY` | 0 | Seconds to wait before starting |
| `LOG_LEVEL` | INFO | Logging level |

## Health

Port **8010**: `GET /health`

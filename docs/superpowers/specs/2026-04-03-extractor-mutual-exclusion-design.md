# Extractor Mutual Exclusion Design

**Date:** 2026-04-03
**Status:** Approved

## Problem

The Discogs and MusicBrainz extractors run as independent Docker containers with no coordination. When both extract simultaneously, the system suffers from:

- **Resource contention** — both extractors saturate RabbitMQ and network bandwidth
- **Consumer saturation** — graphinator, tableinator, brainzgraphinator, and brainztableinator can't keep up processing both sources at once
- **Data ordering** — brainzgraphinator enriches existing Discogs nodes, so Discogs data should be ingested first
- **Disk I/O** — concurrent extraction creates heavy disk pressure

## Decision

**Approach: Health Endpoint Polling** — the MusicBrainz extractor polls the Discogs extractor's `/health` endpoint before starting extraction. No new infrastructure dependencies.

Alternatives considered and rejected:
- **Redis distributed lock** — adds Redis as a new dependency for the Rust extractor; doesn't inherently enforce Discogs-first ordering
- **RabbitMQ signaling** — overly complex for coordinating exactly 2 processes; message durability concerns
- **Shared volume lock file** — rejected by stakeholder

## Scope

Only the MusicBrainz extractor (`--source musicbrainz`) is modified. The Discogs extractor is untouched.

## Behavior

Before `process_musicbrainz_data()` runs (both initial and periodic), the MusicBrainz extractor:

1. Makes a GET request to the Discogs extractor's health endpoint: `http://extractor-discogs:8000/health`
2. Checks the `extraction_status` field in the JSON response
3. If `running` — logs a message, waits 60 seconds, retries (loop)
4. If `idle`, `completed`, or `failed` — proceeds with MusicBrainz extraction
5. If unreachable (connection refused, timeout after 5s) — retries up to 10 times with 60s intervals. After 10 consecutive failures, proceeds anyway (Discogs container is likely not running)

Once Discogs extraction finishes (extractor reports idle), MusicBrainz may start even if Discogs consumers still have queued messages. Consumer overlap is acceptable.

## Configuration

New environment variable: `DISCOGS_HEALTH_URL` (default: `http://extractor-discogs:8000/health`). Allows overriding for testing or non-standard deployments.

## Code Changes

### New function: `wait_for_discogs_idle()`

Location: `extractor/src/extractor.rs`

Encapsulates the polling logic. Called inside `run_musicbrainz_loop()` right before each call to `process_musicbrainz_data()`.

Parameters:
- `discogs_health_url: &str` — the URL to poll
- `shutdown_flag: &AtomicBool` — to break out of the wait loop if shutdown is requested

Returns: `Result<()>` — returns Ok when cleared to proceed, or when fallback kicks in after max retries.

### Integration point

In `run_musicbrainz_loop()`, add `wait_for_discogs_idle()` call before each `process_musicbrainz_data()` invocation — both the initial extraction and periodic re-extractions.

### Config change

Add `discogs_health_url` field to `ExtractorConfig` in `extractor/src/config.rs`, read from `DISCOGS_HEALTH_URL` env var with default `http://extractor-discogs:8000/health`.

## Shutdown Awareness

The polling loop must respect the existing shutdown signal (`AtomicBool`). If shutdown is requested while waiting for Discogs to finish, break out immediately instead of blocking for up to 10 minutes.

## Docker Compose

No changes required. `extractor-musicbrainz` already has network access to `extractor-discogs` via the Docker network.

## Logging

All log messages use emojis from `docs/emoji-guide.md`:

- `"⏳ Discogs extraction in progress, waiting before starting MusicBrainz extraction..."` — on each poll that finds `running`
- `"✅ Discogs extractor idle, proceeding with MusicBrainz extraction"` — when cleared to proceed
- `"⚠️ Discogs health endpoint unreachable (attempt {n}/10), retrying in 60s..."` — on connection failure
- `"⚠️ Discogs health endpoint unreachable after 10 attempts, proceeding with MusicBrainz extraction"` — fallback

## Testing

- Unit test: mock HTTP client, verify `wait_for_discogs_idle()` proceeds on `idle`/`completed`/`failed` status
- Unit test: verify retries on `running` status
- Unit test: verify fallback after 10 unreachable attempts
- Unit test: verify shutdown signal breaks out of the wait loop
- No changes to existing Discogs extractor tests

# Curator Service

Syncs a user's Discogs collection and wantlist into the Discogsography Neo4j graph database and PostgreSQL, enabling personalised graph exploration and analytics.

## Overview

The curator service:

- Authenticates users via JWT tokens (same secret as the API service)
- Reads stored Discogs OAuth tokens from PostgreSQL (populated by the API service)
- Fetches the user's Discogs collection and wantlist via the Discogs API
- Writes the synced data to Neo4j graph database
- Tracks sync history in PostgreSQL
- Runs sync jobs as background async tasks — one per user at a time

## Architecture

- **Language**: Python 3.13+
- **Framework**: FastAPI with async PostgreSQL (`psycopg3`) and Neo4j (`AsyncResilientNeo4jDriver`)
- **Database**: PostgreSQL 18 (sync history, OAuth token lookup)
- **Graph Database**: Neo4j 2026 (collection graph data)
- **Auth**: HS256 JWT validation (shared `JWT_SECRET_KEY` with API service)
- **Service Port**: 8010
- **Health Port**: 8011

## Configuration

Environment variables:

```bash
# PostgreSQL connection
POSTGRES_ADDRESS=postgres:5432
POSTGRES_USERNAME=discogsography
POSTGRES_PASSWORD=discogsography
POSTGRES_DATABASE=discogsography

# Neo4j connection
NEO4J_ADDRESS=bolt://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=discogsography

# JWT signing secret (must match API service)
JWT_SECRET_KEY=your-secret-key-here

# Discogs API
DISCOGS_USER_AGENT="Discogsography/1.0 +https://github.com/SimplicityGuy/discogsography"

# Optional
LOG_LEVEL=INFO
```

### JWT Authentication

The Curator validates HS256 JWT tokens locally using the shared `JWT_SECRET_KEY`. It does **not** make HTTP calls to the API service at runtime — validation is fully stateless. Tokens are issued by the API service's `/api/auth/login` endpoint.

### Discogs Token Lookup

When a sync is triggered, the Curator reads the user's stored Discogs OAuth access token from the `oauth_tokens` PostgreSQL table. These tokens are written by the API service after the user completes the Discogs OAuth flow (`/api/oauth/verify/discogs`).

## API Endpoints

### Sync Operations

| Method | Path              | Auth Required | Description                                         |
| ------ | ----------------- | ------------- | --------------------------------------------------- |
| POST   | `/api/sync`       | Yes           | Trigger a full collection + wantlist sync           |
| GET    | `/api/sync/status`| Yes           | Get sync history for the current user (last 10)     |

#### Trigger Sync Response

```json
{
  "sync_id": "uuid",
  "status": "started"
}
```

If a sync is already running for the user:

```json
{
  "sync_id": "uuid",
  "status": "already_running"
}
```

#### Sync Status Response

```json
{
  "syncs": [
    {
      "sync_id": "uuid",
      "sync_type": "full",
      "status": "completed",
      "items_synced": 1234,
      "error": null,
      "started_at": "2026-02-22T12:00:00+00:00",
      "completed_at": "2026-02-22T12:05:00+00:00"
    }
  ]
}
```

### Health

| Method | Path      | Port | Description          |
| ------ | --------- | ---- | -------------------- |
| GET    | `/health` | 8010 | Service health check |
| GET    | `/health` | 8011 | Health check port    |

Health response includes `active_syncs` count:

```json
{
  "status": "healthy",
  "service": "curator",
  "active_syncs": 0,
  "timestamp": "2026-02-22T12:00:00+00:00"
}
```

## Sync Flow

1. User calls `POST /api/sync` with a valid JWT token
2. Curator looks up the user's Discogs OAuth token from PostgreSQL
3. A `sync_history` record is created with `status = "running"`
4. A background async task (`run_full_sync`) is launched
5. The task fetches the user's collection and wantlist from the Discogs API
6. Data is written to the Neo4j graph database
7. The `sync_history` record is updated with the final status and item count

Only one sync can run per user at a time — a second trigger returns the existing `sync_id`.

## Development

### Running Locally

```bash
# Install dependencies
uv sync --all-extras

# Run the curator service
uv run python -m curator.curator
```

### Running Tests

```bash
# Run curator tests
uv run pytest tests/curator/ -v

# Run with coverage
just test-curator
```

## Docker

Build and run with Docker:

```bash
# Build
docker build -f curator/Dockerfile .

# Run with docker-compose
docker-compose up curator
```

## Database Schema

The Curator service uses the following tables (created by schema-init):

- `oauth_tokens` — read-only lookup of stored Discogs OAuth access tokens
- `sync_history` — sync job records (`id`, `user_id`, `sync_type`, `status`, `items_synced`, `error_message`, `started_at`, `completed_at`)

Neo4j data is written by `curator/syncer.py` using the same node/relationship model as Graphinator.

## Monitoring

- Health endpoint at `http://localhost:8011/health`
- `active_syncs` field in health response shows concurrent background tasks
- Structured logging with visual emoji prefixes
- Sync progress logged with `🔄` (running), `✅` (completed), `❌` (failed)

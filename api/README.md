# API Service

Provides user account management, JWT authentication, and Discogs OAuth 1.0a integration for Discogsography.

## Overview

The API service:

- Handles user registration and password-based login
- Issues and validates HS256 JWT access tokens
- Manages the Discogs OAuth 1.0a OOB flow for users
- Stores Discogs OAuth access tokens in PostgreSQL
- Reads Discogs app credentials from the `app_config` table (set via `discogs-setup` CLI)

## Architecture

- **Language**: Python 3.13+
- **Framework**: FastAPI with async PostgreSQL (`psycopg3`)
- **Cache**: Redis (OAuth state, graph snapshot persistence, JWT revocation blacklist)
- **Database**: PostgreSQL 18
- **Auth**: HS256 JWT with PBKDF2-SHA256 password hashing
- **Service Port**: 8004
- **Health Port**: 8005

## Configuration

Environment variables:

```bash
# PostgreSQL connection
POSTGRES_HOST=postgres
POSTGRES_USERNAME=discogsography
POSTGRES_PASSWORD=discogsography
POSTGRES_DATABASE=discogsography

# Redis (OAuth state + JTI blacklist storage)
REDIS_HOST=redis

# JWT signing secret
JWT_SECRET_KEY=your-secret-key-here

# Discogs API
DISCOGS_USER_AGENT="Discogsography/1.0 +https://github.com/SimplicityGuy/discogsography"

# OAuth token encryption (Fernet symmetric key — generate with:
# python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
OAUTH_ENCRYPTION_KEY=your-fernet-key-here

# Optional — CORS
CORS_ORIGINS="http://localhost:8003,http://localhost:8006"  # Comma-separated allowed origins

# Optional — Snapshot settings
SNAPSHOT_TTL_DAYS=28     # Default: 28 days
SNAPSHOT_MAX_NODES=100   # Default: 100 nodes per snapshot

# Optional
JWT_EXPIRE_MINUTES=30     # Default: 30 minutes
LOG_LEVEL=INFO
```

### JWT Authentication

All tokens are HS256 JWTs containing:

- `sub`: User UUID (PostgreSQL `users.id`)
- `email`: User email address
- `iat`: Issued-at timestamp
- `exp`: Expiry timestamp

The API service handles all JWT validation locally. No other service requires the `JWT_SECRET_KEY`.

### Discogs OAuth Flow

The API implements Discogs OAuth 1.0a OOB (out-of-band) flow:

1. **Start**: `GET /api/oauth/authorize/discogs` — requests a token from Discogs and returns an authorization URL and state token. State is stored in Redis with a TTL.
1. **Authorize**: User visits the Discogs URL and approves access, receiving a PIN verifier code.
1. **Complete**: `POST /api/oauth/verify/discogs` — exchanges the verifier for a permanent access token, which is stored in the `oauth_tokens` table.

After the flow, the API service uses these tokens to sync the user's Discogs collection and wantlist directly (sync logic migrated from the former Curator service).

## Operator Setup

Before users can connect their Discogs accounts, an operator must configure the Discogs app credentials.

### 1. Register a Discogs Developer App

Go to <https://www.discogs.com/settings/developers> and create a new application to obtain a **Consumer Key** and **Consumer Secret**.

### 2. Store Credentials via the CLI

The `discogs-setup` CLI is included in the API container:

```bash
# Set credentials
docker exec <api-container> discogs-setup \
  --consumer-key YOUR_CONSUMER_KEY \
  --consumer-secret YOUR_CONSUMER_SECRET

# Verify (values are masked)
docker exec <api-container> discogs-setup --show
```

The CLI upserts the values into the `app_config` table using the container's existing database connection environment variables. No service restart is required.

### 3. Verify

After running `--show`, output should resemble:

```
discogs_consumer_key:    ab********************cd
discogs_consumer_secret: ef********************gh
```

### Error Without Credentials

If a user attempts to start the Discogs OAuth flow before credentials are configured, the API returns:

```json
{
  "detail": "Discogs app credentials not configured. Ask an admin to run discogs-setup on the API container."
}
```

## API Endpoints

### Authentication

| Method | Path                 | Auth Required | Rate Limit | Description                      |
| ------ | -------------------- | ------------- | ---------- | -------------------------------- |
| POST   | `/api/auth/register` | No            | 3/min      | Register a new user account      |
| POST   | `/api/auth/login`    | No            | 5/min      | Login and receive JWT token      |
| POST   | `/api/auth/logout`   | Yes           | —          | Revoke JWT token (JTI blacklist) |
| GET    | `/api/auth/me`       | Yes           | —          | Get current user details         |

### Discogs OAuth

| Method | Path                           | Auth Required | Description                           |
| ------ | ------------------------------ | ------------- | ------------------------------------- |
| GET    | `/api/oauth/authorize/discogs` | Yes           | Start Discogs OAuth flow              |
| POST   | `/api/oauth/verify/discogs`    | Yes           | Complete OAuth with verifier code     |
| GET    | `/api/oauth/status/discogs`    | Yes           | Check if Discogs account is connected |
| DELETE | `/api/oauth/revoke/discogs`    | Yes           | Disconnect Discogs account            |

### Graph Queries

All graph query endpoints are served by the API service and consumed by the Explore frontend.

| Method | Path                  | Auth Required | Rate Limit | Description                          |
| ------ | --------------------- | ------------- | ---------- | ------------------------------------ |
| GET    | `/api/autocomplete`   | No            | 30/min     | Search entities with autocomplete    |
| GET    | `/api/explore`        | No            | —          | Get center node with category counts |
| GET    | `/api/expand`         | No            | —          | Expand a category node (paginated)   |
| GET    | `/api/node/{node_id}` | No            | —          | Get full details for a node          |
| GET    | `/api/trends`         | No            | —          | Get time-series release counts       |

### Collection Sync

| Method | Path               | Auth Required | Rate Limit | Description                     |
| ------ | ------------------ | ------------- | ---------- | ------------------------------- |
| POST   | `/api/sync`        | Yes           | 2/10min    | Trigger a full Discogs sync     |
| GET    | `/api/sync/status` | Yes           | —          | Get sync history (last 10 jobs) |

### User Collection

Personalized endpoints that return data from the user's synced Discogs collection.

| Method | Path                         | Auth Required | Description                              |
| ------ | ---------------------------- | ------------- | ---------------------------------------- |
| GET    | `/api/user/collection`       | Yes           | List user's collected releases           |
| GET    | `/api/user/wantlist`         | Yes           | List user's wantlist releases            |
| GET    | `/api/user/recommendations`  | Yes           | Get recommended releases                 |
| GET    | `/api/user/collection/stats` | Yes           | Collection statistics summary            |
| GET    | `/api/user/status`           | Optional      | Check collection/wantlist status for IDs |

### Collection Gap Analysis

"Complete My Collection" endpoints that find releases the user does not own.

| Method | Path                                      | Auth Required | Description                                |
| ------ | ----------------------------------------- | ------------- | ------------------------------------------ |
| GET    | `/api/collection/formats`                 | Yes           | Distinct format names in user's collection |
| GET    | `/api/collection/gaps/label/{label_id}`   | Yes           | Missing releases on a label                |
| GET    | `/api/collection/gaps/artist/{artist_id}` | Yes           | Missing releases by an artist              |
| GET    | `/api/collection/gaps/master/{master_id}` | Yes           | Missing pressings of a master release      |

### Snapshots

Save and restore graph exploration states as shareable URLs.

| Method | Path                    | Auth Required | Description                 |
| ------ | ----------------------- | ------------- | --------------------------- |
| POST   | `/api/snapshot`         | Yes           | Save current graph snapshot |
| GET    | `/api/snapshot/{token}` | No            | Restore a saved snapshot    |

### Unified Search

Full-text search across all entity types using PostgreSQL, with facet counts and result highlighting. Results are cached in Redis for 5 minutes.

| Method | Path          | Auth Required | Rate Limit | Description                                   |
| ------ | ------------- | ------------- | ---------- | --------------------------------------------- |
| GET    | `/api/search` | No            | 30/min     | Search artists, labels, masters, and releases |

**Query parameters:**

- `q` (required) — Search query (minimum 3 characters)
- `types` — Comma-separated entity types to search (default: `artist,label,master,release`)
- `genres` — Comma-separated genre filter
- `year_min` — Minimum release year (1000–9999)
- `year_max` — Maximum release year (1000–9999)
- `limit` — Results per page (1–100, default: 20)
- `offset` — Pagination offset (default: 0)

### Path Finder

Find the shortest path between any two entities in the knowledge graph.

| Method | Path        | Auth Required | Description                              |
| ------ | ----------- | ------------- | ---------------------------------------- |
| GET    | `/api/path` | No            | Shortest path between two named entities |

**Query parameters:**

- `from_name` (required) — Source entity name
- `from_type` — Source entity type (default: `artist`)
- `to_name` (required) — Target entity name
- `to_type` — Target entity type (default: `artist`)
- `max_depth` — Maximum path depth (1–15, default: 10)

### Collaborators

Find artists who share releases with a given artist, with temporal collaboration data (yearly counts, first/last year).

| Method | Path                              | Auth Required | Rate Limit | Description                                          |
| ------ | --------------------------------- | ------------- | ---------- | ---------------------------------------------------- |
| GET    | `/api/collaborators/{artist_id}` | No            | 30/min     | Get collaborating artists with release overlap stats |

**Query parameters:**

- `limit` — Maximum collaborators to return (1–100, default: 20)

### Genre Tree

Full genre/style hierarchy derived from release co-occurrence in the knowledge graph.

| Method | Path              | Auth Required | Rate Limit | Description                                   |
| ------ | ----------------- | ------------- | ---------- | --------------------------------------------- |
| GET    | `/api/genre-tree` | No            | 30/min     | Genre hierarchy with nested styles and counts |

The genre tree is cached in-memory for 5 minutes since the hierarchy changes only on data import.

### Vinyl Archaeology

Time-travel through the knowledge graph with year-range and genre-emergence queries.

| Method | Path                           | Auth Required | Description                                 |
| ------ | ------------------------------ | ------------- | ------------------------------------------- |
| GET    | `/api/explore/year-range`      | No            | Get min/max release years in the graph      |
| GET    | `/api/explore/genre-emergence` | No            | Get genres that emerged before a given year |

**Query parameters for `/api/explore/genre-emergence`:**

- `before_year` (required) — Year cutoff (1900–2030)

### Insights

Proxied endpoints forwarding to the insights microservice for precomputed analytics and music trends. Returns 503 if the insights service is unavailable. The API also exposes internal computation endpoints at `/api/internal/insights/*` that the insights service calls over HTTP to fetch raw Neo4j and PostgreSQL query results.

| Method | Path                              | Auth Required | Description                         |
| ------ | --------------------------------- | ------------- | ----------------------------------- |
| GET    | `/api/insights/top-artists`       | No            | Top artists by release count        |
| GET    | `/api/insights/genre-trends`      | No            | Genre popularity trends over time   |
| GET    | `/api/insights/label-longevity`   | No            | Label longevity rankings            |
| GET    | `/api/insights/this-month`        | No            | Releases and trends for this month  |
| GET    | `/api/insights/data-completeness` | No            | Data quality and completeness stats |
| GET    | `/api/insights/status`            | No            | Computation status of insights data |

### Label DNA

Fingerprint and compare record labels based on their genre, style, format, and decade profiles. Rate limited to 30 requests/minute.

| Method | Path                            | Auth Required | Rate Limit | Description                                    |
| ------ | ------------------------------- | ------------- | ---------- | ---------------------------------------------- |
| GET    | `/api/label/{label_id}/dna`     | No            | 30/min     | Full DNA fingerprint for a label               |
| GET    | `/api/label/{label_id}/similar` | No            | 30/min     | Find labels with closest DNA fingerprint       |
| GET    | `/api/label/dna/compare`        | No            | 30/min     | Side-by-side DNA comparison of multiple labels |

**Query parameters for `/api/label/{label_id}/similar`:**

- `limit` — Number of similar labels to return (1–50, default: 10)

**Query parameters for `/api/label/dna/compare`:**

- `ids` (required) — Comma-separated label IDs (2–5 labels)

### Taste Fingerprint

Personalized taste analysis endpoints based on the authenticated user's synced collection. Requires a minimum of 10 collection items.

| Method | Path                          | Auth Required | Description                                                               |
| ------ | ----------------------------- | ------------- | ------------------------------------------------------------------------- |
| GET    | `/api/user/taste/heatmap`     | Yes           | Genre x decade heatmap of user's collection                               |
| GET    | `/api/user/taste/fingerprint` | Yes           | Full taste fingerprint (heatmap, obscurity, drift, blind spots)           |
| GET    | `/api/user/taste/blindspots`  | Yes           | Genres the user's favourite artists release in but they haven't collected |
| GET    | `/api/user/taste/card`        | Yes           | SVG taste card image (returns `image/svg+xml`)                            |

**Query parameters for `/api/user/taste/blindspots`:**

- `limit` — Number of blind spots to return (1–20, default: 5)

### Collection Timeline

Temporal analysis of the authenticated user's collection, showing how their taste has evolved over time.

| Method | Path                             | Auth Required | Description                                     |
| ------ | -------------------------------- | ------------- | ----------------------------------------------- |
| GET    | `/api/user/collection/timeline`  | Yes           | Release count distribution by year or decade    |
| GET    | `/api/user/collection/evolution` | Yes           | How genre, style, or label mix shifts over time |

**Query parameters for `/api/user/collection/timeline`:**

- `bucket` — Grouping bucket: `year` or `decade` (default: `year`)

**Query parameters for `/api/user/collection/evolution`:**

- `metric` — Evolution metric: `genre`, `style`, or `label` (default: `genre`)

### Health

| Method | Path      | Port | Description          |
| ------ | --------- | ---- | -------------------- |
| GET    | `/health` | 8004 | Service health check |
| GET    | `/health` | 8005 | Health check port    |

## Development

### Running Locally

```bash
# Install dependencies
uv sync --all-extras

# Run the API service
uv run python -m api.api
```

### Running Tests

```bash
# Run API tests
uv run pytest tests/api/ -v

# Run with coverage
just test-api
```

## Docker

Build and run with Docker:

```bash
# Build
docker build -f api/Dockerfile .

# Run with docker-compose
docker-compose up api
```

## Database Schema

The API service uses the following tables (created by schema-init):

- `users` — user accounts (`id`, `email`, `hashed_password`, `is_active`, `created_at`)
- `oauth_tokens` — Discogs OAuth tokens (`user_id`, `provider`, `access_token`, `access_secret`, `provider_username`, `provider_user_id`, `updated_at`)
- `app_config` — admin key-value configuration (`key`, `value`, `updated_at`)

## Security

- **Passwords**: PBKDF2-SHA256 (100,000 iterations, random 32-byte salt)
- **Constant-time auth**: Login and registration use constant-time comparison to prevent user enumeration via timing attacks
- **Blind registration**: Duplicate email registration returns the same 201 response to prevent enumeration
- **JWT revocation**: Logout blacklists the JWT's `jti` claim in Redis with TTL matching the token expiry
- **OAuth tokens encrypted at rest**: Discogs OAuth access tokens are encrypted with Fernet symmetric encryption before database storage (`OAUTH_ENCRYPTION_KEY`)
- **Rate limiting**: register (3/min), login (5/min), sync (2/10min), autocomplete (30/min) via slowapi; per-user sync cooldown (600s) in Redis
- **Security response headers**: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`
- **CORS**: Configurable via `CORS_ORIGINS` env var (disabled by default)
- **Snapshots require auth**: `POST /api/snapshot` requires a valid JWT
- **Container**: All endpoints run as non-root container user (UID 1000)

## Monitoring

- Health endpoint at `http://localhost:8005/health`
- Structured logging with visual emoji prefixes
- Health response includes `service`, `status`, and `timestamp` fields

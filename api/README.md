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

# HKDF master encryption key (derives OAuth + TOTP keys; generate with:
# python -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')
# Required for TOTP 2FA. Without it, OAuth tokens are stored unencrypted and 2FA is disabled.
ENCRYPTION_MASTER_KEY=your-base64-master-key-here

# Optional — Brevo email for password reset notifications (when not set, reset links are logged)
# BREVO_API_KEY=your-brevo-api-key
# BREVO_SENDER_EMAIL=noreply@yourdomain.com
# BREVO_SENDER_NAME=Discogsography

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

### Password Reset

| Method | Path                      | Auth Required | Description                              |
| ------ | ------------------------- | ------------- | ---------------------------------------- |
| POST   | `/api/auth/reset-request` | No            | Request a password reset email/link      |
| POST   | `/api/auth/reset-confirm` | No            | Confirm password reset with token        |

### Two-Factor Authentication (TOTP 2FA)

Requires `ENCRYPTION_MASTER_KEY` to be configured. All 2FA endpoints require JWT authentication.

| Method | Path                    | Auth Required | Description                              |
| ------ | ----------------------- | ------------- | ---------------------------------------- |
| POST   | `/api/auth/2fa/setup`   | Yes           | Generate TOTP secret and QR code URI     |
| POST   | `/api/auth/2fa/confirm` | Yes           | Confirm 2FA setup with TOTP code         |
| POST   | `/api/auth/2fa/verify`  | Yes           | Verify TOTP code during login            |
| POST   | `/api/auth/2fa/recovery`| Yes           | Use a recovery code to bypass 2FA        |
| POST   | `/api/auth/2fa/disable` | Yes           | Disable 2FA for the account              |

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

### Collaboration Network

Multi-hop collaborator traversal, centrality scoring, and community detection via the knowledge graph. Centrality and cluster results are cached in Redis (1h TTL). Rate limited to 30 requests/minute.

| Method | Path                                        | Auth Required | Rate Limit | Description                                          |
| ------ | ------------------------------------------- | ------------- | ---------- | ---------------------------------------------------- |
| GET    | `/api/network/artist/{id}/collaborators`    | No            | 30/min     | Multi-hop collaborators via shared releases (depth 1–3) |
| GET    | `/api/network/artist/{id}/centrality`       | No            | 30/min     | Degree centrality, collaborator count, group/alias counts |
| GET    | `/api/network/cluster/{id}`                 | No            | 30/min     | Community detection via genre-based clustering       |

**Query parameters for `/api/network/artist/{id}/collaborators`:**

- `depth` — Number of hops to traverse (1–3, default: 2)
- `limit` — Maximum collaborators to return (1–200, default: 50)

**Query parameters for `/api/network/cluster/{id}`:**

- `limit` — Maximum cluster members to return (1–200, default: 50)

### Genre Tree

Full genre/style hierarchy derived from release co-occurrence in the knowledge graph.

| Method | Path              | Auth Required | Rate Limit | Description                                   |
| ------ | ----------------- | ------------- | ---------- | --------------------------------------------- |
| GET    | `/api/genre-tree` | No            | 30/min     | Genre hierarchy with nested styles and counts |

The genre tree is cached in-memory for 5 minutes since the hierarchy changes only on data import.

### Graph Statistics

Aggregate node counts across the knowledge graph.

| Method | Path               | Auth Required | Description                                 |
| ------ | ------------------ | ------------- | ------------------------------------------- |
| GET    | `/api/graph/stats` | No            | Total entity counts (artists, labels, releases, masters, genres, styles) |

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

### Natural Language Queries (NLQ)

Natural language query interface for the knowledge graph. Translates plain English questions into graph queries.

| Method | Path              | Auth Required | Description                              |
| ------ | ----------------- | ------------- | ---------------------------------------- |
| GET    | `/api/nlq/status` | No            | Check NLQ service availability           |
| POST   | `/api/nlq/query`  | No            | Execute a natural language query         |

### Release Rarity Scoring

Rarity analysis for releases based on market scarcity, pressing details, and collector demand.

| Method | Path                            | Auth Required | Description                                |
| ------ | ------------------------------- | ------------- | ------------------------------------------ |
| GET    | `/api/rarity/leaderboard`       | No            | Top rarest releases overall                |
| GET    | `/api/rarity/hidden-gems`       | No            | Underappreciated rare releases             |
| GET    | `/api/rarity/artist/{artist_id}`| No            | Rarity scores for an artist's releases     |
| GET    | `/api/rarity/label/{label_id}`  | No            | Rarity scores for a label's releases       |
| GET    | `/api/rarity/{release_id}`      | No            | Rarity score for a specific release        |

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

### Credits & Provenance

Query the credited personnel (producers, engineers, mastering engineers, session musicians, designers) behind releases. Person nodes are created by the graphinator from Discogs `extraartists` data.

| Method | Path                                      | Auth Required | Rate Limit | Description                                                 |
| ------ | ----------------------------------------- | ------------- | ---------- | ----------------------------------------------------------- |
| GET    | `/api/credits/person/{name}`              | No            | 60/min     | All releases a person is credited on, grouped by role       |
| GET    | `/api/credits/person/{name}/timeline`     | No            | 60/min     | Year-by-year credit activity for a person                   |
| GET    | `/api/credits/person/{name}/profile`      | No            | 60/min     | Summary profile with role breakdown                         |
| GET    | `/api/credits/release/{release_id}`       | No            | 60/min     | Full credits breakdown for a release                        |
| GET    | `/api/credits/role/{role}/top`            | No            | 30/min     | Most prolific people in a given role category               |
| GET    | `/api/credits/shared`                     | No            | 30/min     | Releases where two people are both credited                 |
| GET    | `/api/credits/connections/{name}`         | No            | 30/min     | People connected through shared releases                    |
| GET    | `/api/credits/autocomplete`               | No            | 120/min    | Search credits by person name (fulltext, min 2 chars)       |

**Role categories:** `production`, `engineering`, `mastering`, `session`, `design`, `management`, `other`

**Query parameters for `/api/credits/role/{role}/top`:**

- `limit` — Number of entries (1–100, default: 20)

**Query parameters for `/api/credits/shared`:**

- `person1` (required) — First person name
- `person2` (required) — Second person name

**Query parameters for `/api/credits/connections/{name}`:**

- `depth` — Connection depth (1–3, default: 2)
- `limit` — Maximum connections (1–200, default: 50)

**Query parameters for `/api/credits/autocomplete`:**

- `q` (required) — Search query (minimum 2 characters)
- `limit` — Results to return (1–50, default: 10)

### MusicBrainz Enrichment

Endpoints exposing MusicBrainz enrichment data linked to Discogs entities. Requires data from brainzgraphinator (Neo4j) and brainztableinator (PostgreSQL).

| Method | Path                                    | Auth Required | Rate Limit | Description                                              |
| ------ | --------------------------------------- | ------------- | ---------- | -------------------------------------------------------- |
| GET    | `/api/artist/{artist_id}/musicbrainz`   | No            | 30/min     | MusicBrainz metadata (type, gender, dates, area, disambiguation) |
| GET    | `/api/artist/{artist_id}/relationships` | No            | 30/min     | MusicBrainz-sourced relationship edges (collaborations, memberships) |
| GET    | `/api/artist/{artist_id}/external-links`| No            | 30/min     | External links (Wikipedia, Wikidata, AllMusic, Last.fm)  |
| GET    | `/api/enrichment/status`                | No            | 10/min     | Enrichment coverage statistics (MB entities, Discogs matches, Neo4j enriched) |

**Data sources:**

- `/musicbrainz` and `/relationships` — Neo4j (enriched by brainzgraphinator)
- `/external-links` — PostgreSQL `musicbrainz.external_links` table (populated by brainztableinator)
- `/enrichment/status` — Both Neo4j and PostgreSQL

### Internal Insights Computation

Internal endpoints called by the Insights service over HTTP to fetch raw query results. Not intended for direct external use.

| Method | Path                                       | Auth Required | Description                          |
| ------ | ------------------------------------------ | ------------- | ------------------------------------ |
| GET    | `/api/internal/insights/artist-centrality` | No            | Artist centrality data from Neo4j    |
| GET    | `/api/internal/insights/genre-trends`      | No            | Genre trend data from Neo4j          |
| GET    | `/api/internal/insights/label-longevity`   | No            | Label longevity data from Neo4j      |
| GET    | `/api/internal/insights/anniversaries`     | No            | Anniversary data from PostgreSQL     |
| GET    | `/api/internal/insights/data-completeness` | No            | Data completeness from both databases|
| GET    | `/api/internal/insights/rarity-scores`     | No            | Rarity score data from PostgreSQL    |

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
- **OAuth tokens encrypted at rest**: Discogs OAuth access tokens are encrypted with Fernet symmetric encryption using an HKDF-derived key from `ENCRYPTION_MASTER_KEY`
- **TOTP 2FA**: Optional time-based one-time password with `pyotp`, Fernet-encrypted secrets, SHA-256 hashed recovery codes, brute-force lockout
- **Password reset**: Redis-backed tokens (15min TTL), anti-enumeration responses, session revocation on password change
- **Rate limiting**: register (3/min), login (5/min), sync (2/10min), autocomplete (30/min) via slowapi; per-user sync cooldown (600s) in Redis
- **Security response headers**: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`
- **CORS**: Configurable via `CORS_ORIGINS` env var (disabled by default)
- **Snapshots require auth**: `POST /api/snapshot` requires a valid JWT
- **Container**: All endpoints run as non-root container user (UID 1000)

## Monitoring

- Health endpoint at `http://localhost:8005/health`
- Structured logging with visual emoji prefixes
- Health response includes `service`, `status`, and `timestamp` fields

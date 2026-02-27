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
POSTGRES_HOST=postgres:5432
POSTGRES_USERNAME=discogsography
POSTGRES_PASSWORD=discogsography
POSTGRES_DATABASE=discogsography

# Redis (OAuth state + JTI blacklist storage)
REDIS_HOST=redis://redis:6379/0

# JWT signing secret (shared with Curator)
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
JWT_EXPIRE_MINUTES=1440   # Default: 24 hours
LOG_LEVEL=INFO
```

### JWT Authentication

All tokens are HS256 JWTs containing:

- `sub`: User UUID (PostgreSQL `users.id`)
- `email`: User email address
- `iat`: Issued-at timestamp
- `exp`: Expiry timestamp

The same `JWT_SECRET_KEY` must be set in both the API and Curator services. JWT validation is stateless — Curator decodes tokens locally using the shared secret without making HTTP calls to the API.

### Discogs OAuth Flow

The API implements Discogs OAuth 1.0a OOB (out-of-band) flow:

1. **Start**: `GET /api/oauth/authorize/discogs` — requests a token from Discogs and returns an authorization URL and state token. State is stored in Redis with a TTL.
1. **Authorize**: User visits the Discogs URL and approves access, receiving a PIN verifier code.
1. **Complete**: `POST /api/oauth/verify/discogs` — exchanges the verifier for a permanent access token, which is stored in the `oauth_tokens` table.

After the flow, the Curator service can read these tokens to sync the user's Discogs collection and wantlist.

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

| Method | Path                 | Auth Required | Rate Limit | Description                     |
| ------ | -------------------- | ------------- | ---------- | ------------------------------- |
| POST   | `/api/auth/register` | No            | 3/min      | Register a new user account     |
| POST   | `/api/auth/login`    | No            | 5/min      | Login and receive JWT token     |
| POST   | `/api/auth/logout`   | Yes           | —          | Revoke JWT token (JTI blacklist) |
| GET    | `/api/auth/me`       | Yes           | —          | Get current user details        |

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

### Snapshots

Save and restore graph exploration states as shareable URLs.

| Method | Path                    | Auth Required | Description                 |
| ------ | ----------------------- | ------------- | --------------------------- |
| POST   | `/api/snapshot`         | Yes           | Save current graph snapshot |
| GET    | `/api/snapshot/{token}` | No            | Restore a saved snapshot    |

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

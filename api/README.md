# API Service

Provides user account management, JWT authentication, and Discogs OAuth 1.0a integration for Discogsography.

## Overview

The API service:

- Handles user registration and password-based login
- Issues and validates HS256 JWT access tokens
- Manages the Discogs OAuth 1.0a OOB flow for users
- Stores Discogs OAuth access tokens in PostgreSQL
- Exposes an admin endpoint for configuring Discogs app credentials

## Architecture

- **Language**: Python 3.13+
- **Framework**: FastAPI with async PostgreSQL (`psycopg3`)
- **Cache**: Redis (OAuth state storage with TTL)
- **Database**: PostgreSQL 18
- **Auth**: HS256 JWT with PBKDF2-SHA256 password hashing
- **Service Port**: 8004
- **Health Port**: 8005

## Configuration

Environment variables:

```bash
# PostgreSQL connection
POSTGRES_ADDRESS=postgres:5432
POSTGRES_USERNAME=discogsography
POSTGRES_PASSWORD=discogsography
POSTGRES_DATABASE=discogsography

# Redis (OAuth state storage)
REDIS_URL=redis://redis:6379/0

# JWT signing secret (shared with Curator)
JWT_SECRET_KEY=your-secret-key-here

# Discogs API
DISCOGS_USER_AGENT="Discogsography/1.0 +https://github.com/SimplicityGuy/discogsography"

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

## API Endpoints

### Authentication

| Method | Path                 | Auth Required | Description                 |
| ------ | -------------------- | ------------- | --------------------------- |
| POST   | `/api/auth/register` | No            | Register a new user account |
| POST   | `/api/auth/login`    | No            | Login and receive JWT token |
| GET    | `/api/auth/me`       | Yes           | Get current user details    |

### Discogs OAuth

| Method | Path                           | Auth Required | Description                           |
| ------ | ------------------------------ | ------------- | ------------------------------------- |
| GET    | `/api/oauth/authorize/discogs` | Yes           | Start Discogs OAuth flow              |
| POST   | `/api/oauth/verify/discogs`    | Yes           | Complete OAuth with verifier code     |
| GET    | `/api/oauth/status/discogs`    | Yes           | Check if Discogs account is connected |
| DELETE | `/api/oauth/revoke/discogs`    | Yes           | Disconnect Discogs account            |

### Admin

| Method | Path                      | Auth Required | Description                         |
| ------ | ------------------------- | ------------- | ----------------------------------- |
| PUT    | `/api/admin/config/{key}` | Yes           | Set admin config (Discogs app keys) |

**Admin Config Keys**: `discogs_consumer_key`, `discogs_consumer_secret`

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

- Passwords hashed with PBKDF2-SHA256 (100,000 iterations, random 32-byte salt)
- JWT signatures use `hmac.compare_digest` for constant-time comparison
- OAuth state stored in Redis with TTL to prevent replay attacks
- All endpoints run as non-root container user (UID 1000)

## Monitoring

- Health endpoint at `http://localhost:8005/health`
- Structured logging with visual emoji prefixes
- Health response includes `service`, `status`, and `timestamp` fields

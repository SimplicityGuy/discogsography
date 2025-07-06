# Dockerfile Standards

This document defines the standards and best practices for all Dockerfiles in the discogsography project.

## Structure

All Dockerfiles follow a consistent multi-stage build pattern:

1. **Builder Stage**: Compile dependencies and prepare the application
1. **Runtime Stage**: Minimal runtime environment with security hardening

## Build Arguments

```dockerfile
# Build arguments (at top of file)
ARG PYTHON_VERSION=3.13
ARG UID=1000
ARG GID=1000

# Runtime stage arguments (for labels)
ARG BUILD_DATE
ARG BUILD_VERSION
ARG VCS_REF
ARG UID=1000
ARG GID=1000
```

## Best Practices

### 1. Build Caching

Always use cache mounts for dependency installation:

```dockerfile
RUN --mount=type=cache,target=/tmp/.cache/uv \
    uv sync --frozen --no-dev --extra <service-name>
```

### 2. Layer Optimization

Copy dependency files before source code:

```dockerfile
# Copy dependency files first
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN --mount=type=cache,target=/tmp/.cache/uv \
    uv sync --frozen --no-dev --extra <service-name>

# Copy source files after dependencies
COPY common/ ./common/
COPY <service>/ ./<service>/
```

### 3. User Creation

Create users with configurable UID/GID and the `-l` flag:

```dockerfile
RUN groupadd -r -g ${GID} discogsography && \
    useradd -r -l -u ${UID} -g discogsography -m -s /bin/bash discogsography && \
    mkdir -p /tmp /app && \
    chown -R discogsography:discogsography /tmp /app
```

### 4. Package Installation

Never use `DEBIAN_FRONTEND` in ENV, only in RUN commands:

```dockerfile
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        curl \
        <other-packages> && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
```

### 5. Health Checks

Use HTTP endpoint checks for all services:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
```

### 6. Security

Add security documentation:

```dockerfile
# Security: This container should be run with:
# docker run --cap-drop=ALL --security-opt=no-new-privileges:true ...

CMD ["/app/start.sh"]
```

### 7. Labels

Use OCI Image Spec annotations:

```dockerfile
LABEL org.opencontainers.image.title="Discogsography <Service>" \
      org.opencontainers.image.description="<Description>" \
      org.opencontainers.image.authors="Robert Wlodarczyk <robert@simplicityguy.com>" \
      org.opencontainers.image.url="https://github.com/SimplicityGuy/discogsography" \
      org.opencontainers.image.documentation="https://github.com/SimplicityGuy/discogsography/blob/main/README.md" \
      org.opencontainers.image.source="https://github.com/SimplicityGuy/discogsography" \
      org.opencontainers.image.vendor="SimplicityGuy" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${BUILD_VERSION:-0.1.0}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.base.name="docker.io/library/python:${PYTHON_VERSION}-slim" \
      com.discogsography.service="<service-name>" \
      com.discogsography.dependencies="<comma-separated-deps>" \
      com.discogsography.python.version="${PYTHON_VERSION}"
```

### 8. Environment Variables

Set minimal environment variables, with empty defaults for secrets:

```dockerfile
ENV HOME=/home/discogsography \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH" \
    # Service-specific vars with empty defaults
    AMQP_CONNECTION="" \
    <OTHER_SERVICE_VARS>=""
```

## Service-Specific Additions

### Dashboard

- Expose port: `EXPOSE 8003`
- Health check endpoint: `/health` or `/api/metrics`

### Extractor

- Volume for data: `VOLUME ["/discogs-data"]`
- Additional env: `DISCOGS_ROOT="/discogs-data"`

### Tableinator

- Additional package: `libpq5` for PostgreSQL client

## Validation

Run hadolint on all Dockerfiles:

```bash
docker run --rm -v "$PWD":/workspace:ro hadolint/hadolint:latest \
    hadolint /workspace/*/Dockerfile
```

## Security Considerations

1. **No hardcoded secrets**: All credentials use empty environment variables
1. **Non-root user**: All containers run as UID/GID 1000 (configurable)
1. **Minimal attack surface**: Only install required packages
1. **Capability dropping**: Document `--cap-drop=ALL` usage
1. **No new privileges**: Document `--security-opt=no-new-privileges:true`
1. **Read-only root filesystem**: Compatible with `--read-only` flag

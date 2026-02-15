# Dockerfile Standards and Guidelines

This document defines the standardized patterns and best practices for all Dockerfiles in the Discogsography project.

## 🎯 Overview

All Dockerfiles must follow these standards to ensure consistency, security, and maintainability across the project.

## 📐 Structure Template

```dockerfile
# syntax=docker/dockerfile:1

# Build arguments
ARG PYTHON_VERSION=3.13
ARG UID=1000
ARG GID=1000

# === BUILDER STAGE ===
FROM python:${PYTHON_VERSION}-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /bin/uv

# Set environment for build
ENV UV_SYSTEM_PYTHON=1 \
    UV_CACHE_DIR=/tmp/.cache/uv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock README.md ./
COPY common/pyproject.toml ./common/
COPY <service>/pyproject.toml ./<service>/

# Install dependencies
RUN --mount=type=cache,target=/tmp/.cache/uv \
    uv sync --frozen --no-dev --extra <service>

# Copy source files
COPY common/ ./common/
COPY <service>/ ./<service>/

# === FINAL STAGE ===
FROM python:${PYTHON_VERSION}-slim

# Build arguments for labels
ARG BUILD_DATE
ARG BUILD_VERSION
ARG VCS_REF
ARG UID=1000
ARG GID=1000

# OCI Image Spec Annotations
# [Labels section - see below]

# Install security updates and service-specific packages
# [Package installation section - see below]

# Create user and directories
# [User creation section - see below]

WORKDIR /app

# Copy from builder
COPY --from=builder --chown=discogsography:discogsography /app /app

# Install uv for runtime
COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /bin/uv

# Create startup script
# [Startup script section - see below]

# Health check
# [Health check section - see below]

USER discogsography:discogsography

# Environment variables
# [Environment section - see below]

# Expose ports (if applicable)
# [Port exposure section - see below]

# Declare volumes
VOLUME ["/logs"]

# Security comment
# Security: This container should be run with:
# docker run --cap-drop=ALL --security-opt=no-new-privileges:true ...

CMD ["/app/start.sh"]
```

## 📋 Section Standards

### 1. Build Arguments

Always define at the top:

```dockerfile
ARG PYTHON_VERSION=3.13
ARG UID=1000
ARG GID=1000
```

### 2. OCI Labels

Standardized format with service-specific variations:

```dockerfile
LABEL org.opencontainers.image.title="Discogsography <Service>" \
      org.opencontainers.image.description="<Service description>" \
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
      com.discogsography.service="<service>" \
      com.discogsography.dependencies="<comma-separated-list>" \
      com.discogsography.python.version="${PYTHON_VERSION}"
```

Additional labels for database services:

- `com.discogsography.database="postgresql"` (tableinator)
- `com.discogsography.database="neo4j"` (graphinator)

### 3. Package Installation

Base template:

```dockerfile
# Install security updates and curl for healthcheck
# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
```

Service-specific additions:

- **tableinator**: Add `libpq5` for PostgreSQL client libraries

### 4. User and Directory Creation

Standard format for all services:

```dockerfile
# Create user and directories with configurable UID/GID
RUN groupadd -r -g ${GID} discogsography && \
    useradd -r -l -u ${UID} -g discogsography -m -s /bin/bash discogsography && \
    mkdir -p /tmp /app /logs && \
    chown -R discogsography:discogsography /tmp /app /logs
```

Additional directories:

- **extractor**: Add `/discogs-data` directory
- **extractor**: Add `/discogs-data` directory

### 5. Startup Script

Standard format:

```dockerfile
# Create startup script
# hadolint ignore=SC2016
RUN printf '#!/bin/sh\nset -e\nsleep "${STARTUP_DELAY:-0}"\nexec /app/.venv/bin/python -m <service>.<service> "$@"\n' > /app/start.sh && \
    chmod +x /app/start.sh
```

### 6. Health Check

HTTP-based (default):

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:<port>/health || exit 1
```

Process-based (graphinator only):

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD pgrep -f "python.*graphinator" > /dev/null || exit 1
```

### 7. Environment Variables

Base environment (all services):

```dockerfile
ENV HOME=/home/discogsography \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH" \
    AMQP_CONNECTION=""
```

Service-specific additions:

- **dashboard**: All database connections
- **extractor**: `DISCOGS_ROOT="/discogs-data"` and `PERIODIC_CHECK_DAYS="15"`
- **extractor**: `DISCOGS_ROOT="/discogs-data"` and `PERIODIC_CHECK_DAYS="15"`
- **graphinator**: Neo4j connections
- **tableinator**: PostgreSQL connections

### 8. Port Exposure

Only expose ports for services with HTTP endpoints:

- **dashboard**: `EXPOSE 8003`

### 9. Volume Declaration

Standard volume:

```dockerfile
VOLUME ["/logs"]
```

Additional volumes:

- **extractor**: Add `"/discogs-data"`
- **extractor**: Add `"/discogs-data"`

## 🔧 Service-Specific Requirements

### Dashboard

- Standard configuration

- Expose port 8003

- All database connections in environment

- Install gcc/g++ for ML libraries

- Expose ports 8004 and 8005

- All database connections in environment

### Python Extractor (extractor)

- Create /discogs-data directory
- Add /discogs-data volume
- Special environment variables for Discogs configuration

### Extractor (extractor)

- Rust-based container using multi-stage build
- Create /discogs-data directory
- Add /discogs-data volume
- Special environment variables for Discogs configuration

### Graphinator

- Process-based health check (no HTTP endpoint)
- Neo4j connection environment variables

### Tableinator

- Install libpq5 for PostgreSQL
- PostgreSQL connection environment variables

## ✅ Quality Checklist

Before committing any Dockerfile:

1. **Structure**: Follows the standard template order
1. **Comments**: Includes all standard comments and hadolint ignores
1. **Labels**: All OCI labels present with correct values
1. **Security**: Security comment present at bottom
1. **Health Check**: Appropriate health check for service type
1. **Environment**: All required environment variables defined
1. **Volumes**: /logs volume declared (plus service-specific)
1. **User**: Runs as discogsography user
1. **Caching**: Uses BuildKit cache mounts
1. **Linting**: Passes hadolint validation

## 🛡️ Security Standards

1. **Non-root execution**: All containers run as UID/GID 1000
1. **Minimal packages**: Only install what's needed
1. **Security updates**: Always run `apt-get upgrade`
1. **Clean up**: Remove apt lists after installation
1. **Capability dropping**: Document in security comment
1. **Read-only root**: Can be enabled with tmpfs mounts

## 📝 Maintenance

When updating Dockerfiles:

1. Update this document if adding new patterns
1. Apply changes consistently across all services
1. Test builds for all services
1. Update docker-compose.yml if needed
1. Verify health checks still function

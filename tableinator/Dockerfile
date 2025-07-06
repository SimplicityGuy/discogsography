# syntax=docker/dockerfile:1

# Python version build argument
ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.5.19 /uv /bin/uv

# Set environment for build
ENV UV_SYSTEM_PYTHON=1 \
    UV_CACHE_DIR=/tmp/.cache/uv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN --mount=type=cache,target=/tmp/.cache/uv \
    uv sync --frozen --no-dev --extra tableinator

# Copy source files
COPY common/ ./common/
COPY tableinator/ ./tableinator/

# Final stage
FROM python:${PYTHON_VERSION}-slim

# Build arguments for dynamic labels
ARG PYTHON_VERSION=3.13
ARG BUILD_DATE
ARG BUILD_VERSION
ARG VCS_REF

# OCI Image Spec Annotations
# https://github.com/opencontainers/image-spec/blob/main/annotations.md
LABEL org.opencontainers.image.title="Discogsography Tableinator" \
      org.opencontainers.image.description="Consumes messages from AMQP queues and imports Discogs data into PostgreSQL relational database. Stores artists, labels, masters, and releases in normalized tables with connection pooling." \
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
      com.discogsography.service="tableinator" \
      com.discogsography.dependencies="psycopg[binary],aio-pika" \
      com.discogsography.python.version="${PYTHON_VERSION}" \
      com.discogsography.database="postgresql"

# Install security updates, PostgreSQL client libraries, and curl for healthcheck
# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        curl \
        libpq5 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create user
RUN groupadd -r -g 1000 discogsography && \
    useradd -r -u 1000 -g discogsography -m -s /bin/bash discogsography

WORKDIR /app

# Copy from builder
COPY --from=builder --chown=discogsography:discogsography /app /app

# Install uv for runtime
COPY --from=ghcr.io/astral-sh/uv:0.5.19 /uv /bin/uv

# Create startup script
# hadolint ignore=SC2016
RUN printf '#!/bin/sh\nset -e\nsleep "${STARTUP_DELAY:-0}"\nexec uv run python -m tableinator.tableinator "$@"\n' > /app/start.sh && \
    chmod +x /app/start.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD pgrep -f "python.*tableinator" > /dev/null || exit 1

USER discogsography:discogsography

# Environment variables
ENV HOME=/home/discogsography \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH" \
    AMQP_CONNECTION="" \
    POSTGRES_ADDRESS="" \
    POSTGRES_USERNAME="" \
    POSTGRES_PASSWORD="" \
    POSTGRES_DATABASE=""

CMD ["/app/start.sh"]

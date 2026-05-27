# syntax=docker/dockerfile:1

# Build arguments
ARG PYTHON_VERSION=3.13
ARG UID=1001
ARG GID=1001

# nosemgrep: dockerfile.security.missing-user.missing-user
FROM python:${PYTHON_VERSION}-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /bin/uv

# Set environment for build
ENV UV_SYSTEM_PYTHON=1 \
    UV_CACHE_DIR=/tmp/.cache/uv \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock README.md ./
COPY common/pyproject.toml ./common/
COPY digger/pyproject.toml ./digger/

# Install dependencies and clean up
# hadolint ignore=SC2015
RUN --mount=type=cache,target=/tmp/.cache/uv \
    uv sync --frozen --no-dev --extra digger && \
    find /app/.venv -type f -name "*.pyc" -delete && \
    find /app/.venv -type f -name "*.pyo" -delete && \
    find /app/.venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find /app/.venv -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true && \
    find /app/.venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true && \
    find /app/.venv -name "*.so" -exec strip --strip-unneeded {} \; 2>/dev/null || true

# Copy source files
COPY common/ ./common/
COPY digger/ ./digger/

# Final stage
FROM python:${PYTHON_VERSION}-slim

# Build arguments for labels
ARG BUILD_DATE
ARG BUILD_VERSION
ARG VCS_REF
ARG UID=1001
ARG GID=1001

# OCI Image Spec Annotations
# https://github.com/opencontainers/image-spec/blob/main/annotations.md
LABEL org.opencontainers.image.title="Discogsography Digger" \
      org.opencontainers.image.description="Discogs marketplace scraper and wantlist scheduler. Polls listings under a Redis token-bucket rate budget and generates per-user reports on configurable cadence." \
      org.opencontainers.image.authors="Robert Wlodarczyk <robert@simplicityguy.com>" \
      org.opencontainers.image.url="https://github.com/SimplicityGuy/discogsography" \
      org.opencontainers.image.documentation="https://github.com/SimplicityGuy/discogsography/blob/main/README.md" \
      org.opencontainers.image.source="https://github.com/SimplicityGuy/discogsography" \
      org.opencontainers.image.vendor="SimplicityGuy" \
      org.opencontainers.image.licenses="PolyForm-Noncommercial-1.0.0" \
      org.opencontainers.image.version="${BUILD_VERSION:-0.1.0}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.base.name="docker.io/library/python:${PYTHON_VERSION}-slim" \
      com.discogsography.service="digger" \
      com.discogsography.dependencies="httpx,psycopg[binary],pydantic,redis,selectolax,bleach" \
      com.discogsography.python.version="${PYTHON_VERSION}" \
      com.discogsography.database="postgresql"

# Install minimal runtime dependencies
# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        curl \
        libpq5 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Create user and directories with configurable UID/GID
RUN groupadd -r -g ${GID} digger && \
    useradd -r -l -u ${UID} -g digger -m -s /bin/bash digger && \
    mkdir -p /tmp /app /logs && \
    chown -R digger:digger /tmp /app /logs

WORKDIR /app

# Copy only necessary files from builder
COPY --from=builder --chown=digger:digger /app/.venv /app/.venv
COPY --from=builder --chown=digger:digger /app/common /app/common
COPY --from=builder --chown=digger:digger /app/digger /app/digger

# UV not needed at runtime

# Create startup script
# hadolint ignore=SC2016
RUN printf '#!/bin/sh\nset -e\nsleep "${STARTUP_DELAY:-0}"\nexec /app/.venv/bin/python -m digger.main "$@"\n' > /app/start.sh && \
    chmod +x /app/start.sh

EXPOSE 8012

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8012/health || exit 1

USER digger:digger

# Environment variables
ENV HOME=/home/digger \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH" \
    POSTGRES_HOST="" \
    POSTGRES_USERNAME="" \
    POSTGRES_DATABASE=""

# Declare volume for logs
VOLUME ["/logs"]

# Security: This container should be run with:
# docker run --cap-drop=ALL --security-opt=no-new-privileges:true ...

CMD ["/app/start.sh"]

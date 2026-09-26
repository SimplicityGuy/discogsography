# syntax=docker/dockerfile:1

# Build arguments
ARG PYTHON_VERSION=3.13
ARG UID=1000
ARG GID=1000

# nosemgrep: dockerfile.security.missing-user.missing-user
FROM python:${PYTHON_VERSION}-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv

# Set environment for build
ENV UV_SYSTEM_PYTHON=1 \
    UV_CACHE_DIR=/tmp/.cache/uv \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy dependency files first for better caching. Every workspace member the
# sync resolves (groovemap-runtime in common/, groovemap-agent-tools in
# common/agent-tools/) needs its manifest here, or `uv sync --frozen` fails.
COPY pyproject.toml uv.lock README.md ./
COPY common/pyproject.toml common/README.md ./common/
COPY common/agent-tools/pyproject.toml common/agent-tools/README.md ./common/agent-tools/
COPY brainztableinator/pyproject.toml ./brainztableinator/

# Install third-party dependencies (cached layer); workspace members need their
# sources, so they are installed after the COPY below
RUN --mount=type=cache,target=/tmp/.cache/uv \
    uv sync --frozen --no-dev --extra brainztableinator --no-install-workspace

# Copy source files
COPY common/ ./common/
COPY brainztableinator/ ./brainztableinator/

# Install workspace members, then clean up. The sync must fail the build on
# error — a swallowed failure once shipped images with an empty .venv — so it
# runs under `set -e` and only the cleanup steps are best-effort.
RUN --mount=type=cache,target=/tmp/.cache/uv \
    set -e; \
    uv sync --frozen --no-dev --extra brainztableinator; \
    find /app/.venv -type f -name "*.pyc" -delete || true; \
    find /app/.venv -type f -name "*.pyo" -delete || true; \
    find /app/.venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true; \
    find /app/.venv -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true; \
    find /app/.venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true; \
    find /app/.venv -name "*.so" -exec strip --strip-unneeded {} \; 2>/dev/null || true

# Final stage
FROM python:${PYTHON_VERSION}-slim

# Build arguments for labels
ARG BUILD_DATE
ARG BUILD_VERSION
ARG VCS_REF
ARG UID=1000
ARG GID=1000

# OCI Image Spec Annotations
# https://github.com/opencontainers/image-spec/blob/main/annotations.md
LABEL org.opencontainers.image.title="Discogsography Brainztableinator" \
      org.opencontainers.image.description="Consumes MusicBrainz messages from AMQP queues and imports data into PostgreSQL relational database. Stores artists, labels, and releases in normalized tables with connection pooling." \
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
      com.discogsography.service="brainztableinator" \
      com.discogsography.dependencies="psycopg[binary],aio-pika" \
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
RUN groupadd -r -g ${GID} discogsography && \
    useradd -r -l -u ${UID} -g discogsography -m -s /bin/bash discogsography && \
    mkdir -p /tmp /app /logs && \
    chown -R discogsography:discogsography /tmp /app /logs

WORKDIR /app

# Copy only necessary files from builder
COPY --from=builder --chown=discogsography:discogsography /app/.venv /app/.venv
COPY --from=builder --chown=discogsography:discogsography /app/common /app/common
COPY --from=builder --chown=discogsography:discogsography /app/brainztableinator /app/brainztableinator

# Fail the build if the shipped venv cannot import the service's dependencies
RUN /app/.venv/bin/python -c "import psycopg, aio_pika, common.config"

# UV not needed at runtime

# Create startup script
# hadolint ignore=SC2016
RUN printf '#!/bin/sh\nset -e\nsleep "${STARTUP_DELAY:-0}"\nexec /app/.venv/bin/python -m brainztableinator.brainztableinator "$@"\n' > /app/start.sh && \
    chmod +x /app/start.sh

EXPOSE 8010

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["curl", "-f", "http://localhost:8010/health"]

# UID/GID build arguments resolve to numeric IDs; DL3066 cannot infer their values.
# hadolint ignore=DL3066
USER ${UID}:${GID}

# Environment variables
ENV HOME=/home/discogsography \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH" \
    POSTGRES_HOST="" \
    POSTGRES_DATABASE=""

# Declare volume for logs
VOLUME ["/logs"]

# Security: This container should be run with:
# docker run --cap-drop=ALL --security-opt=no-new-privileges:true ...

CMD ["/app/start.sh"]

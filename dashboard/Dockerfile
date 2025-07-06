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
COPY common/pyproject.toml ./common/
COPY dashboard/pyproject.toml ./dashboard/

# Copy source code needed for build
COPY common/ ./common/

# Install dependencies
RUN uv sync --frozen --no-dev

# Runtime stage
FROM python:${PYTHON_VERSION}-slim

# Build arguments for labels
ARG BUILD_DATE
ARG BUILD_VERSION
ARG VCS_REF
ARG PYTHON_VERSION

# OCI annotations
# https://github.com/opencontainers/image-spec/blob/main/annotations.md
LABEL org.opencontainers.image.title="Discogsography Dashboard" \
      org.opencontainers.image.description="Real-time monitoring dashboard for discogsography services with WebSocket updates" \
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
      com.discogsography.service="dashboard" \
      com.discogsography.dependencies="fastapi,uvicorn,websockets,httpx" \
      com.discogsography.python.version="${PYTHON_VERSION}"

# Install security updates and curl for healthcheck
# hadolint ignore=DL3008
RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get upgrade -y && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create user and directories
RUN groupadd -r -g 1000 discogsography && \
    useradd -r -u 1000 -g discogsography -m -s /bin/bash discogsography

WORKDIR /app

# Copy from builder
COPY --from=builder --chown=discogsography:discogsography /app /app

# Install uv for runtime
COPY --from=ghcr.io/astral-sh/uv:0.5.19 /uv /bin/uv

# Create startup script
# hadolint ignore=SC2016
RUN printf '#!/bin/sh\nset -e\nsleep "${STARTUP_DELAY:-0}"\nexec uv run python -m dashboard.dashboard "$@"\n' > /app/start.sh && \
    chmod +x /app/start.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8003/api/metrics || exit 1

USER discogsography:discogsography

# Environment variables
ENV HOME=/home/discogsography \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH" \
    AMQP_CONNECTION="" \
    NEO4J_ADDRESS="" \
    NEO4J_USERNAME="" \
    NEO4J_PASSWORD="" \
    POSTGRES_ADDRESS="" \
    POSTGRES_USERNAME="" \
    POSTGRES_PASSWORD="" \
    POSTGRES_DATABASE=""

EXPOSE 8003

# No additional runtime configuration needed

# Run the dashboard
CMD ["/app/start.sh"]

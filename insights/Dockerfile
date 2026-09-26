# syntax=docker/dockerfile:1

# Build arguments
ARG PYTHON_VERSION=3.13
ARG UID=1000
ARG GID=1000

# nosemgrep: dockerfile.security.missing-user.missing-user
FROM python:${PYTHON_VERSION}-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv

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
COPY insights/pyproject.toml ./insights/

# Install third-party dependencies (cached layer); workspace members need their
# sources, so they are installed after the COPY below
RUN --mount=type=cache,target=/tmp/.cache/uv \
    uv sync --frozen --no-dev --extra insights --no-install-workspace

# Copy source files
COPY common/ ./common/
COPY insights/ ./insights/

# Install workspace members, then clean up. The sync must fail the build on
# error — a swallowed failure once shipped images with an empty .venv — so it
# runs under `set -e` and only the cleanup steps are best-effort.
RUN --mount=type=cache,target=/tmp/.cache/uv \
    set -e; \
    uv sync --frozen --no-dev --extra insights; \
    find /app/.venv -type f -name "*.pyc" -delete || true; \
    find /app/.venv -type f -name "*.pyo" -delete || true; \
    find /app/.venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true; \
    find /app/.venv -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true; \
    find /app/.venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true; \
    find /app/.venv -name "py.typed" -delete 2>/dev/null || true; \
    find /app/.venv -name "*.so" -exec strip --strip-unneeded {} \; 2>/dev/null || true

# Final stage
FROM python:${PYTHON_VERSION}-slim

ARG BUILD_DATE
ARG BUILD_VERSION
ARG VCS_REF
ARG UID=1000
ARG GID=1000

LABEL org.opencontainers.image.title="Discogsography Insights" \
      org.opencontainers.image.description="Precomputed analytics and music trends for Discogsography." \
      org.opencontainers.image.authors="Robert Wlodarczyk <robert@simplicityguy.com>" \
      org.opencontainers.image.url="https://github.com/SimplicityGuy/discogsography" \
      org.opencontainers.image.source="https://github.com/SimplicityGuy/discogsography" \
      org.opencontainers.image.vendor="SimplicityGuy" \
      org.opencontainers.image.licenses="PolyForm-Noncommercial-1.0.0" \
      org.opencontainers.image.version="${BUILD_VERSION:-0.1.0}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.base.name="docker.io/library/python:${PYTHON_VERSION}-slim" \
      com.discogsography.service="insights" \
      com.discogsography.python.version="${PYTHON_VERSION}"

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN groupadd -r -g ${GID} discogsography && \
    useradd -r -l -u ${UID} -g discogsography -m -s /bin/bash discogsography && \
    mkdir -p /tmp /app /logs && \
    chown -R discogsography:discogsography /tmp /app /logs

WORKDIR /app

COPY --from=builder --chown=discogsography:discogsography /app/.venv /app/.venv
COPY --from=builder --chown=discogsography:discogsography /app/common /app/common
COPY --from=builder --chown=discogsography:discogsography /app/insights /app/insights

# Fail the build if the shipped venv cannot import the service's dependencies
RUN /app/.venv/bin/python -c "import fastapi, uvicorn, httpx, psycopg, neo4j, redis, common.config"

# hadolint ignore=SC2016
RUN printf '#!/bin/sh\nset -e\nsleep "${STARTUP_DELAY:-0}"\nexec /app/.venv/bin/python -m insights.insights "$@"\n' > /app/start.sh && \
    chmod +x /app/start.sh

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["curl", "-f", "http://localhost:8009/health"]

# UID/GID build arguments resolve to numeric IDs; DL3066 cannot infer their values.
# hadolint ignore=DL3066
USER ${UID}:${GID}

ENV HOME=/home/discogsography \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH"

EXPOSE 8008 8009

VOLUME ["/logs"]

CMD ["/app/start.sh"]

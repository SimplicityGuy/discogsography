# syntax=docker/dockerfile:1

# Build arguments
ARG PYTHON_VERSION=3.13
ARG UID=1000
ARG GID=1000

FROM python:${PYTHON_VERSION}-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.9.28 /uv /bin/uv

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
COPY discovery/pyproject.toml ./discovery/
COPY discovery/constraints.txt ./discovery/

# Install dependencies (sentence-transformers[onnx] excludes PyTorch)
# hadolint ignore=SC2015
RUN --mount=type=cache,target=/tmp/.cache/uv \
    uv sync --frozen --no-dev --extra discovery && \
    # Clean up unnecessary files from site-packages
    find /app/.venv -type f -name "*.pyc" -delete && \
    find /app/.venv -type f -name "*.pyo" -delete && \
    find /app/.venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find /app/.venv -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true && \
    find /app/.venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true && \
    # Remove unnecessary torch files if present
    find /app/.venv -type f -name "*.cpp" -delete 2>/dev/null || true && \
    find /app/.venv -type f -name "*.cu" -delete 2>/dev/null || true && \
    find /app/.venv -type f -name "*.cuh" -delete 2>/dev/null || true && \
    find /app/.venv -type f -name "*.h" -delete 2>/dev/null || true && \
    # Strip debug symbols from compiled libraries
    find /app/.venv -name "*.so" -exec strip --strip-unneeded {} \; 2>/dev/null || true

# Copy source files
COPY common/ ./common/
COPY discovery/ ./discovery/

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
LABEL org.opencontainers.image.title="Discogsography Discovery" \
      org.opencontainers.image.description="Music discovery and analytics service with AI-powered recommendations, semantic search, and advanced visualizations." \
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
      com.discogsography.service="discovery" \
      com.discogsography.dependencies="fastapi,onnxruntime,scikit-learn,plotly" \
      com.discogsography.python.version="${PYTHON_VERSION}"

# Install minimal runtime dependencies
# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        curl \
        libgomp1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Create user and directories with configurable UID/GID
RUN groupadd -r -g ${GID} discogsography && \
    useradd -r -l -u ${UID} -g discogsography -m -s /bin/bash discogsography && \
    mkdir -p /tmp /app /logs /models && \
    chown -R discogsography:discogsography /tmp /app /logs /models

WORKDIR /app

# Copy only necessary files from builder
COPY --from=builder --chown=discogsography:discogsography /app/.venv /app/.venv
COPY --from=builder --chown=discogsography:discogsography /app/common /app/common
COPY --from=builder --chown=discogsography:discogsography /app/discovery /app/discovery
COPY --from=builder --chown=discogsography:discogsography /app/pyproject.toml /app/uv.lock /app/

# We don't need uv at runtime since we're not installing packages

# Create startup script
# hadolint ignore=SC2016
RUN printf '#!/bin/sh\nset -e\nsleep "${STARTUP_DELAY:-0}"\nexec /app/.venv/bin/python -m discovery.discovery "$@"\n' > /app/start.sh && \
    chmod +x /app/start.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8004/health || exit 1

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
    POSTGRES_ADDRESS="" \
    POSTGRES_USERNAME="" \
    POSTGRES_DATABASE=""

# Declare volumes
VOLUME ["/logs", "/models"]

# Expose ports
EXPOSE 8004 8005

# Security: This container should be run with:
# docker run --cap-drop=ALL --security-opt=no-new-privileges:true ...

CMD ["/app/start.sh"]

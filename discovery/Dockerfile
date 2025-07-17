# Discovery Service Dockerfile
ARG PYTHON_VERSION=3.13
FROM python:${PYTHON_VERSION}-slim

# Metadata
LABEL org.opencontainers.image.title="Discogsography Discovery"
LABEL org.opencontainers.image.description="Music discovery and analytics service"
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.source="https://github.com/SimplicityGuy/discogsography"

# Security: Create non-root user
RUN groupadd -r discovery && useradd -r -g discovery discovery

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./
COPY discovery/pyproject.toml ./discovery/

# Install uv and dependencies
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# Copy application code
COPY common/ ./common/
COPY discovery/ ./discovery/

# Install discovery service
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# Create logs directory
RUN mkdir -p /logs && chown discovery:discovery /logs

# Security hardening
USER discovery

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8004/health || exit 1

# Expose ports
EXPOSE 8004 8005

# Start discovery service
CMD ["uv", "run", "python", "discovery/discovery.py"]

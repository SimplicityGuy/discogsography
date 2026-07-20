# Build stage
FROM rust:1.96-slim AS builder

# Install build dependencies
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy Cargo files from extractor subdirectory
COPY Cargo.lock ./
COPY extractor/Cargo.toml ./
COPY extractor/benches ./benches

# Create dummy main to cache dependencies
RUN mkdir src && \
    echo "fn main() {}" > src/main.rs && \
    cargo build --release && \
    rm -rf src

# Copy actual source code from extractor subdirectory
COPY extractor/src ./src

# Build the application
RUN touch src/main.rs && \
    cargo build --release

# Runtime stage
FROM debian:13-slim

# Build arguments for configurable UID/GID (must match the compose `user:` override)
ARG UID=1000
ARG GID=1000

# Install runtime dependencies
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libssl3t64 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user with a fixed UID/GID so file ownership matches the
# runtime user regardless of any `useradd -r` system-UID auto-allocation.
RUN groupadd -r -g ${GID} extractor && useradd -r -l -u ${UID} -g extractor extractor

# Create necessary directories
RUN mkdir -p /discogs-data /musicbrainz-data /logs && \
    chown -R extractor:extractor /discogs-data /musicbrainz-data /logs

# Copy binary from builder
COPY --from=builder /app/target/release/extractor /usr/local/bin/extractor

# Switch to non-root user
USER extractor:extractor

# Set environment variables
ENV LOG_LEVEL=INFO
ENV RUST_EXTRACTOR_CONFIG=/config.toml

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose health port
EXPOSE 8000

# Run the application
ENTRYPOINT ["extractor"]

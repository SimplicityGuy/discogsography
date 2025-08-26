# Build stage
FROM rust:1.89-slim AS builder

# Install build dependencies
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy Cargo files and benchmark directory from extractor/rustextractor subdirectory
COPY extractor/rustextractor/Cargo.toml extractor/rustextractor/Cargo.lock ./
COPY extractor/rustextractor/benches ./benches

# Create dummy main to cache dependencies
RUN mkdir src && \
    echo "fn main() {}" > src/main.rs && \
    cargo build --release && \
    rm -rf src

# Copy actual source code from extractor/rustextractor subdirectory
COPY extractor/rustextractor/src ./src

# Build the application
RUN touch src/main.rs && \
    cargo build --release

# Runtime stage
FROM debian:bookworm-slim

# Install runtime dependencies
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libssl3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r rustextractor && useradd -r -g rustextractor rustextractor

# Create necessary directories
RUN mkdir -p /discogs-data /logs && \
    chown -R rustextractor:rustextractor /discogs-data /logs

# Copy binary from builder
COPY --from=builder /app/target/release/rust_extractor /usr/local/bin/rustextractor

# Switch to non-root user
USER rustextractor

# Set environment variables
ENV RUST_LOG=rust_extractor=info,lapin=warn
ENV RUST_EXTRACTOR_CONFIG=/config.toml

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose health port
EXPOSE 8000

# Run the application
CMD ["rustextractor"]

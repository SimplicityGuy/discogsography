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

# Copy Cargo files from extractor subdirectory
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
FROM rust:1.89-slim

# Install runtime dependencies
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libssl3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r extractor && useradd -r -g extractor extractor

# Create necessary directories
RUN mkdir -p /discogs-data /logs && \
    chown -R extractor:extractor /discogs-data /logs

# Copy binary from builder
COPY --from=builder /app/target/release/extractor /usr/local/bin/extractor

# Switch to non-root user
USER extractor

# Set environment variables
ENV LOG_LEVEL=INFO
ENV RUST_EXTRACTOR_CONFIG=/config.toml

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose health port
EXPOSE 8000

# Run the application
CMD ["extractor"]

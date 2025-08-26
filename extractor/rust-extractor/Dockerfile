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

# Copy Cargo files and benchmark directory from extractor/rust-extractor subdirectory
COPY extractor/rust-extractor/Cargo.toml extractor/rust-extractor/Cargo.lock ./
COPY extractor/rust-extractor/benches ./benches

# Create dummy main to cache dependencies
RUN mkdir src && \
    echo "fn main() {}" > src/main.rs && \
    cargo build --release && \
    rm -rf src

# Copy actual source code from extractor/rust-extractor subdirectory
COPY extractor/rust-extractor/src ./src

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
RUN groupadd -r rust-extractor && useradd -r -g rust-extractor rust-extractor

# Create necessary directories
RUN mkdir -p /discogs-data /logs && \
    chown -R rust-extractor:rust-extractor /discogs-data /logs

# Copy binary from builder
COPY --from=builder /app/target/release/rust_extractor /usr/local/bin/rust-extractor

# Switch to non-root user
USER rust-extractor

# Set environment variables
ENV RUST_LOG=rust_extractor=info,lapin=warn
ENV RUST_EXTRACTOR_CONFIG=/config.toml

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose health port
EXPOSE 8000

# Run the application
CMD ["rust-extractor"]

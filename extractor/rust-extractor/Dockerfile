# Build stage
FROM rust:1.83-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy Cargo files from extractor/rust-extractor subdirectory
COPY extractor/rust-extractor/Cargo.toml extractor/rust-extractor/Cargo.lock ./

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
RUN apt-get update && apt-get install -y \
    ca-certificates \
    libssl3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r distiller && useradd -r -g distiller distiller

# Create necessary directories
RUN mkdir -p /discogs-data /logs && \
    chown -R distiller:distiller /discogs-data /logs

# Copy binary from builder
COPY --from=builder /app/target/release/distiller /usr/local/bin/distiller

# Switch to non-root user
USER distiller

# Set environment variables
ENV RUST_LOG=distiller=info,lapin=warn
ENV DISTILLER_CONFIG=/config.toml

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose health port
EXPOSE 8000

# Run the application
CMD ["distiller"]

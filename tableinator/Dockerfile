FROM python:3.13-slim

LABEL org.opencontainers.image.title="discogsography: table importer" \
      org.opencontainers.image.description="Listens to AMQP and imports data into PostgreSQL." \
      org.opencontainers.image.authors="robert@simplicityguy.com" \
      org.opencontainers.image.source="https://github.com/SimplicityGuy/discogsography/blob/main/tableinator/Dockerfile" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.created="$(date +'%Y-%m-%d')" \
      org.opencontainers.image.base.name="docker.io/library/python:3.13-slim"

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Create user
RUN addgroup --system discogsography && \
    adduser --system --group --home /home/discogsography discogsography && \
    mkdir -p /home/discogsography/.cache/uv && \
    chown -R discogsography:discogsography /home/discogsography

WORKDIR /app

# Copy project files
COPY --chown=discogsography:discogsography pyproject.toml config.py uv.lock ./
COPY --chown=discogsography:discogsography tableinator/*.py ./

# Install dependencies with uv
ENV UV_SYSTEM_PYTHON=1
ENV UV_CACHE_DIR=/home/discogsography/.cache/uv
RUN uv sync --frozen --no-dev --extra tableinator && \
    chown -R discogsography:discogsography .venv && \
    touch tableinator.log && chown discogsography:discogsography tableinator.log && \
    echo '#!/bin/bash' > /app/start.sh && \
    echo "sleep \${STARTUP_DELAY:-0}" >> /app/start.sh && \
    echo 'exec uv run python tableinator.py "$@"' >> /app/start.sh && \
    chmod +x /app/start.sh && \
    chown discogsography:discogsography /app/start.sh

USER discogsography:discogsography

# Environment variables
ENV HOME=/home/discogsography
ENV UV_NO_CACHE=1
ENV AMQP_CONNECTION=""
ENV POSTGRES_ADDRESS=""
ENV POSTGRES_USERNAME=""
ENV POSTGRES_PASSWORD=""
ENV POSTGRES_DATABASE=""

CMD ["/app/start.sh"]

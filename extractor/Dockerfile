FROM python:3.13-slim

LABEL org.opencontainers.image.title="discogsography: discogs extractor" \
      org.opencontainers.image.description="Downloads the latest discogs data, extracts all data, and pushes the data to AMQP." \
      org.opencontainers.image.authors="robert@simplicityguy.com" \
      org.opencontainers.image.source="https://github.com/SimplicityGuy/discogsography/blob/main/extractor/Dockerfile" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.created="$(date +'%Y-%m-%d')" \
      org.opencontainers.image.base.name="docker.io/library/python:3.13-slim"

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Create user and directories
RUN addgroup --system discogsography && \
    adduser --system --group discogsography && \
    mkdir /discogs-data && \
    chown discogsography:discogsography /discogs-data

WORKDIR /app

# Copy project files
COPY --chown=discogsography:discogsography pyproject.toml config.py uv.lock ./
COPY --chown=discogsography:discogsography extractor/*.py ./

# Install dependencies with uv
ENV UV_SYSTEM_PYTHON=1
RUN uv sync --frozen --no-dev --extra extractor

USER discogsography:discogsography

# Environment variables
ENV AMQP_CONNECTION=""
ENV DISCOGS_ROOT="/discogs-data"

CMD ["uv", "run", "python", "extractor.py"]

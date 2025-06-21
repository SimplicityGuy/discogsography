FROM python:3.13-slim

LABEL org.opencontainers.image.title="discogsography: graph importer" \
      org.opencontainers.image.description="Listens to AMQP and imports data into neo4j." \
      org.opencontainers.image.authors="robert@simplicityguy.com" \
      org.opencontainers.image.source="https://github.com/SimplicityGuy/discogsography/blob/main/graphinator/Dockerfile" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.created="$(date +'%Y-%m-%d')" \
      org.opencontainers.image.base.name="docker.io/library/python:3.13-slim"

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Create user
RUN addgroup --system discogsography && \
    adduser --system --group discogsography

WORKDIR /app

# Copy project files
COPY --chown=discogsography:discogsography pyproject.toml config.py uv.lock ./
COPY --chown=discogsography:discogsography graphinator/*.py ./

# Install dependencies with uv
ENV UV_SYSTEM_PYTHON=1
RUN uv sync --frozen --no-dev --extra graphinator

USER discogsography:discogsography

# Environment variables
ENV AMQP_CONNECTION=""
ENV NEO4J_ADDRESS=""
ENV NEO4J_USERNAME=""
ENV NEO4J_PASSWORD=""

CMD ["uv", "run", "python", "graphinator.py"]

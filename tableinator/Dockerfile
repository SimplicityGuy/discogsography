FROM python:3.13.0a1-alpine

LABEL org.opencontainers.image.title="discogsography: table importer" \
      org.opencontainers.image.description="Listens to AMQP and imports data into PostgreSQL." \
      org.opencontainers.image.authors="robert@simplicityguy.com" \
      org.opencontainers.image.source="https://github.com/SimplicityGuy/discogsography/blob/main/tableinator/Dockerfile" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.created="$(date +'%Y-%m-%d')" \
      org.opencontainers.image.base.name="docker.io/library/python:3-alpine"

RUN addgroup -S discogsography && \
    adduser -S discogsography -G discogsography

USER discogsography:discogsography

WORKDIR /app

COPY --chown=discogsography:discogsography . .

RUN pip install --upgrade --no-cache-dir --requirement requirements.txt

# format: amqp://user:pass@server:port
ENV AMQP_CONNECTION=""

# format: server
ENV POSTGRES_ADDRESS=""
ENV POSTGRES_USERNAME=""
ENV POSTGRES_PASSWORD=""
ENV POSTGRES_DATABASE=""


CMD ["python3", "tableinator.py"]

FROM python:3.13.0a4-alpine

LABEL org.opencontainers.image.title="discogsography: discogs exporter" \
      org.opencontainers.image.description="Downloads the latest discogs data, extracts all data, and pushes the data to AMQP." \
      org.opencontainers.image.authors="robert@simplicityguy.com" \
      org.opencontainers.image.source="https://github.com/SimplicityGuy/discogsography/blob/main/extractor/Dockerfile" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.created="$(date +'%Y-%m-%d')" \
      org.opencontainers.image.base.name="docker.io/library/python:3-alpine"

RUN addgroup -S discogsography && \
    adduser -S discogsography -G discogsography && \
    mkdir /discogs-data && \
    chown discogsography:discogsography /discogs-data

USER discogsography:discogsography

WORKDIR /app

COPY --chown=discogsography:discogsography . .

RUN pip install --upgrade --no-cache-dir --requirement requirements.txt

# format: amqp://user:pass@server:port
ENV AMQP_CONNECTION=""

CMD ["python3", "extractor.py"]

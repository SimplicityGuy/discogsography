FROM python:3-alpine

LABEL org.opencontainers.image.title="discogsography discogs exporter" \
      org.opencontainers.image.description="Image that will download the latest discogs data, extract all data, and push the data to AMQP." \
      org.opencontainers.image.authors="robert@simplicityguy.com"

RUN addgroup -S discogsography && \
    adduser -S discogsography -G discogsography && \
    mkdir /discogs-data && \
    chown discogsography:discogsography /discogs-data

USER discogsography:discogsography

WORKDIR /app

COPY --chown=discogsography:discogsography . .

RUN pip install --upgrade --no-cache-dir --requirement requirements.txt

ENV AMQP_CONNECTION="amqp://user:pass@server:port"
ENV AMQP_EXCHANGE="discogs-extractor"
ENV DISCOGS_ROOT="/discogs-data"

CMD ["python3", "extractor.py"]

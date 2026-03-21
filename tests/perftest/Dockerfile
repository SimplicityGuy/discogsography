# syntax=docker/dockerfile:1

# Discogsography API Performance Test Container
#
# Lightweight container that sequentially times all API query endpoints
# and produces a performance report. Not included in docker-compose —
# built and run manually.
#
# See README.md for usage instructions.

FROM python:3.13-slim

LABEL org.opencontainers.image.title="Discogsography Performance Test" \
      org.opencontainers.image.description="Sequential performance test runner for API query endpoints" \
      com.discogsography.service="perftest"

# hadolint ignore=DL3013
RUN pip install --no-cache-dir httpx pyyaml neo4j psycopg2-binary

# Create non-root user and directories
RUN groupadd -r perftest && \
    useradd -r -l -g perftest -m -s /bin/sh perftest && \
    mkdir -p /app /results && \
    chown -R perftest:perftest /app /results

WORKDIR /app

COPY --chown=perftest:perftest run_perftest.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

USER perftest

VOLUME ["/results", "/config"]

ENTRYPOINT ["/app/entrypoint.sh"]

#!/bin/sh
# Thin wrapper for the neo4j container.
# Reads /run/secrets/neo4j_password and sets NEO4J_AUTH before delegating
# to the official Neo4j entrypoint. This is needed because Neo4j does not
# natively support the Docker _FILE secret convention.
set -e

if [ -f /run/secrets/neo4j_password ]; then
    NEO4J_AUTH="neo4j/$(cat /run/secrets/neo4j_password)"
    export NEO4J_AUTH
fi

exec /startup/docker-entrypoint.sh "$@"

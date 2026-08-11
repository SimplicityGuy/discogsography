#!/bin/sh
# Thin wrapper for the redis container.
# Reads /run/secrets/redis_password and appends --requirepass to the
# redis-server arguments before delegating to the official Redis entrypoint.
# This is needed because Redis does not natively support the Docker _FILE
# secret convention. Without this, prod redis runs unauthenticated even
# though every other prod data store gets a _FILE-secret credential — see
# discogsography-yhjn.
set -e

if [ -f /run/secrets/redis_password ]; then
  REDIS_PASSWORD="$(cat /run/secrets/redis_password)"
  exec docker-entrypoint.sh "$@" --requirepass "$REDIS_PASSWORD"
else
  exec docker-entrypoint.sh "$@"
fi

#!/bin/sh
# Thin wrapper for the rabbitmq container.
# Reads /run/secrets/rabbitmq_username and /run/secrets/rabbitmq_password and
# sets RABBITMQ_DEFAULT_USER / RABBITMQ_DEFAULT_PASS before delegating to the
# official RabbitMQ entrypoint. This is needed because RabbitMQ does not
# natively support the Docker _FILE secret convention.
set -e

if [ -f /run/secrets/rabbitmq_username ]; then
  RABBITMQ_DEFAULT_USER="$(cat /run/secrets/rabbitmq_username)"
  export RABBITMQ_DEFAULT_USER
fi

if [ -f /run/secrets/rabbitmq_password ]; then
  RABBITMQ_DEFAULT_PASS="$(cat /run/secrets/rabbitmq_password)"
  export RABBITMQ_DEFAULT_PASS
fi

exec docker-entrypoint.sh "$@"

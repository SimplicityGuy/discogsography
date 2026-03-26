#!/usr/bin/env bash
# Reset a user's password in the Discogsography PostgreSQL database.
#
# Usage:
#   ./scripts/reset-password.sh <container_name> <postgres_password> <email> <new_password>
#
# Example:
#   ./scripts/reset-password.sh postgres discogsography user@example.com mynewpassword123

set -euo pipefail

if [ $# -lt 4 ]; then
  echo "Usage: $0 <container_name> <postgres_password> <email> <new_password>"
  echo "Example: $0 postgres discogsography user@example.com mynewpassword123"
  exit 1
fi

CONTAINER="$1"
PG_PASSWORD="$2"
EMAIL="$3"
NEW_PASSWORD="$4"

if [ ${#NEW_PASSWORD} -lt 8 ]; then
  echo "Error: Password must be at least 8 characters."
  exit 1
fi

# Generate the PBKDF2-SHA256 hash using Python (matches api/auth.py format)
if HASHED=$(docker exec "${CONTAINER}" python3 -c "
import hashlib, os
password = '''${NEW_PASSWORD}'''
salt = os.urandom(32)
key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100_000)
print(salt.hex() + ':' + key.hex())
" 2>/dev/null); then
  : # success
else
  # Alpine postgres image may not have python3; use the API container instead
  echo "python3 not available in '${CONTAINER}' container, trying API container..."
  HASHED=$(docker exec discogsography-api python3 -c "
import hashlib, os
password = '''${NEW_PASSWORD}'''
salt = os.urandom(32)
key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100_000)
print(salt.hex() + ':' + key.hex())
") || {
    echo "Error: Failed to generate password hash. Ensure either '${CONTAINER}' has python3 or the 'discogsography-api' container is running."
    exit 1
  }
fi

if [ -z "$HASHED" ]; then
  echo "Error: Failed to generate password hash (empty result)."
  exit 1
fi

echo "Updating password for: ${EMAIL}"

RESULT=$(docker exec "${CONTAINER}" env PGPASSWORD="${PG_PASSWORD}" psql -U discogsography -d discogsography -t -A -c \
  "UPDATE users SET hashed_password = '${HASHED}', password_changed_at = NOW(), updated_at = NOW() WHERE email = '${EMAIL}' RETURNING email;")

if [ -z "$RESULT" ]; then
  echo "Error: No user found with email '${EMAIL}'."
  echo ""
  echo "Existing users:"
  docker exec "${CONTAINER}" env PGPASSWORD="${PG_PASSWORD}" psql -U discogsography -d discogsography -t -A -c \
    "SELECT email FROM users;"
  exit 1
fi

echo "Password reset successfully for: ${RESULT}"

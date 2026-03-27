#!/usr/bin/env bash
# Bootstrap the secrets/ directory for production deployment.
# Run this once on the host before starting docker-compose.prod.yml.
#
# Usage: bash scripts/create-secrets.sh
#
# Behaviour:
#   - Skips files that already exist (idempotent — safe to re-run)
#   - Sets secrets/ to mode 700 and each file to 600

set -euo pipefail

SECRETS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/secrets"

mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

write_secret() {
  local name="$1"
  local value="$2"
  local path="$SECRETS_DIR/$name"
  if [ -f "$path" ]; then
    echo "[skip] $name already exists"
  else
    printf '%s' "$value" >"$path"
    chmod 600 "$path"
    echo "[ok]   $name created"
  fi
}

# JWT secret key (hex, 32 bytes = 64 hex chars)
write_secret "jwt_secret_key.txt" "$(openssl rand -hex 32)"

# HKDF master encryption key (derives OAuth + TOTP keys)
write_secret "encryption_master_key.txt" "$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode(), end="")')"

# Brevo API key — required for prod email delivery; get from https://app.brevo.com/settings/keys/api
# When empty, password reset links are logged instead of emailed.
write_secret "brevo_api_key.txt" "${BREVO_API_KEY:-}"

# PostgreSQL credentials
write_secret "postgres_username.txt" "discogsography"
write_secret "postgres_password.txt" "$(openssl rand -base64 24)"

# RabbitMQ credentials
write_secret "rabbitmq_username.txt" "discogsography"
write_secret "rabbitmq_password.txt" "$(openssl rand -base64 24)"

# Neo4j password
write_secret "neo4j_password.txt" "$(openssl rand -base64 24)"

echo ""
echo "✅ secrets/ is ready. Files are owner-read-only (chmod 600)."
echo "   Never commit secrets/ to version control."

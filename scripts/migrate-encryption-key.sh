#!/usr/bin/env bash
# Migrate OAuth tokens to a new ENCRYPTION_MASTER_KEY.
#
# Generates a new HKDF master key locally and re-encrypts existing OAuth
# tokens inside the API container.  PostgreSQL credentials are read from the
# container's own environment (POSTGRES_USERNAME / POSTGRES_PASSWORD, or their
# _FILE variants for Docker secrets).
#
# Usage:
#   ./scripts/migrate-encryption-key.sh <options> <api-container>
#
# The <api-container> must be the API service container (e.g. discogsography-api),
# which has Python, psycopg, and cryptography installed.  Do NOT use the postgres
# container — it lacks the required Python packages.
#
# Required:
#   --old-key <key|path>       Old OAuth encryption key — literal value or path to secret file
#   --new-key-file <path>      Write the generated master key to a file
#
# Examples:
#   # Old key as literal:
#   ./scripts/migrate-encryption-key.sh --old-key "$OLD_KEY" \
#       --new-key-file secrets/encryption_master_key.txt discogsography-api
#
#   # Old key from secret file:
#   ./scripts/migrate-encryption-key.sh \
#       --old-key secrets/oauth_encryption_key.txt \
#       --new-key-file secrets/encryption_master_key.txt discogsography-api

set -euo pipefail

# Resolve a value: if it's a path to an existing file, read from it; otherwise use as literal
resolve_value() {
  local val="$1"
  if [ -f "${val}" ]; then
    tr -d '[:space:]' < "${val}"
  else
    printf '%s' "${val}"
  fi
}

OLD_KEY=""
NEW_KEY_FILE=""

# Parse options
while [[ $# -gt 0 ]]; do
  case "$1" in
    --old-key)
      OLD_KEY="$2"
      shift 2
      ;;
    --new-key-file)
      NEW_KEY_FILE="$2"
      shift 2
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

if [ $# -lt 1 ] || [ -z "${OLD_KEY}" ] || [ -z "${NEW_KEY_FILE}" ]; then
  echo "Usage: $0 --old-key <key|path> --new-key-file <path> <api-container>"
  echo ""
  echo "Required:"
  echo "  --old-key <key|path>     Old OAuth encryption key — literal value or path to secret file"
  echo "  --new-key-file <path>    Write the generated master key to a file"
  echo ""
  echo "The <api-container> must be the API service container (e.g. discogsography-api)."
  echo "Do NOT use the postgres container — it lacks the required Python packages."
  echo "PostgreSQL credentials are read from the container's environment automatically."
  echo ""
  echo "Generates a new ENCRYPTION_MASTER_KEY and re-encrypts existing OAuth tokens"
  echo "from an old Fernet key to the new HKDF-derived key."
  exit 1
fi

CONTAINER="$1"

# Resolve old key (file paths become file contents, literals pass through)
OLD_KEY="$(resolve_value "${OLD_KEY}")"

# Generate new master key locally (32 random bytes, base64url-encoded)
NEW_MASTER_KEY=$(python3 -c "
import base64, os
key = os.urandom(32)
print(base64.urlsafe_b64encode(key).decode('ascii'), end='')
")

echo "Generated new ENCRYPTION_MASTER_KEY"
echo "Migrating OAuth tokens from old encryption key to HKDF-derived key..."
echo ""

MIGRATED=$(docker exec "${CONTAINER}" env \
    OLD_KEY="${OLD_KEY}" \
    NEW_MASTER_KEY="${NEW_MASTER_KEY}" \
    python3 -c "
import base64, os
from pathlib import Path
import psycopg
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

def get_secret(env_var):
    \"\"\"Read secret from _FILE path if set, else fall back to env var.\"\"\"
    file_path = os.environ.get(f'{env_var}_FILE')
    if file_path:
        return Path(file_path).read_text().strip()
    return os.environ[env_var]

old_key = os.environ['OLD_KEY']
master_key = os.environ['NEW_MASTER_KEY']

# Derive new OAuth key from master key
master_bytes = base64.urlsafe_b64decode(master_key)
hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b'oauth-tokens')
new_key = base64.urlsafe_b64encode(hkdf.derive(master_bytes)).decode('ascii')

f_old = Fernet(old_key.encode('ascii'))
f_new = Fernet(new_key.encode('ascii'))

# Validate keys work
test_data = b'migration-test'
assert f_new.decrypt(f_new.encrypt(test_data)) == test_data
print('Key derivation validated')

pg_user = get_secret('POSTGRES_USERNAME')
pg_pass = get_secret('POSTGRES_PASSWORD')
pg_host = os.environ.get('POSTGRES_HOST', 'postgres')
pg_db = os.environ.get('POSTGRES_DATABASE', 'discogsography')

conn = psycopg.connect(host=pg_host, dbname=pg_db, user=pg_user, password=pg_pass)
cur = conn.cursor()
cur.execute('SELECT id, access_token, access_secret FROM oauth_tokens')
rows = cur.fetchall()
count = 0
for row_id, access_token, access_secret in rows:
    try:
        plain_token = f_old.decrypt(access_token.encode('ascii')).decode('utf-8')
        plain_secret = f_old.decrypt(access_secret.encode('ascii')).decode('utf-8')
        new_token = f_new.encrypt(plain_token.encode('utf-8')).decode('ascii')
        new_secret = f_new.encrypt(plain_secret.encode('utf-8')).decode('ascii')
        cur.execute('UPDATE oauth_tokens SET access_token = %s, access_secret = %s WHERE id = %s', (new_token, new_secret, row_id))
        count += 1
    except Exception as e:
        print(f'Warning: Could not migrate token {row_id}: {e}')
conn.commit()
conn.close()
print(count)
") || {
  echo "Error: Migration failed."
  exit 1
}

echo ""
echo "Migrated ${MIGRATED} OAuth token(s)."

# Write new key to secret file
NEW_KEY_DIR="$(dirname "${NEW_KEY_FILE}")"
if [ ! -d "${NEW_KEY_DIR}" ]; then
  echo "Error: Directory for new key file does not exist: ${NEW_KEY_DIR}" >&2
  exit 1
fi
printf '%s' "${NEW_MASTER_KEY}" > "${NEW_KEY_FILE}"
chmod 600 "${NEW_KEY_FILE}"
echo "Wrote new master key to ${NEW_KEY_FILE} (mode 600)"

echo ""
echo "Next steps:"
echo ""
echo "  For .env (development):"
echo "    1. Set: ENCRYPTION_MASTER_KEY=<contents of ${NEW_KEY_FILE}>"
echo "    2. Remove: OAUTH_ENCRYPTION_KEY"
echo ""
echo "  For Docker secrets (production):"
echo "    1. New key written to: ${NEW_KEY_FILE}"
echo "    2. Remove old secret file if it exists"
echo ""
echo "Done."

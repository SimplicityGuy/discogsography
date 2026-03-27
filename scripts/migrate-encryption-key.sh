#!/usr/bin/env bash
# Migrate OAuth tokens from OAUTH_ENCRYPTION_KEY to ENCRYPTION_MASTER_KEY.
#
# Usage:
#   ./scripts/migrate-encryption-key.sh [options] <container> <pg_password> <old_oauth_key> <new_master_key>
#
# Options:
#   --old-key-file <path>      Read old OAuth encryption key from a secret file instead of CLI arg
#   --new-key-file <path>      Write the new master key to a secret file after migration
#
# Examples:
#   # Direct key arguments:
#   ./scripts/migrate-encryption-key.sh api-container pgpass old_key new_key
#
#   # Read old key from file, write new key to file:
#   ./scripts/migrate-encryption-key.sh --old-key-file secrets/oauth_encryption_key.txt \
#       --new-key-file secrets/encryption_master_key.txt api-container pgpass "" new_key
#
#   # Read old key from file, pass new key directly:
#   ./scripts/migrate-encryption-key.sh --old-key-file secrets/oauth_encryption_key.txt \
#       api-container pgpass "" new_key
#
# Run this ONCE when switching from OAUTH_ENCRYPTION_KEY to ENCRYPTION_MASTER_KEY.

set -euo pipefail

OLD_KEY_FILE=""
NEW_KEY_FILE=""

# Parse options
while [[ $# -gt 0 ]]; do
  case "$1" in
    --old-key-file)
      OLD_KEY_FILE="$2"
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

if [ $# -lt 4 ]; then
  echo "Usage: $0 [options] <container> <pg_password> <old_oauth_key> <new_master_key>"
  echo ""
  echo "Options:"
  echo "  --old-key-file <path>  Read old OAuth encryption key from a secret file"
  echo "  --new-key-file <path>  Write the new master key to a secret file after migration"
  echo ""
  echo "Migrates OAuth tokens from old Fernet key to HKDF-derived key."
  echo "Run this ONCE when switching from OAUTH_ENCRYPTION_KEY to ENCRYPTION_MASTER_KEY."
  exit 1
fi

CONTAINER="$1"
PG_PASSWORD="$2"
OLD_KEY="$3"
NEW_MASTER_KEY="$4"

# Read old key from file if specified
if [ -n "${OLD_KEY_FILE}" ]; then
  if [ ! -f "${OLD_KEY_FILE}" ]; then
    echo "Error: Old key file not found: ${OLD_KEY_FILE}" >&2
    exit 1
  fi
  OLD_KEY="$(tr -d '[:space:]' < "${OLD_KEY_FILE}")"
  echo "Read old encryption key from ${OLD_KEY_FILE}"
fi

# Validate we have both keys
if [ -z "${OLD_KEY}" ]; then
  echo "Error: Old OAuth encryption key is empty. Provide it as an argument or via --old-key-file." >&2
  exit 1
fi
if [ -z "${NEW_MASTER_KEY}" ]; then
  echo "Error: New master key is empty." >&2
  exit 1
fi

echo "Migrating OAuth tokens from old encryption key to HKDF-derived key..."
echo ""

# Validate keys and re-encrypt tokens
MIGRATED=$(docker exec "${CONTAINER}" env PGPASSWORD="${PG_PASSWORD}" python3 -c "
import base64
import psycopg2
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

old_key = '${OLD_KEY}'
master_key = '${NEW_MASTER_KEY}'

# Derive new OAuth key from master key
master_bytes = base64.urlsafe_b64decode(master_key)
hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b'oauth-tokens')
new_key = base64.urlsafe_b64encode(hkdf.derive(master_bytes)).decode('ascii')

f_old = Fernet(old_key.encode('ascii'))
f_new = Fernet(new_key.encode('ascii'))

# Validate keys work
test_data = b'migration-test'
assert f_new.decrypt(f_new.encrypt(test_data)) == test_data
print(f'Key derivation validated')

conn = psycopg2.connect(host='localhost', dbname='discogsography', user='discogsography', password='${PG_PASSWORD}')
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

# Write new key to secret file if specified
if [ -n "${NEW_KEY_FILE}" ]; then
  NEW_KEY_DIR="$(dirname "${NEW_KEY_FILE}")"
  if [ ! -d "${NEW_KEY_DIR}" ]; then
    echo "Error: Directory for new key file does not exist: ${NEW_KEY_DIR}" >&2
    exit 1
  fi
  printf '%s' "${NEW_MASTER_KEY}" > "${NEW_KEY_FILE}"
  chmod 600 "${NEW_KEY_FILE}"
  echo "Wrote new master key to ${NEW_KEY_FILE} (mode 600)"
fi

echo ""
echo "Next steps:"
echo ""
echo "  For .env (development):"
echo "    1. Remove: OAUTH_ENCRYPTION_KEY"
echo "    2. Add:    ENCRYPTION_MASTER_KEY=<new_master_key>"
echo ""
if [ -n "${NEW_KEY_FILE}" ]; then
  echo "  For Docker secrets (production):"
  echo "    1. New key already written to: ${NEW_KEY_FILE}"
  echo "    2. Remove old secret file if it exists (e.g., secrets/oauth_encryption_key.txt)"
else
  echo "  For Docker secrets (production):"
  echo "    1. Create: printf '%s' '<new_master_key>' > secrets/encryption_master_key.txt"
  echo "    2. Remove: secrets/oauth_encryption_key.txt"
fi
echo ""
echo "Done."

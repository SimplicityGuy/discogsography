#!/usr/bin/env bash
# Migrate OAuth tokens from OAUTH_ENCRYPTION_KEY to ENCRYPTION_MASTER_KEY.
#
# Usage:
#   ./scripts/migrate-encryption-key.sh <container> <pg_password> <old_oauth_key> <new_master_key>
#
# Run this ONCE when switching from OAUTH_ENCRYPTION_KEY to ENCRYPTION_MASTER_KEY.

set -euo pipefail

if [ $# -lt 4 ]; then
  echo "Usage: $0 <container> <pg_password> <old_oauth_key> <new_master_key>"
  echo ""
  echo "Migrates OAuth tokens from old Fernet key to HKDF-derived key."
  echo "Run this ONCE when switching from OAUTH_ENCRYPTION_KEY to ENCRYPTION_MASTER_KEY."
  exit 1
fi

CONTAINER="$1"
PG_PASSWORD="$2"
OLD_KEY="$3"
NEW_MASTER_KEY="$4"

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
echo ""
echo "Update your .env file:"
echo "  1. Remove: OAUTH_ENCRYPTION_KEY"
echo "  2. Add:    ENCRYPTION_MASTER_KEY=${NEW_MASTER_KEY}"
echo ""
echo "Done."

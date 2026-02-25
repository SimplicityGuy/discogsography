"""CLI tool for configuring Discogs app credentials in the database.

Run via docker exec on the API container:
    docker exec <container> discogs-setup --consumer-key KEY --consumer-secret SECRET
    docker exec <container> discogs-setup --show
"""

import argparse
import sys

import psycopg
from psycopg.rows import dict_row

from api.auth import decrypt_oauth_token, encrypt_oauth_token
from common.config import get_secret


def _build_conninfo() -> str:
    """Build a psycopg conninfo string from environment variables."""
    address = get_secret("POSTGRES_ADDRESS") or ""
    username = get_secret("POSTGRES_USERNAME") or ""
    password = get_secret("POSTGRES_PASSWORD") or ""
    database = get_secret("POSTGRES_DATABASE") or ""

    missing = []
    if not address:
        missing.append("POSTGRES_ADDRESS")
    if not username:
        missing.append("POSTGRES_USERNAME")
    if not password:
        missing.append("POSTGRES_PASSWORD")
    if not database:
        missing.append("POSTGRES_DATABASE")

    if missing:
        print(f"❌ Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    # POSTGRES_ADDRESS is in host:port format (matching api.py lifespan)
    if ":" in address:
        host, port = address.rsplit(":", 1)
    else:
        host, port = address, "5432"

    return f"host={host} port={port} user={username} password={password} dbname={database}"


def _mask(value: str) -> str:
    """Mask a credential value for display, preserving first/last two chars."""
    if not value:
        return "(not set)"
    if len(value) <= 4:
        return "****"
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def show_config(conninfo: str) -> None:
    """Print current Discogs credentials (masked)."""
    encryption_key = get_secret("OAUTH_ENCRYPTION_KEY")
    with psycopg.connect(conninfo) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT key, value FROM app_config WHERE key IN ('discogs_consumer_key', 'discogs_consumer_secret')")
        rows = {row["key"]: row["value"] for row in cur.fetchall()}

    key_val = decrypt_oauth_token(rows.get("discogs_consumer_key", ""), encryption_key)
    secret_val = decrypt_oauth_token(rows.get("discogs_consumer_secret", ""), encryption_key)
    print(f"discogs_consumer_key:    {_mask(key_val)}")
    print(f"discogs_consumer_secret: {_mask(secret_val)}")


def set_config(conninfo: str, consumer_key: str, consumer_secret: str) -> None:
    """Upsert Discogs credentials into the app_config table."""
    encryption_key = get_secret("OAUTH_ENCRYPTION_KEY")
    if encryption_key:
        consumer_key = encrypt_oauth_token(consumer_key, encryption_key)
        consumer_secret = encrypt_oauth_token(consumer_secret, encryption_key)

    upsert_sql = """
        INSERT INTO app_config (key, value, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (key) DO UPDATE SET
            value = EXCLUDED.value,
            updated_at = NOW()
    """
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        cur.execute(upsert_sql, ("discogs_consumer_key", consumer_key))
        cur.execute(upsert_sql, ("discogs_consumer_secret", consumer_secret))

    print("✅ Discogs credentials updated successfully.")


def main() -> None:
    """Entry point for the discogs-setup CLI tool."""
    parser = argparse.ArgumentParser(
        prog="discogs-setup",
        description="Configure Discogs app credentials in the database.",
        epilog=("Reads DB connection from environment variables: POSTGRES_ADDRESS, POSTGRES_USERNAME, POSTGRES_PASSWORD, POSTGRES_DATABASE"),
    )
    parser.add_argument("--consumer-key", metavar="KEY", help="Discogs consumer key")
    parser.add_argument("--consumer-secret", metavar="SECRET", help="Discogs consumer secret")
    parser.add_argument(
        "--show",
        action="store_true",
        help="Print current credential values (masked)",
    )

    args = parser.parse_args()

    if not args.show and not args.consumer_key:
        parser.error("one of --show or --consumer-key/--consumer-secret is required")

    if args.show and (args.consumer_key or args.consumer_secret):
        parser.error("--show cannot be combined with --consumer-key/--consumer-secret")

    if args.consumer_key and not args.consumer_secret:
        parser.error("--consumer-secret is required when using --consumer-key")

    if args.consumer_secret and not args.consumer_key:
        parser.error("--consumer-key is required when using --consumer-secret")

    conninfo = _build_conninfo()

    if args.show:
        show_config(conninfo)
    else:
        set_config(conninfo, args.consumer_key, args.consumer_secret)


if __name__ == "__main__":
    main()

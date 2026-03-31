"""CLI tool for managing admin accounts.

Usage:
    admin-setup --email admin@example.com --password mysecretpw
    admin-setup --list
"""

from __future__ import annotations

import argparse
from os import getenv
import sys

import psycopg

from api.auth import _hash_password
from common.config import get_secret


def _build_conninfo() -> str:
    """Build PostgreSQL connection string from environment variables."""
    host = getenv("POSTGRES_HOST", "localhost")
    port = getenv("POSTGRES_PORT", "5432")
    user = get_secret("POSTGRES_USERNAME") or "postgres"
    password = get_secret("POSTGRES_PASSWORD") or "postgres"
    database = getenv("POSTGRES_DATABASE", "discogsography")
    return f"host={host} port={port} user={user} password={password} dbname={database}"


def add_admin(conninfo: str, email: str, password: str) -> None:
    """Insert or promote an admin account in the users table."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    hashed = _hash_password(password)

    upsert_sql = """
        INSERT INTO users (email, hashed_password, is_admin, is_active)
        VALUES (%s, %s, TRUE, TRUE)
        ON CONFLICT (email) DO UPDATE SET
            hashed_password = EXCLUDED.hashed_password,
            is_admin = TRUE,
            updated_at = NOW()
    """
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        cur.execute(upsert_sql, (email.strip().lower(), hashed))
    print(f"✅ Admin account '{email}' created/updated successfully.")


def list_admins(conninfo: str) -> None:
    """List all admin accounts (email + active status)."""
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        cur.execute("SELECT email, is_active, created_at FROM users WHERE is_admin = TRUE ORDER BY created_at")
        rows = cur.fetchall()

    if not rows:
        print("No admin accounts found.")
        return

    print(f"{'Email':<40} {'Active':<8} {'Created'}")
    print("-" * 70)
    for email, is_active, created_at in rows:
        status = "Yes" if is_active else "No"
        print(f"{email:<40} {status:<8} {created_at}")


def main() -> None:
    """Entry point for the admin-setup CLI tool."""
    parser = argparse.ArgumentParser(
        prog="admin-setup",
        description="Manage admin accounts for the dashboard.",
    )
    parser.add_argument("--email", metavar="EMAIL", help="Admin email address")
    parser.add_argument("--password", metavar="PW", help="Admin password (min 8 chars)")
    parser.add_argument("--list", action="store_true", help="List existing admin accounts")

    args = parser.parse_args()

    if not args.list and not (args.email and args.password):
        parser.print_help()
        sys.exit(1)

    if args.password and len(args.password) < 8:
        print("❌ Password must be at least 8 characters.")
        sys.exit(1)

    conninfo = _build_conninfo()

    if args.list:
        list_admins(conninfo)
    else:
        add_admin(conninfo, args.email, args.password)


if __name__ == "__main__":
    main()

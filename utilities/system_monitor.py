#!/usr/bin/env python3

import json
import os
import subprocess  # nosec B404
from typing import Any

import requests

from common.config import get_secret


def get_docker_stats() -> list[dict[str, Any]]:
    """Get Docker container statistics."""
    try:
        result = subprocess.run(  # nosec B603 B607
            ["docker", "compose", "ps", "--format", "json"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        output = result.stdout.strip()
        containers = json.loads(output) if output.startswith("[") else [json.loads(line) for line in output.split("\n") if line]
        return containers
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []


def get_queue_stats(
    base_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
) -> list[dict[str, Any]] | None:
    """Fetch queue statistics from RabbitMQ Management API."""
    base_url = base_url or os.environ.get("RABBITMQ_URL", "http://localhost:15672")
    username = username or os.environ.get("RABBITMQ_USERNAME", "discogsography")
    password = password or get_secret("RABBITMQ_PASSWORD", "")
    try:
        response = requests.get(f"{base_url}/api/queues", auth=(username, password), timeout=10)
        response.raise_for_status()
        data: list[dict[str, Any]] = response.json()
        return data
    except requests.RequestException:
        return None


def get_service_logs(service: str, lines: int = 20) -> str:
    """Get recent logs from a service."""
    try:
        result = subprocess.run(  # noqa: S603  # nosec B603 B607
            ["docker", "compose", "logs", service, f"--tail={lines}"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return result.stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def check_neo4j_status() -> str:
    """Check Neo4j database status."""
    neo4j_username = os.environ.get("NEO4J_USERNAME", "neo4j")
    neo4j_password = get_secret("NEO4J_PASSWORD", "")
    env = os.environ.copy()
    env["NEO4J_USERNAME"] = neo4j_username
    env["NEO4J_PASSWORD"] = neo4j_password
    try:
        result = subprocess.run(  # nosec B603 B607
            [  # noqa: S607
                "docker",
                "exec",
                "-e",
                "NEO4J_USERNAME",
                "-e",
                "NEO4J_PASSWORD",
                "discogsography-neo4j",
                "cypher-shell",
                "MATCH (n) RETURN labels(n)[0] as label, count(n) as count ORDER BY count DESC LIMIT 10",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
            env=env,
        )
        return result.stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        stderr = getattr(e, "stderr", None)
        return f"Error: {stderr}" if isinstance(stderr, str) and stderr else f"Error: {e}"


def check_postgres_status() -> str:
    """Check PostgreSQL database status."""
    try:
        result = subprocess.run(  # noqa: S603  # nosec B603 B607
            [  # noqa: S607
                "docker",
                "exec",
                "discogsography-postgres",
                "psql",
                "-U",
                os.environ.get("POSTGRES_USERNAME", "discogsography"),
                "-d",
                os.environ.get("POSTGRES_DATABASE", "discogsography"),
                "-t",
                "-c",
                "SELECT relname, pg_size_pretty(pg_relation_size(schemaname||'.'||relname)) as size, n_live_tup as rows FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 10;",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return result.stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        stderr = getattr(e, "stderr", None)
        return f"Error: {stderr}" if isinstance(stderr, str) and stderr else f"Error: {e}"


def monitor_system() -> None:
    """Monitor the entire system."""
    print("System Monitor for Discogsography")
    print("=" * 80)

    # Check Docker containers
    print("\n📦 Docker Container Status:")
    print("-" * 40)
    containers = get_docker_stats()
    if containers:
        for container in containers:
            health = container.get("Health", "N/A")
            status = container.get("State", "unknown")
            name = container.get("Name", "unknown")
            print(f"  {name:<30} Status: {status:<15} Health: {health}")
    else:
        print("  Unable to fetch container status")

    # Check RabbitMQ queues
    print("\n📬 RabbitMQ Queue Status:")
    print("-" * 40)
    queues = get_queue_stats()
    if queues:
        total_messages = 0
        for queue in queues:
            if "discogsography" in queue["name"] or "musicbrainz" in queue["name"]:
                name = queue["name"].replace("discogsography-discogs-", "").replace("discogsography-musicbrainz-", "mb-")
                ready = queue.get("messages_ready", 0)
                unacked = queue.get("messages_unacknowledged", 0)
                total = queue.get("messages", 0)
                total_messages += total
                print(f"  {name:<30} Ready: {ready:<8} Unacked: {unacked:<8} Total: {total}")
        print(f"\n  Total messages: {total_messages}")
    else:
        print("  Unable to fetch queue data")

    # Check Neo4j status
    print("\n🔷 Neo4j Database Status:")
    print("-" * 40)
    neo4j_status = check_neo4j_status()
    if not neo4j_status.startswith("Error:"):
        print(neo4j_status)
    else:
        print("  Unable to connect to Neo4j")

    # Check PostgreSQL status
    print("\n🐘 PostgreSQL Database Status:")
    print("-" * 40)
    postgres_status = check_postgres_status()
    if not postgres_status.startswith("Error:"):
        print(postgres_status)
    else:
        print("  Unable to connect to PostgreSQL")

    # Check for recent errors in services
    print("\n⚠️  Recent Errors (last 50 lines):")
    print("-" * 40)
    services = ["extractor-discogs", "extractor-musicbrainz", "graphinator", "tableinator", "brainzgraphinator", "brainztableinator"]
    error_found = False
    for service in services:
        logs = get_service_logs(service, 50)
        errors = [line for line in logs.split("\n") if "ERROR" in line or "Failed" in line]
        if errors:
            error_found = True
            print(f"\n  {service}:")
            for error in errors[-5:]:  # Show last 5 errors
                print(f"    {error[:100]}...")

    if not error_found:
        print("  No recent errors found in service logs")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    monitor_system()

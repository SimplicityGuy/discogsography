import asyncio
import logging
from pathlib import Path

import psycopg
from common import TableinatorConfig, setup_logging

# Config will be initialized in main
config: TableinatorConfig | None = None

# Connection parameters will be initialized in main
connection_params: dict[str, any] = {}


def get_db_connection() -> any:
    """Get a database connection."""
    return psycopg.connect(**connection_params)


def analyze_data() -> None:
    """Analyze the data in the database."""
    try:
        with get_db_connection() as conn, conn.cursor() as cur:
            # Get the most popular artists
            cur.execute(
                """
                SELECT
                    data->>'name' AS artist_name,
                    COUNT(*) AS release_count
                FROM
                    artists
                JOIN
                    releases ON data->'artists'->0->>'id' = artists.data->>'id'
                GROUP BY
                    artist_name
                ORDER BY
                    release_count DESC
                LIMIT 10;
                """
            )
            popular_artists = cur.fetchall()
            print("Most popular artists:")
            for artist, count in popular_artists:
                print(f"- {artist}: {count} releases")

            # Get the most popular labels
            cur.execute(
                """
                SELECT
                    data->>'name' AS label_name,
                    COUNT(*) AS release_count
                FROM
                    labels
                JOIN
                    releases ON data->'labels'->0->>'id' = labels.data->>'id'
                GROUP BY
                    label_name
                ORDER BY
                    release_count DESC
                LIMIT 10;
                """
            )
            popular_labels = cur.fetchall()
            print("\nMost popular labels:")
            for label, count in popular_labels:
                print(f"- {label}: {count} releases")

    except Exception as e:
        print(f"Error analyzing data: {e}")


async def main() -> None:
    """Main function."""
    global config, connection_params

    setup_logging("analyzer", log_file=Path("/logs/analyzer.log"))
    logging.info("🚀 Starting analyzer service")

    # Initialize configuration
    try:
        config = TableinatorConfig.from_env()
    except ValueError as e:
        logging.error(f"❌ Configuration error: {e}")
        return

    # Parse host and port from address
    if ":" in config.postgres_address:
        host, port_str = config.postgres_address.split(":", 1)
        port = int(port_str)
    else:
        host = config.postgres_address
        port = 5432

    # Set connection parameters
    connection_params = {
        "host": str(host),
        "port": int(port),
        "dbname": str(config.postgres_database),
        "user": str(config.postgres_username),
        "password": str(config.postgres_password),
    }

    analyze_data()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("⚠️ Application interrupted")
    except Exception as e:
        logging.error(f"❌ Application error: {e}")
    finally:
        logging.info("✅ Analyzer service shutdown complete")

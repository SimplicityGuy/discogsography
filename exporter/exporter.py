import asyncio
import csv
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


def export_data() -> None:
    """Export data from the database to CSV files."""
    try:
        with get_db_connection() as conn, conn.cursor() as cur:
            # Export artists
            with open("artists.csv", "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["id", "name", "realname", "profile"])
                cur.execute("SELECT data->>'id', data->>'name', data->>'realname', data->>'profile' FROM artists")
                for row in cur:
                    writer.writerow(row)
            print("Exported artists to artists.csv")

            # Export labels
            with open("labels.csv", "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["id", "name", "contactinfo", "profile"])
                cur.execute("SELECT data->>'id', data->>'name', data->>'contactinfo', data->>'profile' FROM labels")
                for row in cur:
                    writer.writerow(row)
            print("Exported labels to labels.csv")

            # Export releases
            with open("releases.csv", "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["id", "title", "year", "country"])
                cur.execute("SELECT data->>'id', data->>'title', data->>'year', data->>'country' FROM releases")
                for row in cur:
                    writer.writerow(row)
            print("Exported releases to releases.csv")

    except Exception as e:
        print(f"Error exporting data: {e}")


async def main() -> None:
    """Main function."""
    global config, connection_params

    setup_logging("exporter", log_file=Path("/logs/exporter.log"))
    logging.info("🚀 Starting exporter service")

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

    export_data()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("⚠️ Application interrupted")
    except Exception as e:
        logging.error(f"❌ Application error: {e}")
    finally:
        logging.info("✅ Exporter service shutdown complete")

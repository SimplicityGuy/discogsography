import asyncio
import logging
from pathlib import Path

import psycopg
from common import TableinatorConfig, setup_logging
from flask import Flask, jsonify

app = Flask(__name__)

# Config will be initialized in main
config: TableinatorConfig | None = None

# Connection parameters will be initialized in main
connection_params: dict[str, any] = {}


def get_db_connection() -> any:
    """Get a database connection."""
    return psycopg.connect(**connection_params)


@app.route("/api/artists_by_year", methods=["GET"])
def artists_by_year():
    """Get the number of artists by year."""
    try:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    EXTRACT(YEAR FROM TO_DATE(data->>'timestamp', 'YYYY-MM-DD')) AS year,
                    COUNT(*) AS artist_count
                FROM
                    artists
                GROUP BY
                    year
                ORDER BY
                    year;
                """
            )
            data = cur.fetchall()
            return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


async def main() -> None:
    """Main function."""
    global config, connection_params

    setup_logging("visualizer", log_file=Path("/logs/visualizer.log"))
    logging.info("🚀 Starting visualizer service")

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

    app.run(host="0.0.0.0", port=8004)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("⚠️ Application interrupted")
    except Exception as e:
        logging.error(f"❌ Application error: {e}")
    finally:
        logging.info("✅ Visualizer service shutdown complete")

#!/usr/bin/env python3
"""Test script to verify file completion message handling."""

import logging
from datetime import datetime

import pika
from orjson import OPT_INDENT_2, OPT_SORT_KEYS, dumps


# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def send_test_completion_message(data_type: str) -> None:
    """Send a test file completion message to RabbitMQ."""
    # Connect to RabbitMQ
    connection = pika.BlockingConnection(pika.ConnectionParameters(host="localhost"))
    channel = connection.channel()

    # Declare exchange
    channel.exchange_declare(exchange="discogs", exchange_type="topic", durable=True, auto_delete=False)

    # Create completion message
    completion_message = {
        "type": "file_complete",
        "data_type": data_type,
        "timestamp": datetime.now().isoformat(),
        "total_processed": 12345,
        "file": f"test_{data_type}.xml",
    }

    # Publish message
    channel.basic_publish(
        exchange="discogs",
        routing_key=data_type,
        body=dumps(completion_message, option=OPT_SORT_KEYS | OPT_INDENT_2),
        properties=pika.BasicProperties(
            delivery_mode=2,  # Make message persistent
        ),
    )

    logger.info(f"✅ Sent test completion message for {data_type}")

    # Close connection
    connection.close()


def main() -> None:
    """Send test completion messages for all data types."""
    logger.info("🚀 Starting file completion test...")

    data_types = ["artists", "labels", "masters", "releases"]

    for data_type in data_types:
        try:
            send_test_completion_message(data_type)
        except Exception as e:
            logger.error(f"❌ Failed to send completion message for {data_type}: {e}")

    logger.info("✅ Test completed! Check tableinator and graphinator logs for 🎉 messages.")


if __name__ == "__main__":
    main()

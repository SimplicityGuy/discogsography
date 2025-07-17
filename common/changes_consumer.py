"""Base class for services that consume change notifications."""

import logging
from abc import ABC, abstractmethod
from typing import Any

import aio_pika
from orjson import loads

from common import AMQP_EXCHANGE


logger = logging.getLogger(__name__)


class ChangesConsumer(ABC):
    """Base class for consuming change notifications from the incremental extractor."""

    def __init__(self, amqp_connection_url: str, service_name: str):
        """Initialize the changes consumer."""
        self.amqp_connection_url = amqp_connection_url
        self.service_name = service_name
        self.connection: aio_pika.abc.AbstractConnection | None = None
        self.channel: aio_pika.abc.AbstractChannel | None = None
        self.queue: aio_pika.abc.AbstractQueue | None = None

    async def connect(self) -> None:
        """Connect to AMQP and set up the changes queue."""
        logger.info(f"🐰 Connecting to RabbitMQ for {self.service_name} changes consumer...")

        self.connection = await aio_pika.connect_robust(self.amqp_connection_url)
        self.channel = await self.connection.channel()

        # Set prefetch count to process one message at a time
        await self.channel.set_qos(prefetch_count=1)

        # Declare the exchange (idempotent operation)
        exchange = await self.channel.declare_exchange(
            AMQP_EXCHANGE,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )

        # Create a unique queue for this service's change notifications
        queue_name = f"discogsography-{self.service_name}-changes"
        self.queue = await self.channel.declare_queue(queue_name, durable=True)

        # Bind to all change notifications
        await self.queue.bind(exchange, routing_key="*.changes")

        logger.info(f"✅ Connected to changes queue: {queue_name}")

    async def start_consuming(self) -> None:
        """Start consuming change notifications."""
        if not self.queue:
            raise RuntimeError("Not connected. Call connect() first.")

        logger.info(f"🔄 Starting to consume changes for {self.service_name}...")

        async with self.queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    try:
                        # Parse the change notification
                        change_data = loads(message.body)

                        logger.info(
                            f"📥 Received change notification: {change_data['data_type']} "
                            f"ID={change_data['record_id']} ({change_data['change_type']})"
                        )

                        # Process the change
                        await self.process_change(change_data)

                    except Exception as e:
                        logger.error(f"❌ Error processing change notification: {e}")
                        # Re-raise to trigger message redelivery
                        raise

    @abstractmethod
    async def process_change(self, change_data: dict[str, Any]) -> None:
        """Process a single change notification.

        Args:
            change_data: Dictionary containing:
                - data_type: Type of data (artists, labels, masters, releases)
                - record_id: ID of the changed record
                - change_type: Type of change (created, updated, deleted)
                - processing_run_id: UUID of the processing run
                - timestamp: ISO timestamp of the change
        """
        pass

    async def close(self) -> None:
        """Close the AMQP connection."""
        if self.connection:
            await self.connection.close()
            logger.info(f"✅ Closed changes consumer connection for {self.service_name}")


class LoggingChangesConsumer(ChangesConsumer):
    """Simple implementation that just logs changes."""

    async def process_change(self, change_data: dict[str, Any]) -> None:
        """Log the change notification."""
        logger.info(
            f"📝 Change: {change_data['data_type']} ID={change_data['record_id']} "
            f"was {change_data['change_type']} at {change_data['timestamp']}"
        )

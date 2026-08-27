"""Backoff for per-message consumers that requeue on a database outage.

Per-message consumers handle "the database is down" by
``nack(requeue=True)``. Their main queues are quorum queues declared with
``x-delivery-limit: 20``, so every redelivery spends part of a FIXED budget with
no time dimension: with no pause between cycles a message is redelivered every
few seconds and reaches 20 deliveries in ~3 minutes, at which point RabbitMQ
dead-letters a perfectly valid record. A sustained outage therefore drains the
head of the queue into the DLQ — silent data loss from a routine maintenance
window (discogsography-rb05).

The batch-mode consumers dodged this by moving retry state out of the broker and
into process memory (deque + backoff). The per-message consumers keep retry state
in the broker, so the only lever is to slow the treadmill down: hold the delivery
for a growing delay before nacking, so 20 deliveries span an outage-sized window
instead of a coffee break.
"""

import asyncio

import structlog


logger = structlog.get_logger(__name__)

# Delay applied before the FIRST requeue of an outage, in seconds.
DEFAULT_INITIAL_DELAY = 2.0
# Ceiling for the per-redelivery delay, in seconds. With x-delivery-limit=20 a
# capped delay of 60s buys ~20 minutes of outage tolerance per message.
DEFAULT_MAX_DELAY = 60.0


class OutageBackoff:
    """Growing delay applied before requeueing during a backend outage.

    One instance per consumer process. It is deliberately NOT per-message: the
    thing being throttled is the outage, and every in-flight delivery is hitting
    the same dead backend.
    """

    def __init__(
        self,
        name: str,
        initial_delay: float = DEFAULT_INITIAL_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        multiplier: float = 2.0,
    ) -> None:
        self.name = name
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self._consecutive_failures = 0

    @property
    def consecutive_failures(self) -> int:
        """Number of consecutive transient failures since the last success."""
        return self._consecutive_failures

    def reset(self) -> None:
        """Record a success — the backend is answering again."""
        self._consecutive_failures = 0

    def next_delay(self) -> float:
        """Count one transient failure and return the delay to apply."""
        self._consecutive_failures += 1
        return min(
            self.initial_delay * (self.multiplier ** (self._consecutive_failures - 1)),
            self.max_delay,
        )

    async def wait(self) -> float:
        """Count a transient failure and sleep for the resulting delay.

        Call this immediately BEFORE ``message.nack(requeue=True)`` so the
        redelivery that follows costs wall-clock time rather than just another
        slot of the quorum queue's delivery budget.
        """
        delay = self.next_delay()
        logger.warning(
            "⏳ Backing off before requeue — backend unavailable",
            consumer=self.name,
            delay_seconds=round(delay, 1),
            consecutive_failures=self._consecutive_failures,
        )
        await asyncio.sleep(delay)
        return delay

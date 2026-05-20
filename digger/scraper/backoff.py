"""Per-release exponential backoff on scrape failure.

next_retry_delay() — pure-Python helper used in unit tests.
record_failure()   — SQL updater; accepts a psycopg AsyncCursor.

Real transactional behaviour is deferred to the M1 e2e smoke (Task 28).
"""

from __future__ import annotations

from datetime import timedelta


MAX_BACKOFF = timedelta(hours=24)


def next_retry_delay(consecutive_failures: int) -> timedelta:
    """Return the retry delay for the given consecutive-failure count.

    Doubles each failure: 1 h → 2 h → 4 h → … capped at MAX_BACKOFF (24 h).
    ``consecutive_failures`` is the count *before* recording the current failure.
    The exponent is clamped to 24 before computing so the intermediate ``2 ** n``
    stays bounded (it is well past the 24 h cap anyway), avoiding pointlessly huge
    intermediate values for runaway failure counts.
    """
    exponent = min(24, max(0, consecutive_failures))
    delay = timedelta(hours=2**exponent)
    return min(delay, MAX_BACKOFF)


async def record_failure(cur: object, release_id: int) -> None:
    """Increment consecutive_failures and set next_retry_at for *release_id*.

    *cur* must be an open psycopg ``AsyncCursor`` (caller owns the
    connection/transaction).
    """
    await cur.execute(  # type: ignore[attr-defined]
        """
        UPDATE digger.release_scrape_state
           SET consecutive_failures = consecutive_failures + 1,
               next_retry_at        = now() + LEAST(
                   interval '24 hours',
                   (interval '1 hour') * power(2, consecutive_failures)
               )
         WHERE release_id = %s
        """,
        (release_id,),
    )

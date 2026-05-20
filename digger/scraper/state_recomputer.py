"""Adaptive throttle for next_scrape_due_at.

compute_next_scrape_due() — pure-Python logic used in unit tests.
refresh_all_due_times()   — bulk SQL recompute; accepts a psycopg AsyncCursor.

Real transactional behaviour is deferred to the M1 e2e smoke (Task 28).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta


BASE_INTERVALS: dict[str, timedelta] = {
    "must": timedelta(days=7),
    "nice": timedelta(days=14),
    "eventually": timedelta(days=28),
}


def compute_next_scrape_due(
    last_scraped_at: datetime,
    tier: str,
    listings_delta_7d: int,
) -> datetime:
    """Compute next scrape timestamp with adaptive churn factor.

    The churn multiplier is clamped to [0.5, 1.5]:
    - high activity  → shorter interval (multiplier < 1)
    - no activity    → base interval   (multiplier = 1)
    - never above    → 1.5× base       (multiplier capped at 1.5)
    """
    base = BASE_INTERVALS[tier]
    raw = 1.0 - math.log10(1 + max(0, listings_delta_7d)) * 0.2
    churn = min(1.5, max(0.5, raw))
    return last_scraped_at + base * churn


async def refresh_all_due_times(cur: object) -> int:
    """Recompute next_scrape_due_at for every row in a single SQL pass.

    *cur* must be an open psycopg ``AsyncCursor`` (caller owns the
    connection/transaction).  Returns the number of rows updated.
    """
    # Only re-throttle rows that have actually been scraped. Never-scraped rows
    # (last_scraped_at IS NULL) keep their default next_scrape_due_at = now() so
    # brand-new releases get picked up promptly instead of being pushed 7-28 days out.
    await cur.execute(  # type: ignore[attr-defined]
        """
        UPDATE digger.release_scrape_state
           SET next_scrape_due_at =
               last_scraped_at
               + (CASE priority_tier
                    WHEN 'must'       THEN interval '7 days'
                    WHEN 'nice'       THEN interval '14 days'
                    ELSE                   interval '28 days'
                  END)
               * GREATEST(0.5, LEAST(1.5,
                   1.0 - log(1 + GREATEST(0, listings_delta_7d)) * 0.2
               ))
         WHERE last_scraped_at IS NOT NULL
        """
    )
    return int(cur.rowcount)  # type: ignore[attr-defined]

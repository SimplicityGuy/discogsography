"""Pop the next due release from the scrape queue.

SELECT ... FOR UPDATE SKIP LOCKED — multi-worker safe.

Real transactional behaviour (SKIP LOCKED ordering, upsert + soft-delete
correctness against a live DB) is deferred to the M1 e2e smoke (Task 28).
"""

from __future__ import annotations


POP_SQL = """
SELECT release_id
  FROM digger.release_scrape_state
 WHERE next_scrape_due_at <= now()
   AND (next_retry_at IS NULL OR next_retry_at <= now())
 ORDER BY
   CASE priority_tier WHEN 'must' THEN 1 WHEN 'nice' THEN 2 ELSE 3 END,
   next_scrape_due_at ASC
 LIMIT 1
 FOR UPDATE SKIP LOCKED
"""


async def pop_next_due(cur: object) -> int | None:
    """Return next due release_id, or None.

    *cur* must be an open psycopg ``AsyncCursor`` running inside an open
    transaction (caller's responsibility).  The matched row stays locked for
    the duration of that transaction so concurrent workers skip it.
    """
    await cur.execute(POP_SQL)  # type: ignore[attr-defined]
    row = await cur.fetchone()  # type: ignore[attr-defined]
    return None if row is None else int(row[0])

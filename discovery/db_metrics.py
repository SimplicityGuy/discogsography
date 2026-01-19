"""Database query performance metrics tracking."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import time
from typing import Any

import structlog

from discovery.metrics import db_query_count, db_query_duration


logger = structlog.get_logger(__name__)


@asynccontextmanager
async def track_query_performance(
    db_type: str,
    operation: str,
) -> AsyncGenerator[None]:
    """Track database query performance metrics.

    Args:
        db_type: Database type (neo4j, postgres, etc.)
        operation: Operation name (search, expand, pathfinding, etc.)

    Yields:
        None

    Example:
        ```python
        async with track_query_performance("neo4j", "search"):
            result = await session.run(query)
        ```
    """
    start_time = time.time()
    status = "success"

    try:
        yield
    except Exception as e:
        status = "error"
        logger.error(
            "❌ Database query failed",
            db_type=db_type,
            operation=operation,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise
    finally:
        # Record query duration
        duration = time.time() - start_time
        db_query_duration.labels(db_type=db_type, operation=operation).observe(duration)

        # Record query count
        db_query_count.labels(db_type=db_type, operation=operation, status=status).inc()

        logger.debug(
            "📊 Database query completed",
            db_type=db_type,
            operation=operation,
            duration=f"{duration:.4f}s",
            status=status,
        )


async def track_neo4j_query(operation: str, query_func: Any) -> Any:
    """Track Neo4j query performance.

    Args:
        operation: Operation name
        query_func: Async function that executes the query

    Returns:
        Query result
    """
    async with track_query_performance("neo4j", operation):
        return await query_func()


async def track_postgres_query(operation: str, query_func: Any) -> Any:
    """Track PostgreSQL query performance.

    Args:
        operation: Operation name
        query_func: Async function that executes the query

    Returns:
        Query result
    """
    async with track_query_performance("postgres", operation):
        return await query_func()

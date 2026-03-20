"""Consolidated Neo4j Cypher query execution helpers.

Replaces duplicated ``_run_query`` / ``_run_single`` / ``_run_count`` across
multiple query modules with a single set of helpers that add:

- DEBUG-level query logging via :func:`common.query_debug.log_cypher_query`
- Optional ``PROFILE`` prefix when database profiling is enabled
- Best-effort ``EXPLAIN`` after query failure (when profiling is enabled)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from common.query_debug import (
    is_db_profiling,
    log_cypher_query,
    log_explain_result,
    log_profile_result,
)


if TYPE_CHECKING:
    from common import AsyncResilientNeo4jDriver

_logger = logging.getLogger(__name__)


async def _try_explain_on_error(
    driver: AsyncResilientNeo4jDriver,
    cypher: str,
    params: dict[str, Any] | None,
    error: BaseException,
    database: str | None = None,
) -> None:
    """Best-effort EXPLAIN after a query failure.

    Opens a new session, runs ``EXPLAIN {cypher}``, and logs the plan via
    :func:`log_explain_result`.  Any exception is silently swallowed because
    the database may be unreachable.
    """
    try:
        session_kwargs: dict[str, Any] = {}
        if database:
            session_kwargs["database"] = database
        async with driver.session(**session_kwargs) as session:
            result = await session.run(f"EXPLAIN {cypher}", params)
            summary = await result.consume()
            log_explain_result(cypher, params, summary, error)
    except Exception:  # noqa: S110
        pass  # nosec B110 — best-effort; DB may be unreachable


async def run_query(
    driver: AsyncResilientNeo4jDriver,
    cypher: str,
    *,
    timeout: float | None = None,
    database: str | None = None,
    **params: Any,
) -> list[dict[str, Any]]:
    """Execute a Cypher query and return all results as a list of dicts.

    Args:
        driver: The async Neo4j driver.
        cypher: The Cypher query string.
        timeout: Optional query timeout in seconds.
        database: Optional Neo4j database name.
        **params: Query parameters forwarded to ``session.run()``.

    Returns:
        A list of dictionaries, one per result record.
    """
    log_cypher_query(cypher, params)

    profiling = is_db_profiling()
    actual_cypher = f"PROFILE {cypher}" if profiling else cypher

    run_kwargs: dict[str, Any] = {}
    if timeout is not None:
        run_kwargs["timeout"] = timeout

    session_kwargs: dict[str, Any] = {}
    if database:
        session_kwargs["database"] = database

    try:
        async with driver.session(**session_kwargs) as session:
            result = await session.run(actual_cypher, params, **run_kwargs)
            records = [dict(record) async for record in result]
            if profiling:
                summary = await result.consume()
                log_profile_result(cypher, params, summary)
            return records
    except Exception as exc:
        if profiling:
            await _try_explain_on_error(driver, cypher, params, exc, database)
        raise


async def run_single(
    driver: AsyncResilientNeo4jDriver,
    cypher: str,
    *,
    timeout: float | None = None,
    database: str | None = None,
    **params: Any,
) -> dict[str, Any] | None:
    """Execute a Cypher query and return a single result, or ``None``.

    Args:
        driver: The async Neo4j driver.
        cypher: The Cypher query string.
        timeout: Optional query timeout in seconds.
        database: Optional Neo4j database name.
        **params: Query parameters forwarded to ``session.run()``.

    Returns:
        A dictionary for the single record, or ``None`` if not found.
    """
    log_cypher_query(cypher, params)

    profiling = is_db_profiling()
    actual_cypher = f"PROFILE {cypher}" if profiling else cypher

    run_kwargs: dict[str, Any] = {}
    if timeout is not None:
        run_kwargs["timeout"] = timeout

    session_kwargs: dict[str, Any] = {}
    if database:
        session_kwargs["database"] = database

    try:
        async with driver.session(**session_kwargs) as session:
            result = await session.run(actual_cypher, params, **run_kwargs)
            record = await result.single()
            if profiling:
                summary = await result.consume()
                log_profile_result(cypher, params, summary)
            return dict(record) if record else None
    except Exception as exc:
        if profiling:
            await _try_explain_on_error(driver, cypher, params, exc, database)
        raise


async def run_count(
    driver: AsyncResilientNeo4jDriver,
    cypher: str,
    *,
    timeout: float | None = None,
    database: str | None = None,
    **params: Any,
) -> int:
    """Execute a count Cypher query and return the integer result.

    Expects the query to return a single record with a ``total`` field.

    Args:
        driver: The async Neo4j driver.
        cypher: The Cypher query string.
        timeout: Optional query timeout in seconds.
        database: Optional Neo4j database name.
        **params: Query parameters forwarded to ``session.run()``.

    Returns:
        The count as an integer, or ``0`` if no record is returned.
    """
    log_cypher_query(cypher, params)

    profiling = is_db_profiling()
    actual_cypher = f"PROFILE {cypher}" if profiling else cypher

    run_kwargs: dict[str, Any] = {}
    if timeout is not None:
        run_kwargs["timeout"] = timeout

    session_kwargs: dict[str, Any] = {}
    if database:
        session_kwargs["database"] = database

    try:
        async with driver.session(**session_kwargs) as session:
            result = await session.run(actual_cypher, params, **run_kwargs)
            record = await result.single()
            if profiling:
                summary = await result.consume()
                log_profile_result(cypher, params, summary)
            return int(record["total"]) if record else 0
    except Exception as exc:
        if profiling:
            await _try_explain_on_error(driver, cypher, params, exc, database)
        raise

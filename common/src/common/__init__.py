"""Stable, dependency-lazy public surface for GrooveMap runtime libraries."""

from importlib import import_module
from pkgutil import extend_path
from typing import TYPE_CHECKING, Any


__path__ = extend_path(__path__, __name__)

if TYPE_CHECKING:
    from common.config import neo4j_security_kwargs, parse_postgres_host_port, setup_logging
    from common.data_normalizer import normalize_record
    from common.db_resilience import (
        AsyncResilientConnection,
        CircuitBreaker,
        CircuitBreakerConfig,
        CircuitOpenError,
        CircuitState,
        ConnectionEstablishmentError,
        DatabaseUnavailableError,
        ExponentialBackoff,
        ResilientConnection,
        async_resilient_connection,
        resilient_connection,
    )
    from common.errors import describe_exception
    from common.health_server import HealthServer
    from common.neo4j_resilient import AsyncResilientNeo4jDriver, ResilientNeo4jDriver, with_async_neo4j_retry, with_neo4j_retry
    from common.outage_backoff import OutageBackoff
    from common.postgres_resilient import AsyncPostgreSQLPool, AsyncResilientPostgreSQL, ResilientPostgreSQLPool
    from common.query_debug import execute_sql, is_db_profiling, is_debug, log_cypher_query, log_sql_query
    from common.rabbitmq_resilient import AsyncResilientRabbitMQ, ResilientRabbitMQConnection, process_message_with_retry


_EXPORTS: dict[str, tuple[str, str]] = {
    "neo4j_security_kwargs": ("common.config", "neo4j_security_kwargs"),
    "parse_postgres_host_port": ("common.config", "parse_postgres_host_port"),
    "setup_logging": ("common.config", "setup_logging"),
    "normalize_record": ("common.data_normalizer", "normalize_record"),
    "AsyncResilientConnection": ("common.db_resilience", "AsyncResilientConnection"),
    "CircuitBreaker": ("common.db_resilience", "CircuitBreaker"),
    "CircuitBreakerConfig": ("common.db_resilience", "CircuitBreakerConfig"),
    "CircuitOpenError": ("common.db_resilience", "CircuitOpenError"),
    "CircuitState": ("common.db_resilience", "CircuitState"),
    "ConnectionEstablishmentError": ("common.db_resilience", "ConnectionEstablishmentError"),
    "DatabaseUnavailableError": ("common.db_resilience", "DatabaseUnavailableError"),
    "ExponentialBackoff": ("common.db_resilience", "ExponentialBackoff"),
    "ResilientConnection": ("common.db_resilience", "ResilientConnection"),
    "async_resilient_connection": ("common.db_resilience", "async_resilient_connection"),
    "resilient_connection": ("common.db_resilience", "resilient_connection"),
    "describe_exception": ("common.errors", "describe_exception"),
    "HealthServer": ("common.health_server", "HealthServer"),
    "AsyncResilientNeo4jDriver": ("common.neo4j_resilient", "AsyncResilientNeo4jDriver"),
    "ResilientNeo4jDriver": ("common.neo4j_resilient", "ResilientNeo4jDriver"),
    "with_async_neo4j_retry": ("common.neo4j_resilient", "with_async_neo4j_retry"),
    "with_neo4j_retry": ("common.neo4j_resilient", "with_neo4j_retry"),
    "OutageBackoff": ("common.outage_backoff", "OutageBackoff"),
    "AsyncPostgreSQLPool": ("common.postgres_resilient", "AsyncPostgreSQLPool"),
    "AsyncResilientPostgreSQL": ("common.postgres_resilient", "AsyncResilientPostgreSQL"),
    "ResilientPostgreSQLPool": ("common.postgres_resilient", "ResilientPostgreSQLPool"),
    "execute_sql": ("common.query_debug", "execute_sql"),
    "is_db_profiling": ("common.query_debug", "is_db_profiling"),
    "is_debug": ("common.query_debug", "is_debug"),
    "log_cypher_query": ("common.query_debug", "log_cypher_query"),
    "log_sql_query": ("common.query_debug", "log_sql_query"),
    "AsyncResilientRabbitMQ": ("common.rabbitmq_resilient", "AsyncResilientRabbitMQ"),
    "ResilientRabbitMQConnection": ("common.rabbitmq_resilient", "ResilientRabbitMQConnection"),
    "process_message_with_retry": ("common.rabbitmq_resilient", "process_message_with_retry"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Load an exported capability only when its dependency family is requested."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value

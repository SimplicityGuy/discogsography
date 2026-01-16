"""Common utilities and configuration for discogsography services."""

from common.config import (
    AMQP_EXCHANGE,
    AMQP_EXCHANGE_TYPE,
    AMQP_QUEUE_PREFIX_GRAPHINATOR,
    AMQP_QUEUE_PREFIX_TABLEINATOR,
    DATA_TYPES,
    DashboardConfig,
    ExtractorConfig,
    GraphinatorConfig,
    TableinatorConfig,
    get_config,
    setup_logging,
)

# Database resilience utilities
from common.db_resilience import (
    AsyncResilientConnection,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    ExponentialBackoff,
    ResilientConnection,
    async_resilient_connection,
    resilient_connection,
)
from common.health_server import HealthServer
from common.neo4j_resilient import (
    AsyncResilientNeo4jDriver,
    ResilientNeo4jDriver,
    with_async_neo4j_retry,
    with_neo4j_retry,
)
from common.postgres_resilient import (
    AsyncResilientPostgreSQL,
    ResilientPostgreSQLPool,
)
from common.rabbitmq_resilient import (
    AsyncResilientRabbitMQ,
    ResilientRabbitMQConnection,
    process_message_with_retry,
)
from common.data_normalizer import (
    normalize_record,
    normalize_artist,
    normalize_label,
    normalize_master,
    normalize_release,
    normalize_id,
    normalize_nested_list,
    normalize_item_with_id,
)


__all__ = [
    "AMQP_EXCHANGE",
    "AMQP_EXCHANGE_TYPE",
    "AMQP_QUEUE_PREFIX_GRAPHINATOR",
    "AMQP_QUEUE_PREFIX_TABLEINATOR",
    "DATA_TYPES",
    "AsyncResilientConnection",
    "AsyncResilientNeo4jDriver",
    "AsyncResilientPostgreSQL",
    "AsyncResilientRabbitMQ",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "DashboardConfig",
    "ExponentialBackoff",
    "ExtractorConfig",
    "GraphinatorConfig",
    "HealthServer",
    "ResilientConnection",
    "ResilientNeo4jDriver",
    "ResilientPostgreSQLPool",
    "ResilientRabbitMQConnection",
    "TableinatorConfig",
    "async_resilient_connection",
    "get_config",
    "process_message_with_retry",
    "resilient_connection",
    "setup_logging",
    "with_async_neo4j_retry",
    "with_neo4j_retry",
    "normalize_record",
    "normalize_artist",
    "normalize_label",
    "normalize_master",
    "normalize_release",
    "normalize_id",
    "normalize_nested_list",
    "normalize_item_with_id",
]

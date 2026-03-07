"""Common utilities and configuration for discogsography services."""

from common.config import (
    AMQP_EXCHANGE_PREFIX,
    AMQP_EXCHANGE_TYPE,
    AMQP_QUEUE_PREFIX_GRAPHINATOR,
    AMQP_QUEUE_PREFIX_TABLEINATOR,
    DATA_TYPES,
    ApiConfig,
    DashboardConfig,
    ExploreConfig,
    ExtractorConfig,
    GraphinatorConfig,
    TableinatorConfig,
    get_config,
    setup_logging,
)
from common.data_normalizer import (
    normalize_artist,
    normalize_id,
    normalize_item_with_id,
    normalize_label,
    normalize_master,
    normalize_nested_list,
    normalize_record,
    normalize_release,
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
from common.oauth import _build_oauth_header, _hmac_sha1_signature, _oauth_escape
from common.postgres_resilient import (
    AsyncPostgreSQLPool,
    AsyncResilientPostgreSQL,
    ResilientPostgreSQLPool,
)
from common.rabbitmq_resilient import (
    AsyncResilientRabbitMQ,
    ResilientRabbitMQConnection,
    process_message_with_retry,
)
from common.state_marker import (
    DownloadPhase,
    ExtractionSummary,
    FileProcessingStatus,
    PhaseStatus,
    ProcessingDecision,
    ProcessingPhase,
    PublishingPhase,
    StateMarker,
)


__all__ = [
    "AMQP_EXCHANGE_PREFIX",
    "AMQP_EXCHANGE_TYPE",
    "AMQP_QUEUE_PREFIX_GRAPHINATOR",
    "AMQP_QUEUE_PREFIX_TABLEINATOR",
    "DATA_TYPES",
    "ApiConfig",
    "AsyncPostgreSQLPool",
    "AsyncResilientConnection",
    "AsyncResilientNeo4jDriver",
    "AsyncResilientPostgreSQL",
    "AsyncResilientRabbitMQ",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "DashboardConfig",
    "DownloadPhase",
    "ExploreConfig",
    "ExponentialBackoff",
    "ExtractionSummary",
    "ExtractorConfig",
    "FileProcessingStatus",
    "GraphinatorConfig",
    "HealthServer",
    "PhaseStatus",
    "ProcessingDecision",
    "ProcessingPhase",
    "PublishingPhase",
    "ResilientConnection",
    "ResilientNeo4jDriver",
    "ResilientPostgreSQLPool",
    "ResilientRabbitMQConnection",
    "StateMarker",
    "TableinatorConfig",
    "_build_oauth_header",
    "_hmac_sha1_signature",
    "_oauth_escape",
    "async_resilient_connection",
    "get_config",
    "normalize_artist",
    "normalize_id",
    "normalize_item_with_id",
    "normalize_label",
    "normalize_master",
    "normalize_nested_list",
    "normalize_record",
    "normalize_release",
    "process_message_with_retry",
    "resilient_connection",
    "setup_logging",
    "with_async_neo4j_retry",
    "with_neo4j_retry",
]

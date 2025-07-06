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
from common.health_server import HealthServer


__all__ = [
    "AMQP_EXCHANGE",
    "AMQP_EXCHANGE_TYPE",
    "AMQP_QUEUE_PREFIX_GRAPHINATOR",
    "AMQP_QUEUE_PREFIX_TABLEINATOR",
    "DATA_TYPES",
    "DashboardConfig",
    "ExtractorConfig",
    "GraphinatorConfig",
    "HealthServer",
    "TableinatorConfig",
    "get_config",
    "setup_logging",
]

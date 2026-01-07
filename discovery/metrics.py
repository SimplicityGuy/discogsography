"""Prometheus metrics for the discovery service."""

from prometheus_client import Counter, Gauge, Histogram


# Request metrics
request_count = Counter(
    "discovery_requests_total",
    "Total number of requests by endpoint and method",
    ["method", "endpoint", "status_code"],
)

request_duration = Histogram(
    "discovery_request_duration_seconds",
    "Request duration in seconds",
    ["method", "endpoint"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

active_requests = Gauge(
    "discovery_active_requests",
    "Number of currently active requests",
    ["method", "endpoint"],
)

# Error metrics
error_count = Counter(
    "discovery_errors_total",
    "Total number of errors by endpoint and error type",
    ["method", "endpoint", "error_type"],
)

# Cache metrics
cache_hits = Counter(
    "discovery_cache_hits_total",
    "Total number of cache hits by cache_key",
    ["cache_key"],
)

cache_misses = Counter(
    "discovery_cache_misses_total",
    "Total number of cache misses by cache_key",
    ["cache_key"],
)

cache_size = Gauge(
    "discovery_cache_size_bytes",
    "Current size of cache in bytes",
    ["cache_name"],
)

# Database metrics
db_query_duration = Histogram(
    "discovery_db_query_duration_seconds",
    "Database query duration in seconds",
    ["db_type", "operation"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

db_query_count = Counter(
    "discovery_db_queries_total",
    "Total number of database queries",
    ["db_type", "operation", "status"],
)

# Neo4j specific metrics
neo4j_connections = Gauge(
    "discovery_neo4j_connections",
    "Number of active Neo4j connections",
)

neo4j_query_failures = Counter(
    "discovery_neo4j_query_failures_total",
    "Total number of failed Neo4j queries",
    ["query_type"],
)

# PostgreSQL specific metrics
postgres_connections = Gauge(
    "discovery_postgres_connections",
    "Number of active PostgreSQL connections",
)

postgres_query_failures = Counter(
    "discovery_postgres_query_failures_total",
    "Total number of failed PostgreSQL queries",
    ["query_type"],
)

# Note: Recommendation metrics are defined in recommender_metrics.py
# Note: Analytics metrics will be defined when analytics module needs them

# Graph exploration metrics
graph_exploration_requests = Counter(
    "discovery_graph_exploration_requests_total",
    "Total number of graph exploration requests",
    ["exploration_type"],
)

graph_exploration_duration = Histogram(
    "discovery_graph_exploration_duration_seconds",
    "Graph exploration duration in seconds",
    ["exploration_type"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# WebSocket metrics
websocket_connections = Gauge(
    "discovery_websocket_connections",
    "Number of active WebSocket connections",
)

websocket_messages_sent = Counter(
    "discovery_websocket_messages_sent_total",
    "Total number of WebSocket messages sent",
)

websocket_messages_received = Counter(
    "discovery_websocket_messages_received_total",
    "Total number of WebSocket messages received",
)

# ONNX model metrics
onnx_model_loaded = Gauge(
    "discovery_onnx_model_loaded",
    "Whether ONNX model is loaded (1) or fallback to PyTorch (0)",
)

model_inference_duration = Histogram(
    "discovery_model_inference_duration_seconds",
    "Model inference duration in seconds",
    ["model_type"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
)

model_inference_count = Counter(
    "discovery_model_inference_total",
    "Total number of model inferences",
    ["model_type"],
)

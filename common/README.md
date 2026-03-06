# Common Module

Shared utilities and configuration for all discogsography services.

## Contents

- `config.py`: Centralized configuration management (environment variable parsing, defaults)
- `health_server.py`: Lightweight HTTP health check server used by all services
- `data_normalizer.py`: Record normalization (`normalize_record()`) that flattens XML-dict structures from the extractor into consistent formats; also provides `extract_format_names()` and `_parse_year_int()`
- `neo4j_resilient.py`: `ResilientNeo4jDriver` / `AsyncResilientNeo4jDriver` — Neo4j driver wrappers with retry logic and connection resilience
- `postgres_resilient.py`: `ResilientPostgreSQLPool` / `AsyncPostgreSQLPool` — PostgreSQL connection pools with retry logic
- `rabbitmq_resilient.py`: `ResilientRabbitMQConnection` / `AsyncResilientRabbitMQ` — RabbitMQ connection wrappers with automatic reconnection
- `db_resilience.py`: Shared retry/backoff primitives (`CircuitBreaker`, `ExponentialBackoff`) used by the database drivers
- `oauth.py`: OAuth 1.0a signing utilities (HMAC-SHA1 signatures, Authorization header building)
- `state_marker.py`: Extraction state marker system for tracking progress and enabling safe restarts

### Key Constants (`__init__.py`)

- `AMQP_EXCHANGE`: Exchange name (`discogsography-exchange`)
- `AMQP_EXCHANGE_TYPE`: Exchange type (`topic`)
- `AMQP_QUEUE_PREFIX_GRAPHINATOR`: Queue prefix for graphinator consumers
- `AMQP_QUEUE_PREFIX_TABLEINATOR`: Queue prefix for tableinator consumers

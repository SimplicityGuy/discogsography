# Dashboard Service

Real-time monitoring dashboard for the Discogsography system with WebSocket support for live updates.

## Overview

The dashboard service provides a web-based interface to monitor all Discogsography services, including:

- Service health status (extractor, graphinator, tableinator)
- RabbitMQ queue metrics and consumer counts
- PostgreSQL and Neo4j database statistics
- Real-time activity logs
- WebSocket-based live updates

## Architecture

- **Backend**: FastAPI with WebSocket support
- **Frontend**: Tailwind CSS, Inter/JetBrains Mono fonts, SVG circular gauges, CSS bar charts
- **Port**: 8003
- **Health Endpoint**: `/health` (port 8003)

## Configuration

Environment variables:

```bash
# Database connections
NEO4J_HOST=neo4j
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=discogsography

POSTGRES_HOST=postgres
POSTGRES_USERNAME=discogsography
POSTGRES_PASSWORD=discogsography
POSTGRES_DATABASE=discogsography

# RabbitMQ (also supports _FILE variants for Docker secrets)
RABBITMQ_HOST=rabbitmq
RABBITMQ_USERNAME=discogsography
RABBITMQ_PASSWORD=discogsography

# Redis
REDIS_HOST=redis

# Optional
CORS_ORIGINS="http://localhost:3000,http://localhost:8003"
LOG_LEVEL=INFO
```

Service health URLs (`http://extractor:8000/health`, etc.) and the RabbitMQ management URL (`http://rabbitmq:15672`) are hardcoded. The dashboard port is fixed at **8003**.

## API Endpoints

- `GET /` - Dashboard web interface
- `GET /health` - Health check endpoint (port 8003)
- `GET /api/metrics` - Current system metrics
- `GET /api/services` - Service-specific metrics
- `GET /api/queues` - Queue metrics
- `GET /api/databases` - Database metrics
- `GET /metrics` - Prometheus metrics endpoint
- `WS /ws` - WebSocket connection for real-time updates

## WebSocket Updates

The dashboard broadcasts updates every 2 seconds with the following data:

```json
{
  "type": "metrics_update",
  "data": {
    "services": {
      "extractor": { "status": "healthy", "health_url": "..." },
      "graphinator": { "status": "healthy", "health_url": "..." },
      "tableinator": { "status": "healthy", "health_url": "..." }
    },
    "queues": {
      "labels": { "messages": 0, "consumers": 1 },
      "artists": { "messages": 0, "consumers": 1 },
      "releases": { "messages": 0, "consumers": 1 },
      "masters": { "messages": 0, "consumers": 1 }
    },
    "databases": {
      "neo4j": { "connections": 5, "database_size": "1.2 GB" },
      "postgresql": { "connections": 10, "database_size": "3.4 GB" }
    },
    "activity": [
      { "timestamp": "2025-01-06T10:15:30", "message": "Service started" }
    ]
  }
}
```

## Development

### Running Locally

```bash
# Install dependencies
uv sync --extra dashboard

# Run the dashboard
uv run python dashboard/dashboard.py
```

### Running Tests

```bash
# Run API tests
uv run pytest tests/dashboard/test_dashboard_api.py -v

# Run integration tests
uv run pytest tests/dashboard/test_dashboard_api_integration.py -v

# Run E2E tests (requires running dashboard)
just test-e2e
```

### Frontend Development

The frontend consists of static files in the `static/` directory:

- `index.html` - Main dashboard page (Tailwind CSS, dark theme)
- `dashboard.js` - WebSocket client and UI update logic

The `tailwind.css` stylesheet is **generated at Docker build time** and does not exist in the source tree.

Two additional files in `dashboard/` (not `static/`) drive the CSS build:

- `tailwind.config.js` - Tailwind CLI configuration (content paths, forms plugin)
- `tailwind.input.css` - Tailwind source directives (`@tailwind base/components/utilities`)

The Docker build uses a dedicated **`css-builder`** stage (Node 24) to run the Tailwind CLI, which
scans `index.html` and emits a minified `tailwind.css` into the final image. No CDN dependency is
needed at runtime.

## Docker

Build and run with Docker:

```bash
# Build
docker build -f dashboard/Dockerfile .

# Run with docker-compose
docker-compose up dashboard
```

## Monitoring

The dashboard itself exposes metrics at `/api/metrics` for monitoring its own health and the health of all connected services.

## Security

- CORS is configured for production use
- All external service calls have timeouts
- Sensitive configuration is loaded from environment variables

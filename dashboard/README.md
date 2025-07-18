# Dashboard Service

Real-time monitoring dashboard for the Discogsography system with WebSocket support for live updates.

## Overview

The dashboard service provides a web-based interface to monitor all Discogsography services, including:

- Service health status (extractor, graphinator, tableinator, discovery)
- RabbitMQ queue metrics and consumer counts
- PostgreSQL and Neo4j database statistics
- Real-time activity logs
- WebSocket-based live updates

## Architecture

- **Backend**: FastAPI with WebSocket support
- **Frontend**: Vanilla JavaScript with dynamic updates
- **Port**: 8003 (configurable via `DASHBOARD_PORT`)
- **Health Endpoint**: `/health` (port 8003)

## Configuration

Environment variables:

```bash
# Dashboard settings
DASHBOARD_HOST=0.0.0.0    # Host to bind to
DASHBOARD_PORT=8003       # Port for web interface

# Service endpoints
EXTRACTOR_URL=http://extractor:8000
GRAPHINATOR_URL=http://graphinator:8001
TABLEINATOR_URL=http://tableinator:8002
DISCOVERY_URL=http://discovery:8004

# Database connections
NEO4J_ADDRESS=neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=discogsography

POSTGRES_ADDRESS=postgres:5433
POSTGRES_USERNAME=discogsography
POSTGRES_PASSWORD=discogsography
POSTGRES_DATABASE=discogsography

# RabbitMQ connection
AMQP_CONNECTION=amqp://discogsography:discogsography@rabbitmq:5672
RABBITMQ_MANAGEMENT_URL=http://rabbitmq:15672
```

## API Endpoints

- `GET /` - Dashboard web interface
- `GET /health` - Health check endpoint (port 8003)
- `GET /api/metrics` - Current system metrics
- `WS /ws` - WebSocket connection for real-time updates

## WebSocket Updates

The dashboard broadcasts updates every 5 seconds with the following data:

```json
{
  "type": "metrics_update",
  "data": {
    "services": {
      "extractor": { "status": "healthy", "health_url": "..." },
      "graphinator": { "status": "healthy", "health_url": "..." },
      "tableinator": { "status": "healthy", "health_url": "..." },
      "discovery": { "status": "healthy", "health_url": "..." }
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
./scripts/test-e2e.sh
```

### Frontend Development

The frontend consists of static files in the `static/` directory:

- `index.html` - Main dashboard page
- `styles.css` - Dashboard styling
- `script.js` - WebSocket client and UI updates

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
- WebSocket connections are authenticated
- All external service calls have timeouts
- Sensitive configuration is loaded from environment variables

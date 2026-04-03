# Dashboard Service

Real-time monitoring dashboard for the Discogsography system with WebSocket support for live updates.

## Overview

The dashboard service provides a web-based interface to monitor all Discogsography services, including:

- Service health status for both Discogs and MusicBrainz pipelines
- RabbitMQ queue metrics and consumer counts, grouped by pipeline
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

Service health URLs (`http://extractor-discogs:8000/health`, `http://extractor-musicbrainz:8000/health`, etc.) and the RabbitMQ management URL (`http://rabbitmq:15672`) are hardcoded. The dashboard port is fixed at **8003**.

## API Endpoints

- `GET /` - Dashboard web interface
- `GET /health` - Health check endpoint (port 8003)
- `GET /api/metrics` - Current system metrics (pipelines + databases)
- `GET /api/services` - Service metrics grouped by pipeline
- `GET /api/queues` - Queue metrics grouped by pipeline
- `GET /api/databases` - Database metrics
- `GET /metrics` - Prometheus metrics endpoint
- `WS /ws` - WebSocket connection for real-time updates

### Admin Proxy Routes

The dashboard proxies the following routes to the API service (requires JWT authentication):

- `POST /admin/api/extractions/trigger` - Trigger a full Discogs extraction
- `POST /admin/api/extractions/trigger-musicbrainz` - Trigger a full MusicBrainz extraction

## Pipeline-Grouped API Responses

Services and queues are now grouped by pipeline. The `/api/metrics` endpoint returns:

```json
{
  "pipelines": {
    "discogs": {
      "services": [
        { "name": "extractor-discogs", "status": "healthy", "last_seen": "...", "current_task": null, "progress": null, "error": null },
        { "name": "graphinator", "status": "healthy", "..." : "..." },
        { "name": "tableinator", "status": "healthy", "..." : "..." }
      ],
      "queues": [
        { "name": "discogsography-discogs-graphinator-artists", "messages": 0, "messages_ready": 0, "messages_unacknowledged": 0, "consumers": 1, "message_rate": 0.0, "ack_rate": 0.0 },
        { "name": "discogsography-discogs-tableinator-artists", "messages": 0, "..." : "..." }
      ]
    },
    "musicbrainz": {
      "services": [
        { "name": "extractor-musicbrainz", "status": "healthy", "..." : "..." },
        { "name": "brainzgraphinator", "status": "healthy", "..." : "..." },
        { "name": "brainztableinator", "status": "healthy", "..." : "..." }
      ],
      "queues": [
        { "name": "discogsography-musicbrainz-brainzgraphinator-artists", "messages": 0, "..." : "..." }
      ]
    }
  },
  "databases": [
    { "name": "Neo4j", "status": "healthy", "connection_count": 1, "size": "1,000 nodes, 5,000 relationships", "error": null },
    { "name": "PostgreSQL", "status": "healthy", "connection_count": 10, "size": "3.40 GB", "error": null }
  ],
  "timestamp": "2025-01-06T10:15:30+00:00"
}
```

The `/api/services` and `/api/queues` endpoints return dicts keyed by pipeline name, each containing a list of service or queue objects matching the structure above.

### MusicBrainz Pipeline Auto-Detection

The MusicBrainz pipeline section is **hidden automatically** when the MusicBrainz services (brainzgraphinator, brainztableinator) are not deployed. The dashboard checks health endpoints on startup and hides the entire pipeline panel if none of the MB services respond. This makes the dashboard safe to deploy in environments where only Discogs is running.

### Queue Prefixes

- **Discogs queues**: use the `discogsography-discogs` exchange prefix (4 entity types: artists, labels, masters, releases)
- **MusicBrainz queues**: use the `discogsography-musicbrainz` exchange prefix (3 entity types: artists, labels, releases — no masters)

## WebSocket Updates

The dashboard broadcasts updates every 2 seconds with the following data:

```json
{
  "type": "metrics_update",
  "data": {
    "pipelines": {
      "discogs": {
        "services": [{ "name": "extractor-discogs", "status": "healthy", "..." : "..." }, "..."],
        "queues": [{ "name": "discogsography-discogs-graphinator-artists", "messages": 0, "..." : "..." }, "..."]
      },
      "musicbrainz": {
        "services": [{ "name": "brainzgraphinator", "status": "healthy", "..." : "..." }, "..."],
        "queues": [{ "name": "discogsography-musicbrainz-brainzgraphinator-artists", "messages": 0, "..." : "..." }, "..."]
      }
    },
    "databases": [
      { "name": "Neo4j", "status": "healthy", "connection_count": 1, "size": "1,000 nodes, 5,000 relationships", "error": null },
      { "name": "PostgreSQL", "status": "healthy", "connection_count": 10, "size": "3.40 GB", "error": null }
    ],
    "timestamp": "2025-01-06T10:15:30+00:00"
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

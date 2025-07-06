# Discogsography Dashboard

A real-time monitoring dashboard for the Discogsography system, providing visibility into service health, message queue status, and database metrics.

## Features

- **Real-time Updates**: WebSocket connection for live metrics
- **Service Monitoring**: Track health and progress of extractor, graphinator, and tableinator services
- **Queue Analytics**: Monitor RabbitMQ queue sizes, consumer counts, and message rates
- **Database Status**: View PostgreSQL and Neo4j connection counts and sizes
- **Interactive Charts**: Visualize queue statistics with Chart.js
- **Activity Log**: Track recent system events and status changes
- **Responsive Design**: Works on desktop and mobile devices

## Architecture

The dashboard consists of:

- **FastAPI Backend**: RESTful API and WebSocket server
- **Static Frontend**: Pure JavaScript with Chart.js for visualization
- **Real-time Updates**: WebSocket connection for live data streaming
- **Metrics Collection**: Background task polling service health endpoints

## API Endpoints

- `GET /api/metrics` - Get all system metrics
- `GET /api/services` - Get service statuses
- `GET /api/queues` - Get queue information
- `GET /api/databases` - Get database information
- `GET /metrics` - Prometheus metrics endpoint
- `WS /ws` - WebSocket endpoint for real-time updates

## Configuration

The dashboard uses the same configuration as other services via `config.py`. Key settings:

- Service health check URLs
- RabbitMQ management API credentials
- Database connection parameters

## Development

Run locally:

```bash
cd dashboard
uv run python dashboard.py
```

Access at http://localhost:8003

## Docker Integration

The dashboard is included in the docker-compose setup and will automatically connect to other services when running in the container environment.

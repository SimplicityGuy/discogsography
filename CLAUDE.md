# 🤖 CLAUDE.md - Claude Code Development Guide

<div align="center">

**The comprehensive guide for AI-assisted development with Claude Code (claude.ai/code)**

[📚 Quick Reference](#-quick-reference) | [🎯 Architecture](#-architecture-components) | [🛠️ Development](#-development-commands) | [📋 Guidelines](#-development-guidelines) | [📋 Emoji Guide](docs/emoji-guide.md)

</div>

> 💡 **Pro Tip**: This guide is optimized for Claude Code's understanding of the codebase. It includes specific conventions, patterns, and instructions that help Claude Code provide better assistance.

## 🎯 Project Overview

**Discogsography** is a production-grade Python 3.13+ microservices platform that transforms Discogs music database exports into powerful, queryable knowledge graphs and analytics engines.

### Core Design Principles

- **🚀 Performance First**: Async operations, efficient parsing, optimized queries
- **🔒 Type Safety**: Full type hints, strict mypy validation, runtime checks
- **🛡️ Security by Design**: Container hardening, secure defaults, continuous scanning
- **📊 Observable**: Comprehensive logging, real-time monitoring, health checks
- **🧪 Testable**: Unit, integration, and E2E tests with high coverage

## 🤖 AI Development Memories

- ✅ Create Mermaid style diagrams when diagrams are added to Markdown files.
- ✅ New markdown files should have a lowercase filename preferring - instead \_, unless the document is a README. Do not rename any existing markdown files.

## 📋 Development Guidelines

### Logging Standards

All services use consistent logging with emojis for visual clarity:

- **Format**: `%(asctime)s - {service_name} - %(name)s - %(levelname)s - %(message)s`
- **Files**: Services log to `/logs/{service_name}.log`
- **Emojis**: See [Emoji Guide](docs/emoji-guide.md) for standardized usage

Example:

```python
logger.info("🚀 Service starting...")
logger.info("✅ Operation completed successfully")
logger.error("❌ Failed to connect to database")
```

### ASCII Art Standards

Each service displays ASCII art on startup:

- Pure text only (no emojis in ASCII art)
- Service name prominently displayed
- Consistent style across all services

### Code Style

- Use type hints for all function parameters and returns
- Follow PEP 8 with 88-character line length (Black formatter)
- Use descriptive variable names
- Add docstrings to all public functions and classes

### Testing Requirements

- Unit tests for all business logic
- Integration tests for service interactions
- E2E tests for critical user paths
- Maintain >80% code coverage

### Security Best Practices

- Never log sensitive data (passwords, tokens, PII)
- Use environment variables for configuration
- Run containers as non-root users
- Keep dependencies updated

## 🛠️ Development Commands

### Service Management

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f [service_name]

# Run tests
docker-compose exec [service_name] pytest

# Check service health
docker-compose ps
```

### Database Access

```bash
# Neo4j Browser
http://localhost:7474

# PostgreSQL
docker-compose exec postgres psql -U postgres discogsography
```

### Debugging

```bash
# View RabbitMQ management
http://localhost:15672

# Check service metrics
http://localhost:8000/api/health
```

## 📚 Quick Reference

### Service Ports

- Dashboard: 8000
- Discovery: 8001
- Neo4j: 7474 (browser), 7687 (bolt)
- PostgreSQL: 5432
- RabbitMQ: 5672 (AMQP), 15672 (management)

### Environment Variables

- `NEO4J_URI`: Neo4j connection string
- `POSTGRES_URL`: PostgreSQL connection string
- `RABBITMQ_URL`: RabbitMQ connection string
- `LOG_LEVEL`: Logging level (INFO, DEBUG, WARNING, ERROR)

### Common Tasks

- Adding new endpoints: Update FastAPI routers in service
- Processing new data types: Extend message schemas
- Adding visualizations: Update dashboard components
- Performance tuning: Check service metrics first

## 🎯 Architecture Components

See main [README.md](README.md) for detailed architecture information.

## 📐 Best Practices for Claude Code

1. **Always read existing code** before making changes
1. **Follow established patterns** in the codebase
1. **Use the emoji guide** for consistent visual communication
1. **Test changes** before marking tasks complete
1. **Document significant changes** in code comments
1. **Check logs** when debugging issues
1. **Validate data** at service boundaries
1. **Handle errors gracefully** with proper logging

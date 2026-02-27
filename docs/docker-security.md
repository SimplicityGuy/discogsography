# Docker Security Configuration

This document describes the security measures implemented in the discogsography Docker deployment.

## Security Features

### 1. Non-Root User Execution

All services run as a non-root user with configurable UID/GID:

```yaml
user: "${UID:-1000}:${GID:-1000}"
```

- Default: UID=1000, GID=1000
- Customize by setting `UID` and `GID` environment variables
- Matches host user to avoid permission issues with volumes

### 2. Capability Dropping

All application containers drop all Linux capabilities:

```yaml
cap_drop:
  - ALL
```

This prevents containers from:

- Modifying network configuration
- Loading kernel modules
- Accessing raw sockets
- Other privileged operations

### 3. No New Privileges

Prevents privilege escalation:

```yaml
security_opt:
  - no-new-privileges:true
```

### 4. Read-Only Root Filesystem

Application containers use read-only root filesystems:

```yaml
read_only: true
tmpfs:
  - /tmp
```

- Prevents malicious writes to the container filesystem
- `/tmp` is mounted as tmpfs for temporary files
- Application data uses explicit volumes

### 5. Health Checks

All services implement HTTP health endpoints:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s
```

### 6. Network Isolation

Services use a dedicated Docker network:

```yaml
networks:
  discogsography:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

### 7. Restart Policies (Production)

Production deployment includes automatic restart policies:

```yaml
deploy:
  restart_policy:
    condition: any
    delay: 5s
    max_attempts: 3
```

## Environment Variables

### Security-Sensitive Variables

These secrets are **never passed as plain environment variables in production**. Instead, they are mounted as in-memory tmpfs files via Docker Compose runtime secrets and read through the `_FILE` convention. See [Production Secrets Setup](#production-secrets-setup) below.

| Secret | `_FILE` env var | Plain env var (dev only) |
|--------|-----------------|--------------------------|
| RabbitMQ password | `RABBITMQ_PASSWORD_FILE` | `RABBITMQ_DEFAULT_PASS` |
| RabbitMQ username | `RABBITMQ_USERNAME_FILE` | `RABBITMQ_DEFAULT_USER` |
| PostgreSQL password | `POSTGRES_PASSWORD_FILE` | `POSTGRES_PASSWORD` |
| PostgreSQL username | `POSTGRES_USER_FILE` | `POSTGRES_USER` |
| Neo4j password | (via entrypoint wrapper) | `NEO4J_AUTH` |
| JWT secret key | `JWT_SECRET_KEY_FILE` | `JWT_SECRET_KEY` |
| OAuth encryption key | `OAUTH_ENCRYPTION_KEY_FILE` | `OAUTH_ENCRYPTION_KEY` |
| RabbitMQ mgmt user | `RABBITMQ_MANAGEMENT_USER_FILE` | `RABBITMQ_MANAGEMENT_USER` |
| RabbitMQ mgmt password | `RABBITMQ_MANAGEMENT_PASSWORD_FILE` | `RABBITMQ_MANAGEMENT_PASSWORD` |

Plain env vars work in development. The production overlay (`docker-compose.prod.yml`) switches to the `_FILE` convention automatically — application code handles both via `get_secret()` in `common/config.py`.

### User Configuration

Set these to match your host user:

```bash
export UID=$(id -u)
export GID=$(id -g)
```

## Production Secrets Setup

### 8. Runtime Secrets via `docker-compose.prod.yml`

The production overlay mounts secrets as in-memory tmpfs files at `/run/secrets/<name>`. Secret values are **never visible in `docker inspect`**, never written to disk, and flushed when the container stops.

**Step 1 — Generate secrets** (idempotent, skips existing files):

```bash
bash scripts/create-secrets.sh
```

This creates `secrets/` (mode `700`) with one file per secret (mode `600`):

```
secrets/
├── jwt_secret_key.txt        # openssl rand -hex 32
├── neo4j_password.txt        # openssl rand -base64 24
├── oauth_encryption_key.txt  # Fernet.generate_key()
├── postgres_password.txt     # openssl rand -base64 24
├── postgres_username.txt         # discogsography
├── rabbitmq_password.txt         # openssl rand -base64 24
└── rabbitmq_username.txt         # discogsography
```

Use `secrets.example/` as a reference for each file's format and generation command.

**Step 2 — Start with production overlay**:

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**Neo4j note**: Neo4j does not natively support the `_FILE` convention. The production overlay overrides Neo4j's entrypoint with `scripts/neo4j-entrypoint.sh`, which reads `/run/secrets/neo4j_password` and sets `NEO4J_AUTH=neo4j/<password>` before delegating to the official Neo4j entrypoint.

### Running Securely

**Development**:

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env to set UID/GID

# Run with security features
docker-compose up -d
```

**Production**:

```bash
# 1. Generate secrets (first time only — safe to re-run)
bash scripts/create-secrets.sh

# 2. Start with production overlay (secrets + restart policies)
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Security Best Practices

1. **Regular Updates**

   - Update base images regularly
   - Rebuild containers for security patches
   - Monitor for vulnerabilities with tools like Trivy

1. **Secrets Management**

   - Use `docker-compose.prod.yml` with `scripts/create-secrets.sh` for Docker Compose deployments
   - For Kubernetes, use Kubernetes Secrets or an external secrets operator
   - For cloud deployments, consider AWS Secrets Manager, Azure Key Vault, or HashiCorp Vault
   - Never use default passwords in production
   - Rotate secrets by updating the file in `secrets/` and restarting the affected container

1. **Monitoring**

   - Monitor container logs for suspicious activity
   - Set up alerts for health check failures
   - Track resource usage for anomalies

1. **Network Security**

   - Use TLS for all external connections
   - Restrict exposed ports to minimum required
   - Consider using reverse proxy (nginx, traefik) for services

## Verification

### Check Security Configuration

```bash
# Verify user execution
docker-compose exec extractor id

# Check capabilities
docker-compose exec extractor capsh --print

# Verify read-only filesystem
docker-compose exec extractor touch /test.txt  # Should fail

# Check security options
docker inspect discogsography-extractor | jq '.[0].HostConfig.SecurityOpt'
```

### Security Scanning

```bash
# Scan images for vulnerabilities
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy image discogsography/extractor:latest

# Check for misconfigurations
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy config .
```

## Troubleshooting

### Permission Issues

If you encounter permission errors:

1. Check UID/GID match your user:

   ```bash
   echo "Host: UID=$(id -u) GID=$(id -g)"
   docker-compose exec service id
   ```

1. Fix volume permissions:

   ```bash
   sudo chown -R $(id -u):$(id -g) ./volumes/
   ```

### Read-Only Filesystem Errors

Some applications may need writable directories:

1. Add specific tmpfs mounts:

   ```yaml
   tmpfs:
     - /tmp
     - /run
     - /var/cache
   ```

1. Or use volumes for persistent data:

   ```yaml
   volumes:
     - app_cache:/app/.cache
   ```

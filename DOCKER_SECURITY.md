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

Never commit these to version control:

- `RABBITMQ_PASS`
- `POSTGRES_PASSWORD`
- `NEO4J_PASSWORD`

### User Configuration

Set these to match your host user:

```bash
export UID=$(id -u)
export GID=$(id -g)
```

## Running Securely

### Development

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env to set UID/GID

# Run with security features
docker-compose up -d
```

### Production

```bash
# Use production overlay with restart policies
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Additional hardening with Docker flags
docker run \
  --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --read-only \
  --tmpfs /tmp \
  discogsography/service:latest
```

## Security Best Practices

1. **Regular Updates**

   - Update base images regularly
   - Rebuild containers for security patches
   - Monitor for vulnerabilities with tools like Trivy

1. **Secrets Management**

   - Use Docker secrets in Swarm mode
   - Consider external secret management (Vault, AWS Secrets Manager)
   - Never use default passwords in production

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

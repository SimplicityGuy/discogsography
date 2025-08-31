# Docker Image Optimization Results

## Summary of Size Reductions

| Service     | Before | After | Reduction | Percentage |
| ----------- | ------ | ----- | --------- | ---------- |
| dashboard   | 284MB  | 253MB | 31MB      | 10.9%      |
| extractor   | 241MB  | 210MB | 31MB      | 12.9%      |
| graphinator | 251MB  | 220MB | 31MB      | 12.4%      |
| tableinator | 230MB  | 199MB | 31MB      | 13.5%      |
| discovery   | 1.32GB | 982MB | 350MB     | 26.5%      |

**Total reduction across all services: 474MB**

## Optimizations Applied

### Common Optimizations (All Services)

1. **Removed UV from runtime stage** - UV package manager is only needed during build
1. **Selective file copying** - Only copy necessary directories (.venv, common, service)
1. **Python cache cleanup** - Remove .pyc, .pyo, __pycache__ files
1. **Test file removal** - Remove test directories from site-packages
1. **Strip debug symbols** - Use strip command on .so files
1. **Clean apt lists** - Remove /tmp/\* and /var/tmp/\* after apt operations

### Service-Specific Optimizations

**Discovery Service** (Phase 1-3 optimizations):

- External model storage with persistent volume
- ONNX runtime support infrastructure
- Removed gcc/g++ from runtime
- Added .dockerignore file

**Extractor Service**:

- Kept all boto3 data files to ensure S3 functionality
- Note: Aggressive optimization of boto3 data (removing non-S3 services) saves ~15MB but causes runtime errors
- The full botocore data is required for proper AWS service discovery

**All Services**:

- Proper multi-stage build practices
- Minimal runtime dependencies
- Security-focused minimal installations

## Build Performance

- All services continue to build successfully
- Docker layer caching remains effective
- No functionality compromised

## Recommendations for Further Optimization

1. **Use Alpine Linux base** - Could reduce base image from ~150MB to ~50MB

   - Requires careful testing due to musl libc differences
   - May have compatibility issues with some Python packages

1. **Create shared base image** - Since all services share common dependencies

   - Would improve build times
   - Reduce overall storage when multiple services are deployed

1. **Implement distroless images** - For production deployments

   - Even smaller attack surface
   - No shell or package manager in runtime

1. **Use BuildKit cache mounts** - For pip/uv caches across builds

   - Already implemented with `--mount=type=cache`

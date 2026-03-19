#!/bin/sh
set -e

echo "=================================================="
echo "  Discogsography API Performance Test"
echo "=================================================="
echo ""

# Run the performance test
python /app/run_perftest.py --config /config/config.yaml --output /results

echo ""
echo "Collecting API logs..."

# Copy API logs if the API container's log volume is mounted
if [ -d "/api-logs" ]; then
    cp /api-logs/api.log /results/api.log 2>/dev/null || echo "  api.log not found"
    cp /api-logs/profiling.log /results/profiling.log 2>/dev/null || echo "  profiling.log not found"
    echo "API logs copied to results directory."
else
    echo "  /api-logs not mounted - skipping log collection."
    echo "  To collect API logs, add: -v discogsography_api_logs:/api-logs:ro"
fi

echo ""
echo "Results saved to /results/"
echo "=================================================="

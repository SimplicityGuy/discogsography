#!/bin/sh
set -e

echo "=================================================="
echo "  Discogsography API Performance Test"
echo "=================================================="
echo ""

# Run the performance test
python /app/run_perftest.py --config /config/config.yaml --output /results

echo ""
echo "Results saved to /results/"
echo ""
echo "To collect API logs, run from the host:"
echo "  docker cp discogsography-api:/logs/api.log ./perftest-results/"
echo "  docker cp discogsography-api:/logs/profiling.log ./perftest-results/"
echo "=================================================="

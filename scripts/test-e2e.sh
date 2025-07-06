#!/usr/bin/env bash
# Script to run E2E tests with proper setup

set -e

echo "🚀 Starting E2E test setup..."

# Check if dashboard is already running
if lsof -i :8003 > /dev/null 2>&1; then
    echo "⚠️  Port 8003 is already in use. Please stop any running dashboard services."
    exit 1
fi

# Start the test dashboard server in background
echo "🔧 Starting test dashboard server..."
uv run python -m uvicorn tests.dashboard.dashboard_test_app:create_test_app \
    --factory --host 127.0.0.1 --port 8003 &
SERVER_PID=$!

# Function to cleanup on exit
cleanup() {
    echo "🛑 Cleaning up..."
    if [ -n "$SERVER_PID" ]; then
        kill $SERVER_PID 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Wait for server to be ready
echo "⏳ Waiting for server to start..."
for i in {1..20}; do
    if curl -s http://127.0.0.1:8003/api/metrics > /dev/null 2>&1; then
        echo "✅ Server is ready!"
        break
    fi
    if [ $i -eq 20 ]; then
        echo "❌ Server failed to start"
        exit 1
    fi
    sleep 0.5
done

# Run the E2E tests
echo "🧪 Running E2E tests..."
# Note: Playwright runs headless by default in CI (when CI env var is set)
uv run pytest tests/dashboard/test_dashboard_ui.py -v -m e2e --browser chromium

echo "✅ E2E tests completed!"

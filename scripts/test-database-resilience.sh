#!/bin/bash

# Test script for database resilience during maintenance windows
# This script simulates database outages to verify the resilience features

set -e

echo "🧪 Database Resilience Test Script"
echo "=================================="
echo ""
echo "This script will simulate database outages to test resilience features."
echo "Make sure all services are running before starting."
echo ""
read -p "Press Enter to continue or Ctrl+C to cancel..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to check service health
check_health() {
    local service=$1
    local port=$2
    local url="http://localhost:${port}/health"

    if curl -s "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ ${service} is healthy${NC}"
        return 0
    else
        echo -e "${RED}❌ ${service} is not responding${NC}"
        return 1
    fi
}

# Function to count messages in RabbitMQ queue
get_queue_depth() {
    local queue=$1
    local depth
    depth=$(docker exec discogsography-rabbitmq-1 rabbitmqctl list_queues name messages | grep "$queue" | awk '{print $2}' 2>/dev/null || echo "0")
    echo "$depth"
}

# Function to simulate database outage
simulate_outage() {
    local service=$1
    local duration=$2

    echo -e "\n${YELLOW}🔌 Stopping ${service} for ${duration} seconds...${NC}"
    docker compose stop "$service"

    echo -e "${BLUE}⏳ Waiting ${duration} seconds...${NC}"
    sleep "$duration"

    echo -e "${GREEN}🔄 Restarting ${service}...${NC}"
    docker compose start "$service"

    # Wait for service to be ready
    echo -e "${BLUE}⏳ Waiting for ${service} to be ready...${NC}"
    sleep 10
}

# Function to monitor service logs
monitor_logs() {
    local service=$1
    local duration=$2

    echo -e "\n${BLUE}📋 Monitoring ${service} logs for ${duration} seconds...${NC}"
    timeout "$duration" docker compose logs -f "$service" 2>&1 | grep -E "(Circuit breaker|Retrying|connection|Connection|Failed|failed|established|resilient)" || true
}

# Initial health check
echo -e "\n${BLUE}🏥 Initial Health Check${NC}"
echo "========================"
check_health "Extractor" 8000
check_health "Graphinator" 8001
check_health "Tableinator" 8002
check_health "Dashboard" 8003
check_health "Discovery" 8004

# Get initial queue depths
echo -e "\n${BLUE}📊 Initial Queue Depths${NC}"
echo "======================="
for data_type in artists labels masters releases; do
    graphinator_queue="graphinator-${data_type}"
    tableinator_queue="tableinator-${data_type}"

    g_depth=$(get_queue_depth "$graphinator_queue")
    t_depth=$(get_queue_depth "$tableinator_queue")

    echo "Queue ${data_type}: graphinator=${g_depth:-0}, tableinator=${t_depth:-0}"
done

# Test 1: Neo4j Outage
echo -e "\n${YELLOW}🧪 Test 1: Neo4j Outage (30 seconds)${NC}"
echo "====================================="
echo "Simulating Neo4j maintenance window..."

# Start monitoring graphinator in background
monitor_logs "graphinator" 60 &
MONITOR_PID=$!

# Simulate outage
simulate_outage "neo4j" 30

# Kill monitor
kill $MONITOR_PID 2>/dev/null || true

# Check recovery
echo -e "\n${BLUE}🔍 Checking Neo4j Recovery${NC}"
sleep 5
check_health "Graphinator" 8001

# Test 2: PostgreSQL Outage
echo -e "\n${YELLOW}🧪 Test 2: PostgreSQL Outage (30 seconds)${NC}"
echo "=========================================="
echo "Simulating PostgreSQL maintenance window..."

# Start monitoring tableinator in background
monitor_logs "tableinator" 60 &
MONITOR_PID=$!

# Simulate outage
simulate_outage "postgres" 30

# Kill monitor
kill $MONITOR_PID 2>/dev/null || true

# Check recovery
echo -e "\n${BLUE}🔍 Checking PostgreSQL Recovery${NC}"
sleep 5
check_health "Tableinator" 8002

# Test 3: RabbitMQ Outage (More Critical)
echo -e "\n${YELLOW}🧪 Test 3: RabbitMQ Outage (20 seconds)${NC}"
echo "========================================"
echo "Simulating RabbitMQ maintenance window..."
echo -e "${RED}⚠️  This is more disruptive as it affects message flow${NC}"

# Start monitoring all services
for service in extractor graphinator tableinator; do
    monitor_logs "$service" 50 &
done

# Simulate outage
simulate_outage "rabbitmq" 20

# Wait for monitors to finish
sleep 30

# Check recovery
echo -e "\n${BLUE}🔍 Checking RabbitMQ Recovery${NC}"
sleep 10
check_health "Extractor" 8000
check_health "Graphinator" 8001
check_health "Tableinator" 8002

# Final health check
echo -e "\n${BLUE}🏥 Final Health Check${NC}"
echo "====================="
check_health "Extractor" 8000
check_health "Graphinator" 8001
check_health "Tableinator" 8002
check_health "Dashboard" 8003
check_health "Discovery" 8004

# Final queue check
echo -e "\n${BLUE}📊 Final Queue Depths${NC}"
echo "===================="
for data_type in artists labels masters releases; do
    graphinator_queue="graphinator-${data_type}"
    tableinator_queue="tableinator-${data_type}"

    g_depth=$(get_queue_depth "$graphinator_queue")
    t_depth=$(get_queue_depth "$tableinator_queue")

    echo "Queue ${data_type}: graphinator=${g_depth:-0}, tableinator=${t_depth:-0}"
done

echo -e "\n${GREEN}✅ Resilience tests completed!${NC}"
echo ""
echo "Review the logs above to verify:"
echo "1. Circuit breakers activated during outages"
echo "2. Services attempted reconnection with exponential backoff"
echo "3. Services recovered after databases restarted"
echo "4. No messages were lost (check queue depths)"
echo ""
echo "For more detailed analysis, check individual service logs:"
echo "  docker compose logs graphinator | grep -i circuit"
echo "  docker compose logs tableinator | grep -i retry"
echo "  docker compose logs extractor | grep -i connection"

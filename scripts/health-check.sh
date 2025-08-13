#!/bin/bash

# Health check script for PR Check Agent
# Usage: ./scripts/health-check.sh [--detailed]

set -e

# Configuration
AGENT_URL="${AGENT_URL:-http://localhost:8080}"
REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
TIMEOUT=10
DETAILED=false

# Parse arguments
if [ "$1" = "--detailed" ]; then
    DETAILED=true
fi

echo "🏥 PR Check Agent Health Check"
echo "==============================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check HTTP endpoint
check_http() {
    local url=$1
    local name=$2
    
    if curl -sf --max-time $TIMEOUT "$url" > /dev/null 2>&1; then
        echo -e "✅ $name: ${GREEN}OK${NC}"
        return 0
    else
        echo -e "❌ $name: ${RED}FAILED${NC}"
        return 1
    fi
}

# Function to check Redis
check_redis() {
    local redis_host=$(echo "$REDIS_URL" | sed -n 's|redis://\([^:]*\):.*|\1|p')
    local redis_port=$(echo "$REDIS_URL" | sed -n 's|redis://[^:]*:\([0-9]*\)/.*|\1|p')
    
    redis_host=${redis_host:-localhost}
    redis_port=${redis_port:-6379}
    
    if command -v redis-cli &> /dev/null; then
        if redis-cli -h "$redis_host" -p "$redis_port" ping > /dev/null 2>&1; then
            echo -e "✅ Redis: ${GREEN}OK${NC}"
            return 0
        else
            echo -e "❌ Redis: ${RED}FAILED${NC}"
            return 1
        fi
    else
        echo -e "⚠️ Redis: ${YELLOW}redis-cli not available${NC}"
        return 1
    fi
}

# Main health checks
HEALTH_STATUS=0

echo "🔍 Basic Health Checks:"
echo "-----------------------"

# Check agent health endpoint
if ! check_http "$AGENT_URL/health" "Agent Health"; then
    HEALTH_STATUS=1
fi

# Check metrics endpoint
if ! check_http "$AGENT_URL/metrics" "Metrics"; then
    HEALTH_STATUS=1
fi

# Check Redis
if ! check_redis; then
    HEALTH_STATUS=1
fi

# Detailed checks if requested
if [ "$DETAILED" = true ]; then
    echo ""
    echo "📊 Detailed Information:"
    echo "------------------------"
    
    # Agent version and status
    if curl -sf --max-time $TIMEOUT "$AGENT_URL/health" | python3 -m json.tool 2>/dev/null; then
        echo ""
    fi
    
    # Redis info
    if command -v redis-cli &> /dev/null; then
        echo "Redis Info:"
        redis_host=$(echo "$REDIS_URL" | sed -n 's|redis://\([^:]*\):.*|\1|p')
        redis_port=$(echo "$REDIS_URL" | sed -n 's|redis://[^:]*:\([0-9]*\)/.*|\1|p')
        redis_host=${redis_host:-localhost}
        redis_port=${redis_port:-6379}
        
        redis-cli -h "$redis_host" -p "$redis_port" info server | grep -E "redis_version|uptime_in_seconds" || true
        echo ""
    fi
    
    # System resources
    echo "System Resources:"
    echo "Memory: $(free -h | grep '^Mem:' | awk '{print $3 "/" $2}')"
    echo "Disk: $(df -h . | tail -1 | awk '{print $3 "/" $2 " (" $5 " used)"}')"
    echo ""
fi

echo "==============================="
if [ $HEALTH_STATUS -eq 0 ]; then
    echo -e "🎉 Overall Status: ${GREEN}HEALTHY${NC}"
    exit 0
else
    echo -e "⚠️ Overall Status: ${RED}UNHEALTHY${NC}"
    exit 1
fi
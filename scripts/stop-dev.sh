#!/bin/bash

# Script to stop development environment

set -e

echo "🛑 Stopping development environment..."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Stop backend and frontend if PIDs exist
if [ -f ".backend.pid" ]; then
    BACKEND_PID=$(cat .backend.pid)
    if ps -p $BACKEND_PID > /dev/null 2>&1; then
        echo -e "${YELLOW}Stopping backend (PID: $BACKEND_PID)...${NC}"
        kill $BACKEND_PID 2>/dev/null || true
    fi
    rm .backend.pid
fi

if [ -f ".frontend.pid" ]; then
    FRONTEND_PID=$(cat .frontend.pid)
    if ps -p $FRONTEND_PID > /dev/null 2>&1; then
        echo -e "${YELLOW}Stopping frontend (PID: $FRONTEND_PID)...${NC}"
        kill $FRONTEND_PID 2>/dev/null || true
    fi
    rm .frontend.pid
fi

# Stop Docker containers
echo -e "${YELLOW}Stopping Docker containers...${NC}"
if [ -d "backend/docker" ]; then
    cd backend/docker
    docker-compose stop postgres redis 2>/dev/null || true
    cd ../..
fi

echo -e "${GREEN}✅ All services stopped${NC}"


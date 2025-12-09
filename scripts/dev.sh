#!/bin/bash

# Script master de desenvolvimento - inicia frontend e backend

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Starting development environment...${NC}"
echo ""

# Verificar se estamos na raiz do projeto
if [ ! -d "frontend" ] || [ ! -d "backend" ]; then
    echo -e "${RED}❌ Por favor, execute este script da raiz do projeto${NC}"
    exit 1
fi

# Verificar se Docker está rodando
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker não está rodando. Por favor, inicie o Docker primeiro.${NC}"
    exit 1
fi

# Iniciar dependências (PostgreSQL e Redis)
echo -e "${YELLOW}🐳 Starting PostgreSQL and Redis...${NC}"
cd backend/docker
docker-compose up -d postgres redis
cd ../..

# Aguardar dependências
echo -e "${YELLOW}⏳ Waiting for dependencies...${NC}"
sleep 5

# Verificar se dependências estão prontas
until docker exec ai_saas_postgres pg_isready -U postgres > /dev/null 2>&1; do
    echo "Waiting for PostgreSQL..."
    sleep 2
done

until docker exec ai_saas_redis redis-cli ping > /dev/null 2>&1; do
    echo "Waiting for Redis..."
    sleep 2
done

echo -e "${GREEN}✅ Dependencies are ready${NC}"

# Iniciar backend em background
echo -e "${YELLOW}🔧 Starting backend...${NC}"
cd backend
./scripts/dev.sh > ../backend.log 2>&1 &
BACKEND_PID=$!
cd ..

# Aguardar backend iniciar
sleep 3

# Iniciar frontend em background
echo -e "${YELLOW}🎨 Starting frontend...${NC}"
cd frontend
./scripts/dev.sh > ../frontend.log 2>&1 &
FRONTEND_PID=$!
cd ..

# Salvar PIDs
echo "$BACKEND_PID" > .backend.pid
echo "$FRONTEND_PID" > .frontend.pid

echo ""
echo -e "${GREEN}✨ Development environment is running!${NC}"
echo ""
echo "📊 Services:"
echo "  - Frontend:  http://localhost:3000"
echo "  - Backend:   http://localhost:8000"
echo "  - API Docs:  http://localhost:8000/docs"
echo ""
echo "📝 Logs:"
echo "  - Backend:   tail -f backend.log"
echo "  - Frontend:  tail -f frontend.log"
echo ""
echo "🛑 To stop, run: ./scripts/stop-dev.sh"
echo "   Or press Ctrl+C"
echo ""

# Aguardar interrupção
trap "echo ''; echo '🛑 Stopping services...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; cd backend/docker && docker-compose stop postgres redis && cd ../..; rm -f .backend.pid .frontend.pid; exit" INT TERM

wait


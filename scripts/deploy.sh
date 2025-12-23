#!/bin/bash

# Script de deploy do backend

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🔧 Deploying backend...${NC}"

# Verificar se estamos no diretório correto
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}❌ Por favor, execute este script do diretório backend/${NC}"
    exit 1
fi

# Verificar se Docker está rodando
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker não está rodando. Por favor, inicie o Docker primeiro.${NC}"
    exit 1
fi

# Verificar se .env existe
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo -e "${YELLOW}⚠️  Arquivo .env não encontrado. Copiando de .env.example...${NC}"
        cp .env.example .env
        echo -e "${YELLOW}⚠️  IMPORTANTE: Edite .env com suas configurações!${NC}"
    else
        echo -e "${RED}❌ Arquivo .env não encontrado e .env.example não existe.${NC}"
        exit 1
    fi
fi

# Build das imagens
echo -e "${YELLOW}🔨 Building Docker images...${NC}"
docker-compose -f docker/docker-compose.yml build

# Parar containers existentes
echo -e "${YELLOW}🛑 Stopping existing containers...${NC}"
docker-compose -f docker/docker-compose.yml down

# Iniciar dependências (postgres, redis)
echo -e "${YELLOW}🚀 Starting dependencies (PostgreSQL, Redis)...${NC}"
docker-compose -f docker/docker-compose.yml up -d postgres redis

# Aguardar dependências estarem prontas
echo -e "${YELLOW}⏳ Waiting for dependencies to be ready...${NC}"
sleep 5

# Executar migrations
echo -e "${YELLOW}📦 Running database migrations...${NC}"
docker-compose -f docker/docker-compose.yml run --rm backend alembic upgrade head || echo "⚠️  Migrations may have failed, but continuing..."

# Iniciar todos os serviços
echo -e "${YELLOW}🚀 Starting all services...${NC}"
docker-compose -f docker/docker-compose.yml up -d

echo -e "${GREEN}✅ Backend deployed successfully!${NC}"
echo ""
echo "📊 Services:"
echo "  - Backend API:  http://localhost:${BACKEND_PORT:-8000}"
echo "  - API Docs:     http://localhost:${BACKEND_PORT:-8000}/docs"
echo "  - PostgreSQL:   localhost:5432"
echo "  - Redis:        localhost:6379"
echo ""
echo "📝 Comandos úteis:"
echo "  - Ver logs:     docker-compose -f docker/docker-compose.yml logs -f"
echo "  - Parar:        docker-compose -f docker/docker-compose.yml down"
echo "  - Reiniciar:    docker-compose -f docker/docker-compose.yml restart"
echo ""


#!/bin/bash

# Script master de deploy - orquestra frontend e backend

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Starting full deployment...${NC}"
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

# Verificar se .env existe em deploy/
if [ ! -f "deploy/.env" ]; then
    if [ -f "deploy/.env.example" ]; then
        echo -e "${YELLOW}⚠️  Arquivo deploy/.env não encontrado. Copiando de deploy/.env.example...${NC}"
        cp deploy/.env.example deploy/.env
        echo -e "${RED}⚠️  IMPORTANTE: Edite deploy/.env com suas configurações antes de continuar!${NC}"
        echo -e "${RED}⚠️  Especialmente as senhas e chaves secretas!${NC}"
        exit 1
    else
        echo -e "${RED}❌ Arquivo deploy/.env.example não encontrado.${NC}"
        exit 1
    fi
fi

# Verificar se as chaves secretas foram alteradas
if grep -q "CHANGE_THIS" deploy/.env; then
    echo -e "${RED}❌ Por favor, altere as senhas e chaves secretas no deploy/.env!${NC}"
    echo -e "${YELLOW}   Procure por 'CHANGE_THIS' no arquivo.${NC}"
    exit 1
fi

# Carregar variáveis de ambiente
export $(cat deploy/.env | grep -v '^#' | xargs)

# Deploy usando docker-compose completo
echo -e "${YELLOW}🔨 Building all Docker images...${NC}"
cd deploy
docker-compose build

# Parar containers existentes
echo -e "${YELLOW}🛑 Stopping existing containers...${NC}"
docker-compose down

# Iniciar serviços
echo -e "${YELLOW}🚀 Starting all services...${NC}"
docker-compose up -d

# Aguardar serviços iniciarem
echo -e "${YELLOW}⏳ Waiting for services to start...${NC}"
sleep 10

# Verificar saúde dos serviços
echo -e "${YELLOW}🏥 Checking service health...${NC}"

# Verificar PostgreSQL
if docker exec ai_saas_postgres_prod pg_isready -U ${POSTGRES_USER:-postgres} > /dev/null 2>&1; then
    echo -e "${GREEN}✅ PostgreSQL is running${NC}"
else
    echo -e "${RED}❌ PostgreSQL is not responding${NC}"
fi

# Verificar Redis
if docker exec ai_saas_redis_prod redis-cli --raw incr ping > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Redis is running${NC}"
else
    echo -e "${RED}❌ Redis is not responding${NC}"
fi

# Verificar Backend
sleep 5
if curl -s http://localhost:${BACKEND_PORT:-8000}/health > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Backend is running${NC}"
else
    echo -e "${YELLOW}⚠️  Backend may still be starting...${NC}"
fi

# Verificar Frontend
sleep 5
if curl -s http://localhost:${FRONTEND_PORT:-3000} > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Frontend is running${NC}"
else
    echo -e "${YELLOW}⚠️  Frontend may still be starting...${NC}"
fi

cd ..

echo ""
echo -e "${GREEN}✨ Deployment completed!${NC}"
echo ""
echo "📊 Services:"
echo "  - Frontend:  http://localhost:${FRONTEND_PORT:-3000}"
echo "  - Backend:   http://localhost:${BACKEND_PORT:-8000}"
echo "  - API Docs:  http://localhost:${BACKEND_PORT:-8000}/docs"
echo ""
echo "📝 Comandos úteis:"
echo "  - Ver logs:     cd deploy && docker-compose logs -f"
echo "  - Ver status:   cd deploy && docker-compose ps"
echo "  - Parar:        cd deploy && docker-compose down"
echo "  - Reiniciar:    cd deploy && docker-compose restart"
echo ""

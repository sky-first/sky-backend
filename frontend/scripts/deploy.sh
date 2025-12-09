#!/bin/bash

# Script de deploy do frontend

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🎨 Deploying frontend...${NC}"

# Verificar se estamos no diretório correto
if [ ! -f "package.json" ]; then
    echo -e "${RED}❌ Por favor, execute este script do diretório frontend/${NC}"
    exit 1
fi

# Verificar se Docker está rodando
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker não está rodando. Por favor, inicie o Docker primeiro.${NC}"
    exit 1
fi

# Build da imagem
echo -e "${YELLOW}🔨 Building Docker image...${NC}"
docker-compose -f docker/docker-compose.yml build

# Parar container existente
echo -e "${YELLOW}🛑 Stopping existing container...${NC}"
docker-compose -f docker/docker-compose.yml down

# Iniciar container
echo -e "${YELLOW}🚀 Starting frontend container...${NC}"
docker-compose -f docker/docker-compose.yml up -d

echo -e "${GREEN}✅ Frontend deployed successfully!${NC}"
echo ""
echo "📊 Frontend running at: http://localhost:${FRONTEND_PORT:-3000}"
echo ""
echo "📝 Comandos úteis:"
echo "  - Ver logs:     docker-compose -f docker/docker-compose.yml logs -f"
echo "  - Parar:        docker-compose -f docker/docker-compose.yml down"
echo "  - Reiniciar:    docker-compose -f docker/docker-compose.yml restart"
echo ""


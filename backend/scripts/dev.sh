#!/bin/bash

# Script de desenvolvimento do backend

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🔧 Starting backend development environment...${NC}"

# Verificar se estamos no diretório correto
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}❌ Por favor, execute este script do diretório backend/${NC}"
    exit 1
fi

# Verificar se .env existe
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo -e "${YELLOW}⚠️  Arquivo .env não encontrado. Copiando de .env.example...${NC}"
        cp .env.example .env
        echo -e "${YELLOW}⚠️  IMPORTANTE: Edite .env com suas configurações!${NC}"
    fi
fi

# Carregar variáveis de ambiente
if [ -f ".env" ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Verificar se venv existe
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}📦 Creating Python virtual environment...${NC}"
    python3 -m venv venv
fi

# Ativar venv
source venv/bin/activate

# Instalar dependências se necessário
if [ ! -f ".deps-installed" ]; then
    echo -e "${YELLOW}📦 Installing Python dependencies...${NC}"
    pip install -r requirements.txt
    touch .deps-installed
fi

# Iniciar dependências com Docker (se não estiverem rodando)
if ! docker ps | grep -q ai_saas_postgres; then
    echo -e "${YELLOW}🐳 Starting PostgreSQL and Redis with Docker...${NC}"
    docker-compose -f docker/docker-compose.yml up -d postgres redis
    sleep 5
fi

# Executar migrations
echo -e "${YELLOW}📦 Running database migrations...${NC}"
alembic upgrade head || echo "⚠️  Migrations may have failed, but continuing..."

# Criar usuário de teste se não existir
echo -e "${YELLOW}👤 Checking test user...${NC}"
python scripts/create-test-user.py || echo "⚠️  Test user creation skipped"

# Iniciar servidor de desenvolvimento
echo -e "${GREEN}🚀 Starting FastAPI development server...${NC}"
echo ""
echo "📊 Backend running at: http://localhost:${BACKEND_PORT:-8000}"
echo "📚 API Docs at: http://localhost:${BACKEND_PORT:-8000}/docs"
echo ""
uvicorn src.main:app --reload --host 0.0.0.0 --port ${BACKEND_PORT:-8000}


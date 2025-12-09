#!/bin/bash

# Script para rodar o backend localmente
# Uso: ./run-local.sh

set -e

# Cores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Starting backend locally...${NC}"

# Verificar se estamos na pasta backend
if [ ! -f "requirements.txt" ]; then
    echo -e "${YELLOW}⚠️  Por favor, execute este script da pasta backend/${NC}"
    exit 1
fi

# Carregar variáveis de ambiente do .env na pasta deploy
if [ -f "../deploy/.env" ]; then
    echo -e "${GREEN}📝 Loading environment variables from ../deploy/.env${NC}"
    export $(cat ../deploy/.env | grep -v '^#' | xargs)
else
    echo -e "${YELLOW}⚠️  Arquivo ../deploy/.env não encontrado. Usando variáveis padrão.${NC}"
fi

# Verificar se venv existe e ativar
if [ -d "venv" ]; then
    echo -e "${GREEN}🐍 Activating virtual environment...${NC}"
    source venv/bin/activate
else
    echo -e "${YELLOW}⚠️  Virtual environment não encontrado. Usando Python global.${NC}"
fi

# Rodar uvicorn
echo -e "${GREEN}🚀 Starting uvicorn...${NC}"
echo ""
echo "📊 Backend: http://localhost:8000"
echo "📚 API Docs: http://localhost:8000/docs"
echo ""
echo "Pressione Ctrl+C para parar"
echo ""

uvicorn src.main:app --reload --host 0.0.0.0 --port 8000


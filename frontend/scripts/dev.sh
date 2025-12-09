#!/bin/bash

# Script de desenvolvimento do frontend

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🎨 Starting frontend development server...${NC}"

# Verificar se estamos no diretório correto
if [ ! -f "package.json" ]; then
    echo -e "${RED}❌ Por favor, execute este script do diretório frontend/${NC}"
    exit 1
fi

# Verificar se node_modules existe
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}📦 Installing dependencies...${NC}"
    npm install
fi

# Iniciar servidor de desenvolvimento
echo -e "${GREEN}🚀 Starting Next.js dev server...${NC}"
npm run dev


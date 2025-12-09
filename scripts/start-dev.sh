#!/bin/bash

# Script para iniciar ambiente de desenvolvimento completo
# Este script inicia PostgreSQL, Redis, Backend e Frontend

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Starting development environment...${NC}"

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

echo -e "${YELLOW}🐳 Starting PostgreSQL and Redis with Docker...${NC}"
cd backend/docker
docker-compose up -d postgres redis
cd ../..

# Aguardar PostgreSQL estar pronto
echo -e "${YELLOW}⏳ Waiting for PostgreSQL to be ready...${NC}"
sleep 5

until docker exec ai_saas_postgres pg_isready -U postgres > /dev/null 2>&1; do
    echo "Waiting for PostgreSQL..."
    sleep 2
done

echo -e "${GREEN}✅ PostgreSQL is ready${NC}"

# Verificar Redis
until docker exec ai_saas_redis redis-cli ping > /dev/null 2>&1; do
    echo "Waiting for Redis..."
    sleep 2
done

echo -e "${GREEN}✅ Redis is ready${NC}"

# Setup backend
echo -e "${YELLOW}🔧 Setting up backend...${NC}"
cd backend

# Criar virtual environment se não existir
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

# Ativar virtual environment
source venv/bin/activate

# Instalar dependências
if [ ! -f ".deps-installed" ]; then
    echo "Installing Python dependencies..."
    pip install -r requirements.txt
    touch .deps-installed
fi

# Configurar variáveis de ambiente
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db"
export REDIS_URL="redis://localhost:6379/0"
export JWT_SECRET_KEY="dev-secret-key-change-in-production"
export ENCRYPTION_KEY="dev-encryption-key-32-bytes-long!!"
export DEBUG=true

# Executar migrations
echo "Running database migrations..."
alembic upgrade head || echo "⚠️  Migrations may have failed, but continuing..."

# Criar usuário de teste
echo "Creating test user..."
python scripts/create-test-user.py || echo "⚠️  Test user creation may have failed, but continuing..."

cd ..

# Iniciar backend em background
echo -e "${YELLOW}🔧 Starting backend server...${NC}"
cd backend
source venv/bin/activate
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db"
export REDIS_URL="redis://localhost:6379/0"
export JWT_SECRET_KEY="dev-secret-key-change-in-production"
export ENCRYPTION_KEY="dev-encryption-key-32-bytes-long!!"
export DEBUG=true
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000 > ../backend.log 2>&1 &
BACKEND_PID=$!
cd ..

# Aguardar backend estar pronto
echo -e "${YELLOW}⏳ Waiting for backend to be ready...${NC}"
sleep 3

until curl -s http://localhost:8000/health > /dev/null 2>&1; do
    echo "Waiting for backend..."
    sleep 2
done

echo -e "${GREEN}✅ Backend is ready at http://localhost:8000${NC}"

# Iniciar frontend
echo -e "${YELLOW}🎨 Starting frontend...${NC}"
cd frontend

# Instalar dependências se necessário
if [ ! -d "node_modules" ]; then
    echo "Installing Node.js dependencies..."
    npm install
fi

npm run dev > ../frontend.log 2>&1 &
FRONTEND_PID=$!

cd ..

# Aguardar frontend estar pronto
echo -e "${YELLOW}⏳ Waiting for frontend to be ready...${NC}"
sleep 5

echo -e "${GREEN}✅ Frontend is ready at http://localhost:3000${NC}"

echo ""
echo -e "${GREEN}✨ Development environment is running!${NC}"
echo ""
echo "📊 Services:"
echo "  - Frontend:  http://localhost:3000"
echo "  - Backend:   http://localhost:8000"
echo "  - API Docs:  http://localhost:8000/docs"
echo "  - PostgreSQL: localhost:5432"
echo "  - Redis:     localhost:6379"
echo ""
echo "🔐 Test Credentials:"
echo "  - Email:     test@example.com"
echo "  - Password:  test123"
echo ""
echo "📝 Logs:"
echo "  - Backend:   tail -f backend.log"
echo "  - Frontend:  tail -f frontend.log"
echo ""
echo "🛑 To stop all services, run: ./scripts/stop-dev.sh"
echo "   Or press Ctrl+C and run: kill $BACKEND_PID $FRONTEND_PID"
echo ""

# Salvar PIDs
echo "$BACKEND_PID" > .backend.pid
echo "$FRONTEND_PID" > .frontend.pid

# Aguardar interrupção
trap "echo ''; echo '🛑 Stopping services...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; cd backend/docker && docker-compose stop postgres redis && cd ../..; rm -f .backend.pid .frontend.pid; exit" INT TERM

wait

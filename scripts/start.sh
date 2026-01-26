#!/bin/bash

# Script para rodar o Backend com uvicorn
# Uso: ./scripts/start.sh

set -e

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🚀 Iniciando Backend na porta 8000..."

cd "$BACKEND_DIR"

# Verifica se o ambiente virtual existe
if [ ! -d "venv" ] && [ ! -d ".venv" ]; then
    echo "⚠️  Ambiente virtual não encontrado. Criando..."
    python3 -m venv venv
fi

# Ativa o ambiente virtual
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Instala dependências se necessário
if [ ! -f ".deps_installed" ]; then
    echo "📦 Instalando dependências..."
    if [ -d "venv" ]; then
        venv/bin/pip install -q -r requirements.txt
    elif [ -d ".venv" ]; then
        .venv/bin/pip install -q -r requirements.txt
    else
        pip install -q -r requirements.txt
    fi
    touch .deps_installed
fi

# Configura variáveis de ambiente
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://localhost:6379/1}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://localhost:6379/2}"
export AI_SERVICE_URL="${AI_SERVICE_URL:-http://localhost:8001}"

echo "✅ Variáveis de ambiente configuradas"
echo "   DATABASE_URL: $DATABASE_URL"
echo "   REDIS_URL: $REDIS_URL"
echo "   AI_SERVICE_URL: $AI_SERVICE_URL"
echo ""

# Verifica se infraestrutura está rodando
if ! docker ps | grep -q sky_poc_postgres; then
    echo "⚠️  Infraestrutura não está rodando."
    echo "   Execute: cd ../../deploy && ./start.sh"
    echo "   Continuando..."
fi

# Executa migrações
echo "🔄 Executando migrações do banco de dados..."
if [ -d "venv" ]; then
    venv/bin/python -m alembic upgrade head
elif [ -d ".venv" ]; then
    .venv/bin/python -m alembic upgrade head
else
    python3 -m alembic upgrade head
fi
echo ""

# Seed role permissions (RBAC)
echo "🌱 Populando permissões de roles (RBAC)..."
if [ -d "venv" ]; then
    venv/bin/python scripts/seed_role_permissions.py
elif [ -d ".venv" ]; then
    .venv/bin/python scripts/seed_role_permissions.py
else
    python3 scripts/seed_role_permissions.py
fi
echo ""

# Cria usuário de teste
echo "👤 Verificando/Criando usuário de teste..."
if [ -d "venv" ]; then
    venv/bin/python create_user.py
elif [ -d ".venv" ]; then
    .venv/bin/python create_user.py
else
    python3 create_user.py
fi
echo ""

# Roda o uvicorn
echo "🌐 Iniciando servidor na porta 8000..."
if [ -d "venv" ]; then
    venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
elif [ -d ".venv" ]; then
    .venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
else
    python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
fi


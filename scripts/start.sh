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
# Sempre verifica e instala dependências para garantir ambiente atualizado
echo "📦 Verificando dependências..."
if [ -d "venv" ]; then
    venv/bin/pip install -q -r requirements.txt
elif [ -d ".venv" ]; then
    .venv/bin/pip install -q -r requirements.txt
else
    pip install -q -r requirements.txt
fi

# Configura variáveis de ambiente
# Carrega .env.local primeiro (pydantic-settings usa, mas alembic roda no shell e precisa de env vars exportadas)
if [ -f ".env.local" ]; then
    set -a
    # shellcheck disable=SC1091
    source .env.local
    set +a
fi
# sky_poc_postgres está exposto em 5432 no host (mapeamento definido em deploy/docker-compose.yml)
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://localhost:6379/1}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://localhost:6379/2}"
export AI_SERVICE_URL="${AI_SERVICE_URL:-http://localhost:8001}"

# Cache Warming settings
export CACHE_WARMING_ENABLED="${CACHE_WARMING_ENABLED:-false}"
export CACHE_WARMING_INTERVAL_SECONDS="${CACHE_WARMING_INTERVAL_SECONDS:-60}"

echo "✅ Variáveis de ambiente configuradas"
echo "   DATABASE_URL: $DATABASE_URL"
echo "   REDIS_URL: $REDIS_URL"
echo "   AI_SERVICE_URL: $AI_SERVICE_URL"
echo "   CACHE_WARMING: $CACHE_WARMING_ENABLED (Interval: ${CACHE_WARMING_INTERVAL_SECONDS}s)"
echo ""

# Verifica se infraestrutura está rodando
if ! docker ps | grep -q sky_poc_postgres; then
    echo "⚠️  Infraestrutura não está rodando."
    echo "   Execute: cd ../../deploy && ./start.sh"
    echo "   Continuando..."
fi

# Função para limpar processos em background ao sair
cleanup() {
    echo ""
    echo "🛑 Desligando Celery Worker e Beat..."
    if [ ! -z "$WORKER_PID" ]; then kill $WORKER_PID 2>/dev/null || true; fi
    if [ ! -z "$BEAT_PID" ]; then kill $BEAT_PID 2>/dev/null || true; fi
    echo "✅ Processos encerrados."
}

# Trap para capturar interrupção (Ctrl+C) e encerrar processos filhos
trap cleanup EXIT

# Executa migrações
echo "🔄 Executando migrações do banco de dados..."
ALEMBIC_CMD="python3 -m alembic"
if [ -d "venv" ]; then
    ALEMBIC_CMD="venv/bin/python -m alembic"
elif [ -d ".venv" ]; then
    ALEMBIC_CMD=".venv/bin/python -m alembic"
fi

if ! $ALEMBIC_CMD upgrade head; then
    echo "⚠️  Falha nas migrações. Verificando se há revisões órfãs..."
    # Se o erro for "Can't locate revision", a tabela alembic_version aponta
    # para uma migration que não existe nesta checkout — tipicamente quando
    # mudas de branch e a branch antiga tinha uma migration que esta não tem.
    UPGRADE_ERR=$($ALEMBIC_CMD upgrade head 2>&1 || true)
    if echo "$UPGRADE_ERR" | grep -q "Can't locate revision"; then
        ORPHAN_REV=$(echo "$UPGRADE_ERR" | grep -oE "identified by '[^']+'" | head -1 | sed -E "s/identified by '(.+)'/\1/")
        echo "💡 Detectada revisão órfã '$ORPHAN_REV' (provavelmente de outra branch)."
        echo "🔧 Limpando alembic_version e re-stampando com a head válida..."
        # 1. Apaga a row órfã via Python+SQLAlchemy (usa a mesma DATABASE_URL
        #    que o resto do app, sem precisar de psql instalado).
        # 2. Roda stamp <head> para gravar a head conhecida desta checkout.
        # 3. Roda upgrade head para garantir que nada está em falta (no-op
        #    se já estiver no head).
        if [ -d "venv" ]; then PY="venv/bin/python"; elif [ -d ".venv" ]; then PY=".venv/bin/python"; else PY="python3"; fi
        $PY - <<'PYEOF'
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    if "asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    eng = create_async_engine(url)
    async with eng.begin() as c:
        await c.execute(text("DELETE FROM alembic_version"))
    await eng.dispose()
    print("   alembic_version cleared")

asyncio.run(main())
PYEOF
        # Now stamp & upgrade can run cleanly.
        HEAD_REV=$($ALEMBIC_CMD heads 2>/dev/null | awk '{print $1}' | head -1)
        if [ -z "$HEAD_REV" ]; then
            echo "❌ Não foi possível identificar a head conhecida. Aborto."
            exit 1
        fi
        if $ALEMBIC_CMD stamp "$HEAD_REV" && $ALEMBIC_CMD upgrade head; then
            echo "✅ Banco sincronizado (re-stampado em $HEAD_REV) e migrations aplicadas."
        else
            echo "❌ Não foi possível recuperar automaticamente. Verifique as migrações manualmente."
            exit 1
        fi
    else
        echo "❌ Falha crítica nas migrações. Por favor, verifique os logs acima."
        exit 1
    fi
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
    venv/bin/python scripts/create-test-user.py
elif [ -d ".venv" ]; then
    .venv/bin/python scripts/create-test-user.py
else
    python3 scripts/create-test-user.py
fi
echo ""

# Inicia Celery Worker (se habilitado)
if [ "$CACHE_WARMING_ENABLED" = "true" ]; then
    echo "⚙️ Iniciando Celery Worker em background..."
    if [ -d "venv" ]; then
        export PYTHONPATH=$PYTHONPATH:.
        venv/bin/celery -A src.workers.celery_app worker --loglevel=error -Q celery > /dev/null 2>&1 &
    else
        export PYTHONPATH=$PYTHONPATH:.
        celery -A src.workers.celery_app worker --loglevel=error -Q celery > /dev/null 2>&1 &
    fi
    WORKER_PID=$!
    
    echo "⏰ Iniciando Celery Beat em background..."
    if [ -d "venv" ]; then
        venv/bin/celery -A src.workers.celery_app beat --loglevel=error > /dev/null 2>&1 &
    else
        celery -A src.workers.celery_app beat --loglevel=error > /dev/null 2>&1 &
    fi
    BEAT_PID=$!
fi

# Roda o uvicorn
echo "🌐 Iniciando servidor na porta 8000..."
if [ -d "venv" ]; then
    venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
elif [ -d ".venv" ]; then
    .venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
else
    python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
fi


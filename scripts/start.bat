@echo off
setlocal

:: Script para rodar o Backend no Windows CMD
:: Uso: scripts\start.bat

echo 🚀 Iniciando Backend no Windows...

:: Caminho para o diretório raiz do backend
set BACKEND_DIR=%~dp0..
cd /d "%BACKEND_DIR%"

:: Verifica se o ambiente virtual existe
if not exist "venv" (
    echo ⚠️  Ambiente virtual não encontrado. Criando...
    python -m venv venv
)

:: Ativa o ambiente virtual
call venv\Scripts\activate

:: Instala/Verifica dependências
echo 📦 Verificando dependências...
pip install -q -r requirements.txt

:: Configura variáveis de ambiente (se não estiverem definidas)
if "%DATABASE_URL%"=="" set DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db
if "%REDIS_URL%"=="" set REDIS_URL=redis://localhost:6379/0
if "%CELERY_BROKER_URL%"=="" set CELERY_BROKER_URL=redis://localhost:6379/1
if "%CELERY_RESULT_BACKEND%"=="" set CELERY_RESULT_BACKEND=redis://localhost:6379/2
if "%AI_SERVICE_URL%"=="" set AI_SERVICE_URL=http://localhost:8001
if "%CACHE_WARMING_ENABLED%"=="" set CACHE_WARMING_ENABLED=false
if "%CACHE_WARMING_INTERVAL_SECONDS%"=="" set CACHE_WARMING_INTERVAL_SECONDS=60

:: Configura PYTHONPATH para incluir o diretório atual
set PYTHONPATH=%PYTHONPATH%;.

echo ✅ Variáveis de ambiente configuradas
echo    DATABASE_URL: %DATABASE_URL%
echo    AI_SERVICE_URL: %AI_SERVICE_URL%
echo.

:: Executa migrações
echo 🔄 Executando migrações do banco de dados...
python -m alembic upgrade head
if %ERRORLEVEL% neq 0 (
    echo ⚠️  Falha nas migrações. Tentando sincronizar com 'alembic stamp head'...
    python -m alembic stamp head
    python -m alembic upgrade head
)

:: Seed role permissions (RBAC)
echo 🌱 Populando permissões de roles (RBAC)...
python scripts/seed_role_permissions.py

:: Cria usuário de teste
echo 👤 Verificando/Criando usuário de teste...
python scripts/create-test-user.py
echo.

:: Inicia o uvicorn
echo 🌐 Iniciando servidor na porta 8000...
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

pause

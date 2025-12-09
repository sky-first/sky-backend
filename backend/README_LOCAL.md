# 🚀 Rodar Backend Localmente (Fora do Docker)

## Configuração

O arquivo `.env` na pasta `backend/` está configurado para:
- ✅ Usar **PostgreSQL** do container Docker (porta 5433)
- ✅ Usar **Redis** do container Docker (porta 6379)
- ✅ Desenvolvimento local com hot-reload

## Pré-requisitos

1. **Containers Docker rodando:**
   ```bash
   cd deploy
   docker-compose up -d postgres redis
   ```

2. **Verificar se estão rodando:**
   ```bash
   docker ps | grep -E "postgres|redis"
   ```

## Como Rodar

### Opção 1: Terminal

```bash
cd backend
source venv/bin/activate
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### Opção 2: VSCode Debugger

1. Selecione o interpretador: `./backend/venv/bin/python`
2. Vá em "Run and Debug" (F5)
3. Selecione "Python Debugger: FastAPI"
4. Clique em "Start Debugging"

## Configuração do .env

O arquivo `backend/.env` contém:
- `DATABASE_URL`: PostgreSQL do Docker (localhost:5433)
- `REDIS_URL`: Redis do Docker (localhost:6379)
- Todas as credenciais do `deploy/.env`

## Verificar se está funcionando

Após iniciar, acesse:
- **Health Check:** http://localhost:8000/health
- **API Docs:** http://localhost:8000/docs

## Notas Importantes

- O `.env` do backend **NÃO afeta** o Docker Compose
- O Docker Compose continua usando `deploy/.env`
- Você pode rodar backend local + Docker (postgres/redis) simultaneamente


# AI SaaS Dashboard - Monorepo

Plataforma completa de Business Intelligence com IA, organizada em monorepo com frontend e backend separados.

## 📁 Estrutura do Projeto

```
projeto-frontend-poc/
├── frontend/                    # Aplicação Next.js
│   ├── src/                    # Código fonte
│   ├── public/                 # Assets públicos
│   ├── docker/                  # Deploy do frontend
│   │   ├── Dockerfile
│   │   └── docker-compose.yml
│   ├── scripts/                 # Scripts do frontend
│   │   ├── deploy.sh
│   │   └── dev.sh
│   ├── package.json
│   └── .env.example
│
├── backend/                     # API FastAPI
│   ├── src/                    # Código fonte
│   ├── docker/                  # Deploy do backend
│   │   ├── Dockerfile
│   │   ├── Dockerfile.worker
│   │   └── docker-compose.yml
│   ├── scripts/                 # Scripts do backend
│   │   ├── deploy.sh
│   │   ├── dev.sh
│   │   ├── create-test-user.py
│   │   └── init-db.sh
│   └── .env.example
│
├── deploy/                      # Orquestração completa
│   ├── docker-compose.yml      # Orquestra tudo
│   └── .env.example
│
└── scripts/                     # Scripts master
    ├── deploy.sh               # Deploy completo
    ├── dev.sh                  # Desenvolvimento
    ├── start-dev.sh            # Início rápido
    ├── stop-dev.sh             # Parar serviços
    └── generate-secrets.sh     # Gerar chaves
```

## 🚀 Início Rápido

### Desenvolvimento

```bash
# Iniciar tudo (PostgreSQL, Redis, Backend, Frontend)
./scripts/start-dev.sh
```

Isso vai:
- ✅ Iniciar PostgreSQL e Redis via Docker
- ✅ Configurar backend (venv, dependências, migrations)
- ✅ Criar usuário de teste
- ✅ Iniciar backend na porta 8000
- ✅ Iniciar frontend na porta 3000

### Deploy em Produção

```bash
# 1. Gerar chaves secretas
./scripts/generate-secrets.sh

# 2. Configurar ambiente
cp deploy/.env.example deploy/.env
# Edite deploy/.env com suas configurações

# 3. Deploy
./scripts/deploy.sh
```

## 📚 Documentação

- **QUICK_START.md** - Guia rápido de início
- **DEPLOY.md** - Guia completo de deploy
- **TESTING_GUIDE.md** - Guia de testes
- **backend/README.md** - Documentação do backend
- **backend/ENDPOINTS_AI.md** - Endpoints de IA

## 🛠️ Desenvolvimento Individual

### Frontend

```bash
cd frontend
./scripts/dev.sh
```

### Backend

```bash
cd backend
./scripts/dev.sh
```

## 🐳 Deploy Individual

### Frontend

```bash
cd frontend
./scripts/deploy.sh
```

### Backend

```bash
cd backend
./scripts/deploy.sh
```

## 📊 Serviços

Após iniciar, acesse:

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 🔐 Credenciais de Teste

- **Email**: `test@example.com`
- **Password**: `test123`

## 🛑 Parar Serviços

```bash
./scripts/stop-dev.sh
```

## 📝 Tecnologias

### Frontend
- Next.js 16
- React 19
- TypeScript
- Tailwind CSS
- Zustand
- Radix UI

### Backend
- FastAPI
- Python 3.11
- PostgreSQL 14
- Redis 7
- Celery
- SQLAlchemy (async)

## 📖 Mais Informações

Consulte a documentação específica em cada pasta:
- `frontend/` - Documentação do frontend
- `backend/README.md` - Documentação completa do backend
- `deploy/` - Configurações de deploy

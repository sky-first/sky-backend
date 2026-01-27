# Backend - AI SaaS Dashboard

Backend completo da plataforma SaaS de Business Intelligence com IA.

## Stack Tecnológica

- **Framework**: FastAPI (Python 3.11+)
- **Database**: PostgreSQL 14+ (async SQLAlchemy)
- **Cache/Queue**: Redis 7+
- **Queue Workers**: Celery
- **ORM**: SQLAlchemy 2.0 (async)
- **Migrations**: Alembic
- **Validation**: Pydantic v2
- **Authentication**: JWT (python-jose)
- **Password Hashing**: bcrypt (passlib)

## Estrutura do Projeto

```
backend/
├── src/                    # Código fonte
│   ├── api/               # Endpoints FastAPI
│   ├── models/            # SQLAlchemy models
│   ├── schemas/           # Pydantic schemas
│   ├── services/          # Business logic
│   ├── repositories/      # Data access layer
│   ├── connectors/        # Database connectors
│   ├── workers/           # Celery workers
│   └── core/              # Core utilities
├── tests/                 # Testes
├── migrations/            # Alembic migrations
└── scripts/              # Utility scripts
```

## Setup Inicial

### Pré-requisitos

- Python 3.11+
- PostgreSQL 14+ (ou use a infraestrutura em `../deploy/`)
- Redis 7+ (ou use a infraestrutura em `../deploy/`)

### Instalação

1. **Clone o repositório e entre na pasta backend:**

```bash
cd backend
```

2. **Crie um ambiente virtual:**

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows
```

3. **Instale as dependências:**

```bash
pip install -r requirements.txt
```

4. **Configure as variáveis de ambiente:**

```bash
cp .env.example .env
# Edite .env com suas configurações
```

5. **Configure o banco de dados:**

```bash
# Crie o banco de dados PostgreSQL
createdb ai_saas_db

# Execute as migrations
alembic upgrade head
```

6. **Inicie a infraestrutura (Postgres + Redis):**

```bash
# Na pasta deploy (raiz dos repositórios)
cd ../deploy
./start.sh
```

7. **Inicie o servidor:**

```bash
# Volte para a pasta backend
cd ../sky-poc-backend
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

**Nota:** A infraestrutura (Postgres e Redis) está centralizada em `../deploy/` e serve tanto o Backend quanto o AI Service.

## Desenvolvimento

### Executar Migrations

```bash
# Criar nova migration
alembic revision --autogenerate -m "description"

# Aplicar migrations
alembic upgrade head

# Reverter migration
alembic downgrade -1
```

### Executar Testes

```bash
# Todos os testes
pytest

# Com coverage
pytest --cov=src --cov-report=html

# Testes específicos
pytest tests/unit/services/
```

### Formatação de Código

```bash
# Black
black src tests

# isort
isort src tests

# Flake8
flake8 src tests
```

## API Documentation

Após iniciar o servidor, acesse:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Endpoints Principais

### Autenticação
- `POST /api/v1/auth/login` - Login
- `POST /api/v1/auth/logout` - Logout
- `POST /api/v1/auth/refresh` - Refresh token
- `GET /api/v1/auth/me` - Dados do usuário

### Workspaces
- `GET /api/v1/workspaces` - Listar workspaces
- `POST /api/v1/workspaces` - Criar workspace
- `PUT /api/v1/workspaces/:id` - Atualizar workspace
- `DELETE /api/v1/workspaces/:id` - Deletar workspace

### Dashboards
- `GET /api/v1/dashboards` - Listar dashboards
- `POST /api/v1/dashboards` - Criar dashboard
- `GET /api/v1/dashboards/:id/widgets` - Widgets do dashboard

### Conexões
- `GET /api/v1/connections` - Listar conexões
- `POST /api/v1/connections` - Criar conexão
- `POST /api/v1/connections/:id/test` - Testar conexão
- `POST /api/v1/connections/:id/sync` - Sincronizar

### IA
- `POST /api/v1/ai/query` - Fazer pergunta
- `POST /api/v1/ai/chat` - Chat com IA
- `GET /api/v1/ai/history` - Histórico

## Workers

### Celery Worker

```bash
celery -A src.workers.celery_app worker --loglevel=info
```

### Celery Beat (para tarefas agendadas)

```bash
celery -A src.workers.celery_app beat --loglevel=info
```

## Monitoramento

- **Health Check**: `GET /health`
- **Ready Check**: `GET /ready`
- **Liveness Check**: `GET /live`
- **Prometheus Metrics**: `GET /metrics`

## Segurança

- JWT authentication obrigatória para endpoints protegidos
- Rate limiting configurado
- Input validation com Pydantic
- SQL injection prevention
- XSS/CSRF protection
- Credenciais criptografadas (AES-256)

## Contribuindo

1. Crie uma branch para sua feature
2. Faça commit das mudanças
3. Execute os testes
4. Abra um Pull Request

## Licença

Proprietário - Todos os direitos reservados


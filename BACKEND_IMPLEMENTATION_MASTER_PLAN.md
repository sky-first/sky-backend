# 🏗️ BACKEND IMPLEMENTATION MASTER PLAN
## Plano Mestre de Implementação - Plataforma SaaS de Business Intelligence com IA

**Versão:** 1.0.0  
**Data:** 2025-01-15  
**Status:** Documento Técnico Completo  
**Autor:** Tech Lead / Staff Engineer

---

## 📋 Índice

1. [Consolidação de Requisitos](#1-consolidação-de-requisitos)
2. [Arquitetura Final do Backend](#2-arquitetura-final-do-backend)
3. [Serviços do Backend](#3-serviços-do-backend)
4. [Modelos de Dados (Database Schema)](#4-modelos-de-dados-database-schema)
5. [Endpoints Completos do Backend](#5-endpoints-completos-do-backend)
6. [Fluxos Internos Detalhados](#6-fluxos-internos-detalhados)
7. [Módulo de Integração / Third-Party Integrations](#7-módulo-de-integração--third-party-integrations)
8. [Cache + Performance + Otimizações](#8-cache--performance--otimizações)
9. [Filas e Processamento Assíncrono](#9-filas-e-processamento-assíncrono)
10. [Segurança Completa](#10-segurança-completa)
11. [Observabilidade (Monitoramento)](#11-observabilidade-monitoramento)
12. [Deployment e Infraestrutura](#12-deployment-e-infraestrutura)
13. [Plano de Implementação em Etapas (Roadmap Técnico)](#13-plano-de-implementação-em-etapas-roadmap-técnico)

---

## 1. Consolidação de Requisitos

### 1.1 Análise Comparativa dos Documentos

#### Documentos Analisados
- **BACKEND_REQUIREMENTS.md**: Foco em requisitos funcionais específicos do frontend
- **BACKEND_SAAS_AI_BLUEPRINT.md**: Foco em checklist completo de plataforma SaaS enterprise

#### Sobreposições Identificadas

**Endpoints:**
- Ambos definem autenticação JWT com refresh tokens
- Ambos incluem gestão de workspaces, dashboards e widgets
- Ambos definem conexões de dados e integrações
- Ambos incluem endpoints de IA

**Modelos de Dados:**
- User, Workspace, Dashboard, Widget presentes em ambos
- DataConnection e ConnectionMetadata em ambos
- AIQuery, AIHistory, Pipeline em ambos

**Serviços:**
- Authentication Service
- Connection Service
- AI Service
- Widget Data Service
- Sync Service
- Permission Service

**Segurança:**
- JWT authentication
- RBAC
- Rate limiting
- Input validation
- SQL injection prevention

#### Lacunas Identificadas

**No BACKEND_REQUIREMENTS.md (presente no BLUEPRINT):**
- Multi-tenancy detalhado (apenas mencionado)
- Integrações de pagamento (Stripe, etc.)
- Compliance (LGPD, GDPR)
- Backup e disaster recovery detalhado
- Observabilidade completa (APM, tracing)
- Versionamento de API
- Webhooks de saída

**No BACKEND_SAAS_AI_BLUEPRINT.md (presente no REQUIREMENTS):**
- Spaces e Crews (conceitos específicos do domínio)
- Connection Permissions detalhadas
- Pipeline de IA com steps específicos
- Chat Messages e AI Responses
- Templates com aplicação a dashboards

#### Conflitos e Resoluções

**Conflito 1: Estrutura de Autenticação**
- REQUIREMENTS: Endpoints básicos (login, logout, refresh, me)
- BLUEPRINT: Inclui OAuth, 2FA, social login
- **Resolução**: Implementar endpoints básicos primeiro (MVP), OAuth e 2FA como features futuras

**Conflito 2: Multi-tenancy**
- REQUIREMENTS: Workspaces como isolamento principal
- BLUEPRINT: Tenant/Organization com múltiplas estratégias
- **Resolução**: Usar Workspaces como unidade de isolamento (row-level security), adicionar conceito de Tenant/Organization no futuro se necessário

**Conflito 3: IA Implementation**
- REQUIREMENTS: Pipeline detalhado com steps específicos
- BLUEPRINT: Integração com múltiplos providers
- **Resolução**: Implementar pipeline mockado primeiro, abstrair providers através de interface comum

**Conflito 4: Estrutura de Pastas**
- REQUIREMENTS: Não especifica
- BLUEPRINT: Estrutura genérica
- **Resolução**: Definir estrutura específica para FastAPI/Python

### 1.2 Requisitos Unificados Finais

#### Endpoints Totais: 67 endpoints

**Autenticação (8):**
- POST /api/auth/login
- POST /api/auth/logout
- POST /api/auth/refresh
- POST /api/auth/forgot-password
- POST /api/auth/reset-password
- GET /api/auth/me
- POST /api/auth/verify-email
- GET /api/auth/session

**Usuários (8):**
- GET /api/users
- GET /api/users/:id
- POST /api/users
- PUT /api/users/:id
- DELETE /api/users/:id
- GET /api/users/:id/permissions
- PUT /api/users/:id/permissions
- POST /api/users/:id/invite

**Workspaces (10):**
- GET /api/workspaces
- GET /api/workspaces/:id
- POST /api/workspaces
- PUT /api/workspaces/:id
- DELETE /api/workspaces/:id
- GET /api/workspaces/:id/members
- POST /api/workspaces/:id/members
- DELETE /api/workspaces/:id/members/:userId
- PUT /api/workspaces/:id/members/:userId/role
- GET /api/workspaces/:id/dashboards
- POST /api/workspaces/:id/switch

**Dashboards e Widgets (11):**
- GET /api/dashboards
- GET /api/dashboards/:id
- POST /api/dashboards
- PUT /api/dashboards/:id
- DELETE /api/dashboards/:id
- GET /api/dashboards/:id/widgets
- POST /api/dashboards/:id/widgets
- PUT /api/widgets/:id
- DELETE /api/widgets/:id
- POST /api/widgets/:id/duplicate
- POST /api/widgets/:id/export
- GET /api/widgets/:id/data
- POST /api/widgets/:id/refresh

**Conexões de Dados (11):**
- GET /api/connections
- GET /api/connections/:id
- POST /api/connections
- PUT /api/connections/:id
- DELETE /api/connections/:id
- POST /api/connections/:id/test
- POST /api/connections/:id/sync
- GET /api/connections/:id/metadata
- GET /api/connections/:id/tables
- GET /api/connections/:id/schemas
- GET /api/connections/:id/status
- POST /api/connections/:id/validate

**Permissões (7):**
- GET /api/permissions/connections/:connectionId
- POST /api/permissions/connections/:connectionId
- PUT /api/permissions/:id
- DELETE /api/permissions/:id
- GET /api/permissions/spaces/:spaceId
- GET /api/permissions/crews/:crewId
- POST /api/permissions/validate

**Spaces e Crews (12):**
- GET /api/spaces
- GET /api/spaces/:id
- POST /api/spaces
- PUT /api/spaces/:id
- DELETE /api/spaces/:id
- GET /api/spaces/:id/crews
- GET /api/spaces/:id/connections
- POST /api/spaces/:id/members
- DELETE /api/spaces/:id/members/:userId
- GET /api/crews
- GET /api/crews/:id
- POST /api/crews
- PUT /api/crews/:id
- DELETE /api/crews/:id
- GET /api/crews/:id/members
- POST /api/crews/:id/members
- DELETE /api/crews/:id/members/:userId
- PUT /api/crews/:id/members/:userId/role

**IA e Pipeline (12):**
- POST /api/ai/query
- POST /api/ai/chat
- GET /api/ai/history
- GET /api/ai/history/:id
- DELETE /api/ai/history/:id
- POST /api/ai/history/:id/pin
- POST /api/ai/history/:id/unpin
- GET /api/ai/history/export
- POST /api/ai/pipeline/execute
- GET /api/ai/pipeline/:id/status
- GET /api/ai/pipeline/:id/logs
- POST /api/ai/generate-sql
- POST /api/ai/generate-answer
- POST /api/ai/analyze-question

**Templates (7):**
- GET /api/templates
- GET /api/templates/:id
- POST /api/templates
- PUT /api/templates/:id
- DELETE /api/templates/:id
- GET /api/templates/categories
- POST /api/templates/:id/apply

**Configurações (10):**
- GET /api/settings
- PUT /api/settings
- GET /api/settings/data-catalog
- GET /api/settings/spaces
- GET /api/settings/crews
- GET /api/settings/users
- GET /api/settings/permissions
- GET /api/settings/api-keys
- POST /api/settings/api-keys
- DELETE /api/settings/api-keys/:id
- GET /api/settings/integrations
- POST /api/settings/integrations
- PUT /api/settings/integrations/:id
- DELETE /api/settings/integrations/:id

**Upload e Arquivos (7):**
- POST /api/upload
- POST /api/upload/csv
- POST /api/upload/excel
- POST /api/upload/image
- POST /api/upload/pdf
- GET /api/files/:id
- DELETE /api/files/:id

**Connector Registry (3):**
- GET /api/connectors
- GET /api/connectors/:id
- GET /api/connectors/categories

**Health e Monitoramento (3):**
- GET /health
- GET /ready
- GET /live

#### Modelos de Dados Totais: 25 entidades

1. User
2. RefreshToken
3. Workspace
4. WorkspaceMember
5. Dashboard
6. Widget
7. Connection (Widget Connections)
8. DataConnection
9. ConnectionMetadata
10. TableMetadata (embedded)
11. ColumnMetadata (embedded)
12. Space
13. Crew
14. CrewMember
15. ConnectionPermission
16. AIQuery
17. AIHistory
18. Pipeline
19. PipelineStep (embedded)
20. ChatMessage
21. AIResponse
22. Template
23. SyncLog
24. APIKey
25. FileUpload

#### Serviços Totais: 9 serviços principais

1. AuthenticationService
2. ConnectionService
3. AIService (mockado inicialmente)
4. WidgetDataService
5. SyncService
6. PermissionService
7. TemplateService
8. FileUploadService
9. NotificationService

---

## 2. Arquitetura Final do Backend

### 2.1 Decisão Arquitetural

**Arquitetura Escolhida: Monolito Modular**

**Justificativa:**
- MVP e desenvolvimento inicial mais rápido
- Menor complexidade operacional
- Facilita desenvolvimento e debugging
- Permite evolução para microserviços no futuro
- Adequado para equipe pequena/média
- Reduz latência entre módulos

**Evolução Futura:**
- Possibilidade de extrair serviços para microserviços quando necessário
- Workers já separados facilitam migração
- Abstrações permitem refatoração gradual

### 2.2 Stack Tecnológica

**Backend Framework:**
- **FastAPI** (Python 3.11+)
  - Performance alta (comparable a Node.js/Go)
  - Type hints nativos
  - Documentação automática (OpenAPI/Swagger)
  - Validação com Pydantic
  - Async/await nativo

**Banco de Dados:**
- **PostgreSQL 14+** (principal)
  - ACID compliance
- **Redis 7+** (cache, sessions, queues)

**ORM:**
- **SQLAlchemy 2.0+** (async)
  - Type-safe queries
  - Migrations com Alembic

**Validação:**
- **Pydantic v2**
  - Validação de dados
  - Serialização automática

**Autenticação:**
- **python-jose** (JWT)
- **passlib** (bcrypt)

**Queue:**
- **Celery** com Redis broker
  - Ou **RQ** (Redis Queue) para simplicidade

**Storage:**
- **boto3** (AWS S3) ou **google-cloud-storage**

**Monitoramento:**
- **Prometheus** + **Grafana**
- **Sentry** (error tracking)

### 2.3 Estrutura de Pastas Detalhada

```
backend/
├── src/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py         # Pydantic Settings
│   │   ├── database.py         # DB connection pool
│   │   └── redis.py             # Redis connection
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py              # Dependencies (auth, DB session)
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py          # JWT authentication
│   │   │   ├── cors.py          # CORS
│   │   │   ├── rate_limit.py    # Rate limiting
│   │   │   ├── logging.py       # Request logging
│   │   │   └── error_handler.py # Global error handler
│   │   │
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py        # Main router
│   │       ├── auth.py          # Auth endpoints
│   │       ├── users.py          # User endpoints
│   │       ├── workspaces.py    # Workspace endpoints
│   │       ├── dashboards.py    # Dashboard endpoints
│   │       ├── widgets.py       # Widget endpoints
│   │       ├── connections.py  # Data connection endpoints
│   │       ├── permissions.py  # Permission endpoints
│   │       ├── spaces.py        # Space endpoints
│   │       ├── crews.py         # Crew endpoints
│   │       ├── ai.py            # AI endpoints
│   │       ├── templates.py    # Template endpoints
│   │       ├── settings.py      # Settings endpoints
│   │       ├── upload.py        # Upload endpoints
│   │       └── connectors.py    # Connector registry
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── security.py          # JWT, password hashing
│   │   ├── permissions.py       # RBAC logic
│   │   └── exceptions.py        # Custom exceptions
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── workspace.py
│   │   ├── dashboard.py
│   │   ├── widget.py
│   │   ├── connection.py
│   │   ├── space.py
│   │   ├── crew.py
│   │   ├── ai.py
│   │   ├── template.py
│   │   └── file.py
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── user.py              # Pydantic schemas
│   │   ├── workspace.py
│   │   ├── dashboard.py
│   │   ├── widget.py
│   │   ├── connection.py
│   │   ├── ai.py
│   │   └── common.py            # Common schemas
│   │
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── base.py              # Base repository
│   │   ├── user.py
│   │   ├── workspace.py
│   │   ├── dashboard.py
│   │   ├── widget.py
│   │   ├── connection.py
│   │   └── ai.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py
│   │   ├── connection_service.py
│   │   ├── ai_service.py        # Mocked initially
│   │   ├── widget_data_service.py
│   │   ├── sync_service.py
│   │   ├── permission_service.py
│   │   ├── template_service.py
│   │   ├── file_upload_service.py
│   │   └── notification_service.py
│   │
│   ├── connectors/
│   │   ├── __init__.py
│   │   ├── base.py              # Base connector interface
│   │   ├── mysql.py
│   │   ├── postgresql.py
│   │   ├── mongodb.py
│   │   ├── google_sheets.py
│   │   └── rest_api.py
│   │
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── sync_worker.py
│   │   ├── ai_worker.py
│   │   ├── email_worker.py
│   │   └── file_worker.py
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── cache.py             # Cache helpers
│   │   ├── validators.py
│   │   ├── encryption.py        # AES encryption for credentials
│   │   └── logger.py            # Structured logging
│   │
│   └── ai/
│       ├── __init__.py
│       ├── mock.py               # Mock AI service
│       ├── pipeline.py           # AI pipeline orchestrator
│       └── providers.py          # Future: OpenAI, Anthropic, etc.
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py               # Pytest fixtures
│   ├── unit/
│   │   ├── services/
│   │   ├── repositories/
│   │   └── utils/
│   ├── integration/
│   │   ├── api/
│   │   └── database/
│   └── e2e/
│
├── migrations/
│   └── versions/                 # Alembic migrations
│
├── scripts/
│   ├── init_db.py
│   ├── seed_data.py
│   └── backup_db.py
│
├── docker/
│   ├── Dockerfile
│   ├── Dockerfile.worker
│   └── docker-compose.yml
│
├── .env.example
├── .gitignore
├── requirements.txt
├── pyproject.toml
├── alembic.ini
└── README.md
```

### 2.4 Camadas da Aplicação

#### Camada 1: API Layer (Controllers)
- **Responsabilidade**: Receber requisições HTTP, validar entrada, chamar serviços
- **Tecnologia**: FastAPI routers
- **Padrão**: Thin controllers, fat services

#### Camada 2: Service Layer
- **Responsabilidade**: Lógica de negócio, orquestração, validações de negócio
- **Tecnologia**: Python classes
- **Padrão**: Service pattern

#### Camada 3: Repository Layer
- **Responsabilidade**: Acesso a dados, queries, abstração do ORM
- **Tecnologia**: SQLAlchemy repositories
- **Padrão**: Repository pattern

#### Camada 4: Model Layer
- **Responsabilidade**: Entidades de domínio, relacionamentos
- **Tecnologia**: SQLAlchemy models
- **Padrão**: Active Record / Data Mapper

### 2.5 Padrões Arquiteturais

#### Dependency Injection
- FastAPI dependency system
- Injeção de serviços, repositórios, sessões DB

#### Repository Pattern
- Abstração de acesso a dados
- Facilita testes (mocks)
- Centraliza queries complexas

#### Service Pattern
- Lógica de negócio isolada
- Reutilização entre endpoints
- Testabilidade

#### Factory Pattern
- Criação de connectors dinâmicos
- Criação de workers

#### Strategy Pattern
- Diferentes estratégias de cache
- Diferentes providers de IA (futuro)

### 2.6 Comunicação Entre Módulos

#### Síncrona
- Chamadas diretas entre serviços (mesmo processo)
- FastAPI dependencies

#### Assíncrona
- Celery/RQ para jobs pesados
- Redis Pub/Sub para eventos (opcional)

#### Eventos
- Eventos internos via callbacks/listeners
- Eventos externos via webhooks

### 2.7 Middleware Stack

**Ordem de execução:**
1. CORS Middleware
2. Request ID Middleware (gerar request_id)
3. Logging Middleware (log request)
4. Rate Limiting Middleware
5. Authentication Middleware (JWT)
6. Authorization Middleware (RBAC)
7. Error Handler Middleware (catch exceptions)

---

## 3. Serviços do Backend

### 3.1 AuthenticationService

**Responsabilidades:**
- Autenticação de usuários (login)
- Geração e validação de JWT tokens
- Gerenciamento de refresh tokens
- Logout e invalidação de tokens
- Recuperação de senha
- Verificação de email
- Gerenciamento de sessões

**Interface:**
```python
class AuthenticationService:
    async def login(email: str, password: str) -> LoginResponse
    async def logout(user_id: str, token: str) -> None
    async def refresh_token(refresh_token: str) -> TokenResponse
    async def forgot_password(email: str) -> None
    async def reset_password(token: str, new_password: str) -> None
    async def verify_email(token: str) -> None
    async def get_current_user(token: str) -> User
```

**Dependências:**
- UserRepository
- RefreshTokenRepository
- EmailService (NotificationService)
- Redis (para token blacklist)

**Eventos Emitidos:**
- `user.logged_in` (user_id, timestamp, ip_address)
- `user.logged_out` (user_id, timestamp)
- `user.password_reset_requested` (user_id, email)
- `user.email_verified` (user_id)

**Modelos Utilizados:**
- User
- RefreshToken

**Segurança:**
- Password hashing com bcrypt (salt rounds: 10)
- JWT com expiração (access: 15min, refresh: 7 dias)
- Token blacklist no Redis
- Rate limiting (5 tentativas/minuto por IP)
- Account lockout após 5 tentativas falhas

### 3.2 ConnectionService

**Responsabilidades:**
- Criar, atualizar, deletar conexões de dados
- Validar credenciais de conexão
- Testar conectividade
- Gerenciar metadados (tabelas, schemas, colunas)
- Executar queries SQL de forma segura
- Cache de metadados
- Retry logic para conexões falhadas

**Interface:**
```python
class ConnectionService:
    async def create_connection(data: CreateConnectionRequest) -> DataConnection
    async def update_connection(id: str, data: UpdateConnectionRequest) -> DataConnection
    async def delete_connection(id: str) -> None
    async def test_connection(connection_id: str) -> ConnectionTestResult
    async def get_metadata(connection_id: str) -> ConnectionMetadata
    async def get_tables(connection_id: str) -> List[TableMetadata]
    async def get_schemas(connection_id: str) -> List[SchemaMetadata]
    async def execute_query(connection_id: str, query: str, params: dict) -> QueryResult
    async def validate_connection(connection_id: str) -> ValidationResult
```

**Dependências:**
- DataConnectionRepository
- ConnectionMetadataRepository
- ConnectorFactory (cria drivers)
- CacheService (Redis)
- PermissionService (validar acesso)

**Eventos Emitidos:**
- `connection.created` (connection_id, user_id)
- `connection.updated` (connection_id, user_id)
- `connection.deleted` (connection_id, user_id)
- `connection.tested` (connection_id, success, latency)
- `connection.sync.completed` (connection_id, records_synced)
- `connection.sync.failed` (connection_id, error)

**Modelos Utilizados:**
- DataConnection
- ConnectionMetadata
- TableMetadata
- ColumnMetadata
- SyncLog

**Segurança:**
- Credenciais criptografadas (AES-256) no banco
- Query sanitization (parameterized queries)
- Whitelist de tabelas/colunas permitidas
- Timeout em queries (30s default)
- Rate limiting por conexão
- Validação de permissões antes de executar queries

### 3.3 AIService (Mockado Inicialmente)

**Responsabilidades:**
- Processar perguntas em linguagem natural
- Gerar SQL a partir de perguntas (mockado)
- Executar queries e retornar resultados
- Gerar respostas em linguagem natural (mockado)
- Gerenciar pipeline de processamento
- Cache de respostas similares
- Gerenciar histórico de interações

**Interface:**
```python
class AIService:
    async def process_query(question: str, widget_id: str, knowledge: List[str], 
                          configure_data: ConfigureData) -> AIQueryResponse
    async def chat(message: str, widget_id: str, context: dict) -> ChatResponse
    async def generate_sql(question: str, knowledge: List[str], 
                          sql_instructions: str, creativity: int) -> SQLGenerationResponse
    async def execute_pipeline(question: str, knowledge: List[str], 
                              configure_data: ConfigureData) -> PipelineResponse
    async def get_pipeline_status(pipeline_id: str) -> PipelineStatus
    async def get_history(user_id: str, filters: HistoryFilters) -> List[AIHistory]
```

**Dependências:**
- AIQueryRepository
- AIHistoryRepository
- PipelineRepository
- ConnectionService (para executar SQL gerado)
- CacheService (para cache de respostas)
- MockAIService (implementação mockada)

**Eventos Emitidos:**
- `ai.query.processed` (query_id, user_id, success)
- `ai.pipeline.started` (pipeline_id, query_id)
- `ai.pipeline.completed` (pipeline_id, duration)
- `ai.pipeline.failed` (pipeline_id, error)

**Modelos Utilizados:**
- AIQuery
- AIHistory
- Pipeline
- PipelineStep

**Segurança:**
- Rate limiting (10 queries/minuto por usuário)
- Validação de SQL gerado antes de executar
- Sanitização de inputs
- Limite de complexidade de queries
- Timeout em processamento (60s)

**Implementação Mockada:**
- Retorna respostas pré-definidas baseadas em keywords
- Simula pipeline com delays
- Gera SQL simples baseado em templates
- Cache de respostas por similaridade de pergunta

### 3.4 WidgetDataService

**Responsabilidades:**
- Buscar dados para widgets
- Cache de dados de widgets
- Atualização em tempo real (via polling inicialmente)
- Agregação e transformação de dados
- Validação de queries
- Refresh de dados sob demanda

**Interface:**
```python
class WidgetDataService:
    async def get_widget_data(widget_id: str) -> WidgetData
    async def refresh_widget_data(widget_id: str) -> WidgetData
    async def get_widget_data_cached(widget_id: str) -> Optional[WidgetData]
    async def aggregate_data(connection_id: str, query: str, aggregation: dict) -> AggregatedData
    async def transform_data(data: List[dict], transformation: dict) -> List[dict]
```

**Dependências:**
- WidgetRepository
- ConnectionService (para executar queries)
- CacheService (Redis)
- PermissionService (validar acesso aos dados)

**Eventos Emitidos:**
- `widget.data.updated` (widget_id, last_updated)
- `widget.data.refreshed` (widget_id, duration)

**Modelos Utilizados:**
- Widget
- DataConnection

**Segurança:**
- Validação de permissões antes de buscar dados
- Query sanitization
- Rate limiting por widget
- Cache com TTL (5 minutos)

### 3.5 SyncService

**Responsabilidades:**
- Executar sincronizações agendadas (cron jobs)
- Atualizar metadados de conexões
- Processar dados incrementais
- Gerenciar fila de sincronizações
- Notificar sobre falhas de sincronização
- Registrar logs de sincronização

**Interface:**
```python
class SyncService:
    async def schedule_sync(connection_id: str, sync_frequency: str) -> None
    async def execute_sync(connection_id: str) -> SyncResult
    async def sync_metadata(connection_id: str) -> MetadataSyncResult
    async def get_sync_status(connection_id: str) -> SyncStatus
    async def get_sync_logs(connection_id: str, limit: int) -> List[SyncLog]
```

**Dependências:**
- DataConnectionRepository
- ConnectionMetadataRepository
- SyncLogRepository
- ConnectionService
- QueueService (Celery/RQ)
- NotificationService

**Eventos Emitidos:**
- `sync.scheduled` (connection_id, next_sync)
- `sync.started` (connection_id, started_at)
- `sync.completed` (connection_id, records_synced, duration)
- `sync.failed` (connection_id, error)

**Modelos Utilizados:**
- DataConnection
- ConnectionMetadata
- SyncLog

**Segurança:**
- Validação de credenciais antes de sync
- Timeout em operações de sync (5 minutos)
- Retry automático com backoff exponencial
- Rate limiting por conexão

### 3.6 PermissionService

**Responsabilidades:**
- Validar permissões em tempo real
- Cache de permissões
- Herança de permissões (Space → Crew → User)
- Auditoria de acessos
- Gerenciar permissões de conexões
- Validar acesso a recursos

**Interface:**
```python
class PermissionService:
    async def check_permission(user_id: str, resource_type: str, resource_id: str, 
                              action: str) -> bool
    async def get_user_permissions(user_id: str, resource_type: str) -> List[Permission]
    async def grant_permission(connection_id: str, space_id: str, crew_id: str, 
                              access_level: str, table_access: List[str]) -> ConnectionPermission
    async def revoke_permission(permission_id: str) -> None
    async def validate_access(user_id: str, connection_id: str) -> bool
    async def get_connection_permissions(connection_id: str) -> List[ConnectionPermission]
```

**Dependências:**
- ConnectionPermissionRepository
- WorkspaceMemberRepository
- CrewMemberRepository
- CacheService (Redis)
- AuditService

**Eventos Emitidos:**
- `permission.granted` (permission_id, resource_id, user_id)
- `permission.revoked` (permission_id, resource_id, user_id)
- `access.denied` (user_id, resource_id, action)

**Modelos Utilizados:**
- ConnectionPermission
- WorkspaceMember
- CrewMember
- User

**Segurança:**
- Cache de permissões (TTL: 15 minutos)
- Invalidação de cache em mudanças
- Auditoria de todas as verificações de permissão
- Validação hierárquica (Workspace → Space → Crew → User)

### 3.7 TemplateService

**Responsabilidades:**
- Gerenciar templates de dashboards
- Aplicar templates a dashboards existentes
- Validar estrutura de widgets em templates
- Versionamento de templates
- Categorização de templates

**Interface:**
```python
class TemplateService:
    async def get_templates(category: str, search: str, popular: bool) -> List[Template]
    async def get_template(template_id: str) -> Template
    async def create_template(data: CreateTemplateRequest) -> Template
    async def update_template(template_id: str, data: UpdateTemplateRequest) -> Template
    async def delete_template(template_id: str) -> None
    async def apply_template(template_id: str, dashboard_id: str, position: dict) -> List[Widget]
    async def get_categories() -> List[str]
```

**Dependências:**
- TemplateRepository
- DashboardRepository
- WidgetRepository
- CacheService (Redis)

**Eventos Emitidos:**
- `template.created` (template_id, creator_id)
- `template.applied` (template_id, dashboard_id, widgets_created)

**Modelos Utilizados:**
- Template
- Dashboard
- Widget

**Segurança:**
- Validação de estrutura de widgets
- Cache de templates (TTL: 24 horas)
- Permissões para criar/editar templates (admin only)

### 3.8 FileUploadService

**Responsabilidades:**
- Upload de arquivos (CSV, Excel, imagens, PDF)
- Parse de CSV/Excel
- Validação de tipos de arquivo
- Storage (S3, GCS, ou local)
- Geração de URLs assinadas
- Limpeza de arquivos antigos

**Interface:**
```python
class FileUploadService:
    async def upload_file(file: UploadFile, user_id: str) -> FileUpload
    async def upload_csv(file: UploadFile, user_id: str) -> CSVUploadResult
    async def upload_excel(file: UploadFile, user_id: str) -> ExcelUploadResult
    async def get_file(file_id: str) -> FileUpload
    async def delete_file(file_id: str) -> None
    async def get_signed_url(file_id: str, expires_in: int) -> str
```

**Dependências:**
- FileUploadRepository
- StorageService (S3/GCS)
- QueueService (para processamento assíncrono)

**Eventos Emitidos:**
- `file.uploaded` (file_id, user_id, file_type, size)
- `file.parsed` (file_id, records_count)
- `file.deleted` (file_id)

**Modelos Utilizados:**
- FileUpload

**Segurança:**
- Validação de tipo MIME
- Validação de tamanho (max 50MB)
- Scan de vírus (opcional, futuro)
- Rate limiting (5 arquivos/minuto por usuário)
- URLs assinadas com expiração
- Permissões de acesso a arquivos

### 3.9 NotificationService

**Responsabilidades:**
- Notificações de sincronização
- Alertas de erros
- Notificações de compartilhamento
- Email notifications
- In-app notifications
- Gerenciamento de preferências de notificação

**Interface:**
```python
class NotificationService:
    async def send_email(to: str, subject: str, body: str, template: str) -> None
    async def send_notification(user_id: str, type: str, message: str, data: dict) -> None
    async def notify_sync_completed(connection_id: str, user_id: str, result: SyncResult) -> None
    async def notify_sync_failed(connection_id: str, user_id: str, error: str) -> None
    async def notify_dashboard_shared(dashboard_id: str, user_id: str, shared_with: List[str]) -> None
```

**Dependências:**
- EmailService (SendGrid, SES, etc.)
- QueueService (para envio assíncrono)
- UserRepository (para buscar preferências)

**Eventos Emitidos:**
- `notification.sent` (user_id, type, success)
- `email.sent` (to, subject, success)

**Modelos Utilizados:**
- User (preferências)

**Segurança:**
- Validação de destinatários
- Rate limiting (10 emails/hora por usuário)
- Sanitização de conteúdo
- Templates seguros (sem XSS)

---

## 4. Modelos de Dados (Database Schema)

### 4.1 Convenções Gerais

**Nomenclatura:**
- Tabelas: snake_case, plural (ex: `users`, `workspaces`)
- Colunas: snake_case (ex: `created_at`, `user_id`)
- Foreign keys: `{table}_id` (ex: `user_id`, `workspace_id`)
- Índices: `idx_{table}_{columns}` (ex: `idx_users_email`)

**Campos Padrão:**
- `id`: UUID (PRIMARY KEY)
- `created_at`: TIMESTAMP (NOT NULL, DEFAULT NOW())
- `updated_at`: TIMESTAMP (NOT NULL, DEFAULT NOW(), ON UPDATE NOW())
- `deleted_at`: TIMESTAMP (NULL, para soft deletes)

**Tipos PostgreSQL:**
- UUID: `UUID`
- Strings: `VARCHAR(n)` ou `TEXT`
- Numbers: `INTEGER`, `BIGINT`, `DECIMAL`
- Booleans: `BOOLEAN`
- JSON: `JSONB`
- Dates: `TIMESTAMP WITH TIME ZONE`

### 4.2 Schema Completo

#### 4.2.1 users

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    avatar TEXT,
    role VARCHAR(50) NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user', 'viewer')),
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    email_verified_at TIMESTAMP WITH TIME ZONE,
    onboarding_step INTEGER NOT NULL DEFAULT 0,
    has_completed_onboarding BOOLEAN NOT NULL DEFAULT FALSE,
    selected_domain VARCHAR(255),
    last_login_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_users_email ON users(email) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_role ON users(role) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_created_at ON users(created_at);
```

#### 4.2.2 refresh_tokens

```sql
CREATE TABLE refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token VARCHAR(255) NOT NULL UNIQUE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_token ON refresh_tokens(token);
CREATE INDEX idx_refresh_tokens_expires_at ON refresh_tokens(expires_at);
```

#### 4.2.3 workspaces

```sql
CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    type VARCHAR(50) NOT NULL CHECK (type IN ('personal', 'team')),
    color VARCHAR(7) NOT NULL, -- Hex color
    icon VARCHAR(255),
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    last_accessed TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_workspaces_owner_id ON workspaces(owner_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_workspaces_type ON workspaces(type) WHERE deleted_at IS NULL;
CREATE INDEX idx_workspaces_is_active ON workspaces(is_active) WHERE deleted_at IS NULL;
CREATE INDEX idx_workspaces_last_accessed ON workspaces(last_accessed);
```

#### 4.2.4 workspace_members

```sql
CREATE TABLE workspace_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    joined_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(workspace_id, user_id)
);

CREATE INDEX idx_workspace_members_workspace_id ON workspace_members(workspace_id);
CREATE INDEX idx_workspace_members_user_id ON workspace_members(user_id);
```

#### 4.2.5 dashboards

```sql
CREATE TABLE dashboards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    template_id UUID REFERENCES templates(id) ON DELETE SET NULL,
    canvas_settings JSONB NOT NULL DEFAULT '{}',
    is_locked BOOLEAN NOT NULL DEFAULT FALSE,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_dashboards_workspace_id ON dashboards(workspace_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_dashboards_created_by ON dashboards(created_by) WHERE deleted_at IS NULL;
CREATE INDEX idx_dashboards_created_at ON dashboards(created_at);
```

#### 4.2.6 widgets

```sql
CREATE TABLE widgets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dashboard_id UUID NOT NULL REFERENCES dashboards(id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL CHECK (type IN ('chart', 'kpi', 'table', 'ai-box', 'text')),
    title VARCHAR(255) NOT NULL,
    position JSONB NOT NULL, -- {x: number, y: number}
    size JSONB NOT NULL, -- {width: number, height: number}
    data JSONB NOT NULL DEFAULT '{}',
    config JSONB NOT NULL DEFAULT '{}',
    connection_id UUID REFERENCES data_connections(id) ON DELETE SET NULL,
    query_id UUID REFERENCES ai_queries(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_widgets_dashboard_id ON widgets(dashboard_id);
CREATE INDEX idx_widgets_type ON widgets(type);
CREATE INDEX idx_widgets_connection_id ON widgets(connection_id);
CREATE INDEX idx_widgets_query_id ON widgets(query_id);
```

#### 4.2.7 widget_connections

```sql
CREATE TABLE widget_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dashboard_id UUID NOT NULL REFERENCES dashboards(id) ON DELETE CASCADE,
    from_widget_id UUID NOT NULL REFERENCES widgets(id) ON DELETE CASCADE,
    to_widget_id UUID NOT NULL REFERENCES widgets(id) ON DELETE CASCADE,
    from_anchor VARCHAR(50) NOT NULL CHECK (from_anchor IN ('top', 'right', 'bottom', 'left')),
    to_anchor VARCHAR(50) NOT NULL CHECK (to_anchor IN ('top', 'right', 'bottom', 'left')),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(dashboard_id, from_widget_id, to_widget_id)
);

CREATE INDEX idx_widget_connections_dashboard_id ON widget_connections(dashboard_id);
CREATE INDEX idx_widget_connections_from_to ON widget_connections(from_widget_id, to_widget_id);
```

#### 4.2.8 data_connections

```sql
CREATE TABLE data_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    connector_id VARCHAR(100) NOT NULL, -- 'mysql', 'postgresql', 'mongodb', 'google-sheets', 'rest-api'
    description TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'inactive' CHECK (status IN ('active', 'inactive', 'error')),
    config JSONB NOT NULL, -- Encrypted credentials
    sync_frequency VARCHAR(100), -- Cron expression
    last_sync TIMESTAMP WITH TIME ZONE,
    next_sync TIMESTAMP WITH TIME ZONE,
    last_metadata_update TIMESTAMP WITH TIME ZONE,
    error JSONB, -- {message: string, timestamp: timestamp}
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_data_connections_connector_id ON data_connections(connector_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_data_connections_status ON data_connections(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_data_connections_created_by ON data_connections(created_by) WHERE deleted_at IS NULL;
CREATE INDEX idx_data_connections_last_sync ON data_connections(last_sync);
```

#### 4.2.9 connection_metadata

```sql
CREATE TABLE connection_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL UNIQUE REFERENCES data_connections(id) ON DELETE CASCADE,
    tables JSONB, -- Array of TableMetadata
    schemas JSONB, -- Array of SchemaMetadata
    documents JSONB, -- Array of DocumentMetadata (MongoDB)
    endpoints JSONB, -- Array of EndpointMetadata (REST API)
    last_metadata_update TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_connection_metadata_connection_id ON connection_metadata(connection_id);
```

#### 4.2.10 spaces

```sql
CREATE TABLE spaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    color VARCHAR(7), -- Hex color
    icon VARCHAR(255),
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_spaces_created_by ON spaces(created_by) WHERE deleted_at IS NULL;
```

#### 4.2.11 space_connections

```sql
CREATE TABLE space_connections (
    space_id UUID NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
    connection_id UUID NOT NULL REFERENCES data_connections(id) ON DELETE CASCADE,
    PRIMARY KEY (space_id, connection_id)
);

CREATE INDEX idx_space_connections_space_id ON space_connections(space_id);
CREATE INDEX idx_space_connections_connection_id ON space_connections(connection_id);
```

#### 4.2.12 crews

```sql
CREATE TABLE crews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    space_id UUID NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_crews_space_id ON crews(space_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_crews_created_by ON crews(created_by) WHERE deleted_at IS NULL;
```

#### 4.2.13 crew_members

```sql
CREATE TABLE crew_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    crew_id UUID NOT NULL REFERENCES crews(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL CHECK (role IN ('commander', 'navigator', 'explorer', 'guest')),
    joined_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(crew_id, user_id)
);

CREATE INDEX idx_crew_members_crew_id ON crew_members(crew_id);
CREATE INDEX idx_crew_members_user_id ON crew_members(user_id);
```

#### 4.2.14 crew_connections

```sql
CREATE TABLE crew_connections (
    crew_id UUID NOT NULL REFERENCES crews(id) ON DELETE CASCADE,
    connection_id UUID NOT NULL REFERENCES data_connections(id) ON DELETE CASCADE,
    PRIMARY KEY (crew_id, connection_id)
);

CREATE INDEX idx_crew_connections_crew_id ON crew_connections(crew_id);
CREATE INDEX idx_crew_connections_connection_id ON crew_connections(connection_id);
```

#### 4.2.15 connection_permissions

```sql
CREATE TABLE connection_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL REFERENCES data_connections(id) ON DELETE CASCADE,
    space_id UUID REFERENCES spaces(id) ON DELETE CASCADE,
    crew_id UUID REFERENCES crews(id) ON DELETE CASCADE,
    access_level VARCHAR(50) NOT NULL CHECK (access_level IN ('full', 'read-only', 'custom')),
    table_access JSONB, -- Array of table names (if access_level = 'custom')
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(connection_id, space_id, crew_id)
);

CREATE INDEX idx_connection_permissions_connection_id ON connection_permissions(connection_id);
CREATE INDEX idx_connection_permissions_space_id ON connection_permissions(space_id);
CREATE INDEX idx_connection_permissions_crew_id ON connection_permissions(crew_id);
```

#### 4.2.16 ai_queries

```sql
CREATE TABLE ai_queries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    widget_id UUID REFERENCES widgets(id) ON DELETE SET NULL,
    question TEXT NOT NULL,
    answer TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'processing' CHECK (status IN ('processing', 'completed', 'error')),
    configure_data JSONB NOT NULL,
    pipeline_id UUID REFERENCES pipelines(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ai_queries_user_id ON ai_queries(user_id);
CREATE INDEX idx_ai_queries_widget_id ON ai_queries(widget_id);
CREATE INDEX idx_ai_queries_status ON ai_queries(status);
CREATE INDEX idx_ai_queries_created_at ON ai_queries(created_at);
```

#### 4.2.17 ai_history

```sql
CREATE TABLE ai_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    preview TEXT NOT NULL,
    answer TEXT NOT NULL,
    date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    tags JSONB NOT NULL DEFAULT '[]',
    category VARCHAR(50) CHECK (category IN ('Finance', 'Marketing', 'Sales', 'General', 'Logistics')),
    pinned BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ai_history_user_id ON ai_history(user_id);
CREATE INDEX idx_ai_history_pinned ON ai_history(pinned);
CREATE INDEX idx_ai_history_category ON ai_history(category);
CREATE INDEX idx_ai_history_date ON ai_history(date);
CREATE INDEX idx_ai_history_user_date ON ai_history(user_id, date);
```

#### 4.2.18 pipelines

```sql
CREATE TABLE pipelines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_id UUID NOT NULL REFERENCES ai_queries(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL DEFAULT 'processing' CHECK (status IN ('processing', 'completed', 'error')),
    steps JSONB NOT NULL DEFAULT '[]', -- Array of PipelineStep
    current_step VARCHAR(255),
    errors JSONB, -- Array of errors
    logs TEXT,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pipelines_query_id ON pipelines(query_id);
CREATE INDEX idx_pipelines_status ON pipelines(status);
CREATE INDEX idx_pipelines_started_at ON pipelines(started_at);
```

#### 4.2.19 chat_messages

```sql
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    widget_id UUID NOT NULL REFERENCES widgets(id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL CHECK (type IN ('user', 'assistant')),
    content TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chat_messages_widget_id ON chat_messages(widget_id);
CREATE INDEX idx_chat_messages_timestamp ON chat_messages(timestamp);
```

#### 4.2.20 ai_responses

```sql
CREATE TABLE ai_responses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    widget_id UUID NOT NULL REFERENCES widgets(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ai_responses_widget_id ON ai_responses(widget_id);
CREATE INDEX idx_ai_responses_is_active ON ai_responses(is_active);
CREATE INDEX idx_ai_responses_timestamp ON ai_responses(timestamp);
```

#### 4.2.21 templates

```sql
CREATE TABLE templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    creator VARCHAR(255) NOT NULL,
    category VARCHAR(100) NOT NULL,
    description TEXT,
    thumbnail TEXT,
    question TEXT,
    widgets JSONB NOT NULL DEFAULT '[]',
    icon VARCHAR(255),
    color VARCHAR(7) NOT NULL,
    popular BOOLEAN NOT NULL DEFAULT FALSE,
    enterprise BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_templates_category ON templates(category);
CREATE INDEX idx_templates_popular ON templates(popular);
CREATE INDEX idx_templates_enterprise ON templates(enterprise);
```

#### 4.2.22 sync_logs

```sql
CREATE TABLE sync_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL REFERENCES data_connections(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL CHECK (status IN ('success', 'error')),
    records_synced INTEGER,
    duration INTEGER, -- milliseconds
    error TEXT,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sync_logs_connection_id ON sync_logs(connection_id);
CREATE INDEX idx_sync_logs_started_at ON sync_logs(started_at);
CREATE INDEX idx_sync_logs_status ON sync_logs(status);
```

#### 4.2.23 api_keys

```sql
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    key_hash VARCHAR(255) NOT NULL UNIQUE,
    key_prefix VARCHAR(20) NOT NULL,
    permissions JSONB NOT NULL DEFAULT '[]',
    last_used_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    revoked_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX idx_api_keys_key_hash ON api_keys(key_hash);
CREATE INDEX idx_api_keys_expires_at ON api_keys(expires_at);
```

#### 4.2.24 file_uploads

```sql
CREATE TABLE file_uploads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    size BIGINT NOT NULL,
    url TEXT NOT NULL,
    storage VARCHAR(50) NOT NULL CHECK (storage IN ('s3', 'local', 'gcs')),
    widget_id UUID REFERENCES widgets(id) ON DELETE SET NULL,
    parsed_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_file_uploads_user_id ON file_uploads(user_id);
CREATE INDEX idx_file_uploads_widget_id ON file_uploads(widget_id);
CREATE INDEX idx_file_uploads_mime_type ON file_uploads(mime_type);
CREATE INDEX idx_file_uploads_created_at ON file_uploads(created_at);
```

### 4.3 Relacionamentos

**User → Workspace (1:N)**
- Um usuário pode ter múltiplos workspaces
- Um workspace tem um owner (user)

**Workspace → WorkspaceMember (1:N)**
- Um workspace tem múltiplos membros
- Um usuário pode ser membro de múltiplos workspaces

**Workspace → Dashboard (1:N)**
- Um workspace tem múltiplos dashboards

**Dashboard → Widget (1:N)**
- Um dashboard tem múltiplos widgets

**DataConnection → ConnectionMetadata (1:1)**
- Uma conexão tem um registro de metadados

**Space → Crew (1:N)**
- Um space tem múltiplos crews

**Crew → CrewMember (1:N)**
- Um crew tem múltiplos membros

**DataConnection → ConnectionPermission (1:N)**
- Uma conexão pode ter múltiplas permissões (para diferentes spaces/crews)

**User → AIQuery (1:N)**
- Um usuário pode fazer múltiplas queries

**AIQuery → Pipeline (1:1)**
- Uma query tem um pipeline associado

**Widget → AIQuery (1:N)**
- Um widget pode ter múltiplas queries (histórico)

### 4.4 Estratégia de Soft Deletes

**Tabelas com soft delete:**
- users
- workspaces
- dashboards
- data_connections
- spaces
- crews

**Implementação:**
- Campo `deleted_at` (TIMESTAMP, NULL quando ativo)
- Queries sempre filtram `WHERE deleted_at IS NULL`
- Índices parciais para performance: `WHERE deleted_at IS NULL`

### 4.5 Normalização

**Normalizado (3NF):**
- Todas as entidades principais
- Relacionamentos via foreign keys
- Dados JSONB apenas para estruturas flexíveis (config, metadata)

**Desnormalização Intencional:**
- `connection_metadata.tables` (JSONB) - raramente consultado individualmente
- `widgets.data` (JSONB) - estrutura variável por tipo de widget
- `pipelines.steps` (JSONB) - array de objetos aninhados

---

## 5. Endpoints Completos do Backend

### 5.1 Convenções de API

**Versionamento:**
- URL-based: `/api/v1/...`
- Header-based (futuro): `Accept: application/vnd.api+json;version=1`

**Formato de Resposta Padrão:**
```json
{
  "success": true,
  "data": {},
  "message": "Operação realizada com sucesso",
  "meta": {
    "timestamp": "2025-01-15T10:30:00Z",
    "requestId": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

**Formato de Erro:**
```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Mensagem de erro",
    "details": {}
  },
  "meta": {
    "timestamp": "2025-01-15T10:30:00Z",
    "requestId": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

**Códigos HTTP:**
- `200 OK`: Sucesso
- `201 Created`: Recurso criado
- `204 No Content`: Sucesso sem conteúdo
- `400 Bad Request`: Erro de validação
- `401 Unauthorized`: Não autenticado
- `403 Forbidden`: Sem permissão
- `404 Not Found`: Recurso não encontrado
- `409 Conflict`: Conflito (ex: email já existe)
- `422 Unprocessable Entity`: Erro de validação de dados
- `429 Too Many Requests`: Rate limit excedido
- `500 Internal Server Error`: Erro do servidor

### 5.2 Endpoints de Autenticação

#### POST /api/v1/auth/login

**Descrição:** Autenticação de usuário com email e senha

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "securePassword123"
}
```

**Response 200:**
```json
{
  "success": true,
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refreshToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "expiresIn": 900,
    "user": {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "email": "user@example.com",
      "name": "John Doe",
      "avatar": "https://...",
      "role": "user"
    }
  }
}
```

**Response 401:**
```json
{
  "success": false,
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Email ou senha inválidos"
  }
}
```

**Permissões:** Público

**Rate Limit:** 5 tentativas/minuto por IP

---

#### POST /api/v1/auth/logout

**Descrição:** Invalida tokens do usuário

**Headers:**
- `Authorization: Bearer <token>`

**Response 204:** No Content

**Permissões:** Autenticado

---

#### POST /api/v1/auth/refresh

**Descrição:** Renova access token usando refresh token

**Request Body:**
```json
{
  "refreshToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response 200:**
```json
{
  "success": true,
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refreshToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "expiresIn": 900
  }
}
```

**Permissões:** Público (com refresh token válido)

---

#### GET /api/v1/auth/me

**Descrição:** Obtém dados do usuário autenticado

**Headers:**
- `Authorization: Bearer <token>`

**Response 200:**
```json
{
  "success": true,
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "name": "John Doe",
    "avatar": "https://...",
    "role": "user",
    "emailVerified": true,
    "hasCompletedOnboarding": true
  }
}
```

**Permissões:** Autenticado

---

#### POST /api/v1/auth/forgot-password

**Descrição:** Solicita reset de senha

**Request Body:**
```json
{
  "email": "user@example.com"
}
```

**Response 200:**
```json
{
  "success": true,
  "message": "Email de recuperação enviado"
}
```

**Permissões:** Público

**Rate Limit:** 3 tentativas/hora por email

---

#### POST /api/v1/auth/reset-password

**Descrição:** Reseta senha com token

**Request Body:**
```json
{
  "token": "reset_token_here",
  "newPassword": "newSecurePassword123"
}
```

**Response 200:**
```json
{
  "success": true,
  "message": "Senha alterada com sucesso"
}
```

**Permissões:** Público (com token válido)

---

#### POST /api/v1/auth/verify-email

**Descrição:** Verifica email do usuário

**Request Body:**
```json
{
  "token": "verification_token_here"
}
```

**Response 200:**
```json
{
  "success": true,
  "message": "Email verificado com sucesso"
}
```

**Permissões:** Público (com token válido)

---

### 5.3 Endpoints de Workspaces

#### GET /api/v1/workspaces

**Descrição:** Lista workspaces do usuário

**Query Parameters:**
- `type` (optional): `personal` | `team`
- `search` (optional): string
- `page` (optional): integer (default: 1)
- `limit` (optional): integer (default: 20)

**Response 200:**
```json
{
  "success": true,
  "data": {
    "workspaces": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "My Workspace",
        "description": "Description",
        "type": "personal",
        "color": "#FF5733",
        "icon": "workspace-icon",
        "isActive": true,
        "lastAccessed": "2025-01-15T10:30:00Z"
      }
    ],
    "total": 1,
    "page": 1,
    "limit": 20
  }
}
```

**Permissões:** Autenticado

---

#### POST /api/v1/workspaces

**Descrição:** Cria novo workspace

**Request Body:**
```json
{
  "name": "New Workspace",
  "description": "Workspace description",
  "type": "personal",
  "color": "#FF5733",
  "icon": "workspace-icon"
}
```

**Response 201:**
```json
{
  "success": true,
  "data": {
    "workspace": {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "New Workspace",
      "type": "personal",
      "color": "#FF5733",
      "ownerId": "user-id",
      "isActive": false,
      "createdAt": "2025-01-15T10:30:00Z"
    }
  }
}
```

**Permissões:** Autenticado

**Validações:**
- `name`: obrigatório, 1-255 caracteres
- `type`: obrigatório, `personal` ou `team`
- `color`: obrigatório, formato hex (#RRGGBB)

---

#### PUT /api/v1/workspaces/:id

**Descrição:** Atualiza workspace

**Path Parameters:**
- `id`: UUID do workspace

**Request Body:**
```json
{
  "name": "Updated Name",
  "description": "Updated description",
  "color": "#00FF00",
  "icon": "new-icon"
}
```

**Response 200:**
```json
{
  "success": true,
  "data": {
    "workspace": { /* workspace atualizado */ }
  }
}
```

**Permissões:** Owner ou Admin do workspace

---

#### DELETE /api/v1/workspaces/:id

**Descrição:** Deleta workspace (soft delete)

**Path Parameters:**
- `id`: UUID do workspace

**Response 204:** No Content

**Permissões:** Owner do workspace

---

#### GET /api/v1/workspaces/:id/members

**Descrição:** Lista membros do workspace

**Response 200:**
```json
{
  "success": true,
  "data": {
    "members": [
      {
        "id": "member-id",
        "userId": "user-id",
        "user": {
          "name": "John Doe",
          "email": "john@example.com",
          "avatar": "https://..."
        },
        "role": "member",
        "joinedAt": "2025-01-15T10:30:00Z"
      }
    ]
  }
}
```

**Permissões:** Membro do workspace

---

#### POST /api/v1/workspaces/:id/members

**Descrição:** Adiciona membro ao workspace

**Request Body:**
```json
{
  "userId": "user-id-to-add",
  "role": "member"
}
```

**Response 201:**
```json
{
  "success": true,
  "data": {
    "member": { /* member criado */ }
  }
}
```

**Permissões:** Owner ou Admin do workspace

---

#### POST /api/v1/workspaces/:id/switch

**Descrição:** Alterna workspace ativo do usuário

**Response 200:**
```json
{
  "success": true,
  "data": {
    "workspace": { /* workspace ativo */ },
    "dashboards": [ /* dashboards do workspace */ ]
  }
}
```

**Permissões:** Membro do workspace

---

### 5.4 Endpoints de Dashboards

#### GET /api/v1/dashboards

**Descrição:** Lista dashboards do workspace atual

**Query Parameters:**
- `workspaceId` (optional): UUID
- `page` (optional): integer
- `limit` (optional): integer

**Response 200:**
```json
{
  "success": true,
  "data": {
    "dashboards": [
      {
        "id": "dashboard-id",
        "name": "Sales Dashboard",
        "description": "Dashboard description",
        "workspaceId": "workspace-id",
        "isLocked": false,
        "createdAt": "2025-01-15T10:30:00Z"
      }
    ],
    "total": 1
  }
}
```

**Permissões:** Membro do workspace

---

#### POST /api/v1/dashboards

**Descrição:** Cria novo dashboard

**Request Body:**
```json
{
  "name": "New Dashboard",
  "description": "Dashboard description",
  "workspaceId": "workspace-id",
  "templateId": "template-id" // optional
}
```

**Response 201:**
```json
{
  "success": true,
  "data": {
    "dashboard": { /* dashboard criado */ }
  }
}
```

**Permissões:** Membro do workspace (com permissão de criar)

---

#### GET /api/v1/dashboards/:id/widgets

**Descrição:** Obtém todos os widgets de um dashboard

**Response 200:**
```json
{
  "success": true,
  "data": {
    "widgets": [
      {
        "id": "widget-id",
        "type": "chart",
        "title": "Sales Chart",
        "position": {"x": 0, "y": 0},
        "size": {"width": 400, "height": 300},
        "data": {},
        "config": {}
      }
    ],
    "connections": [
      {
        "id": "connection-id",
        "from": "widget-id-1",
        "to": "widget-id-2",
        "fromAnchor": "right",
        "toAnchor": "left"
      }
    ]
  }
}
```

**Permissões:** Membro do workspace

---

#### POST /api/v1/dashboards/:id/widgets

**Descrição:** Adiciona widget ao dashboard

**Request Body:**
```json
{
  "type": "chart",
  "title": "New Widget",
  "position": {"x": 0, "y": 0},
  "size": {"width": 400, "height": 300},
  "data": {},
  "config": {}
}
```

**Response 201:**
```json
{
  "success": true,
  "data": {
    "widget": { /* widget criado */ }
  }
}
```

**Permissões:** Membro do workspace (com permissão de editar)

---

#### PUT /api/v1/widgets/:id

**Descrição:** Atualiza widget

**Request Body:**
```json
{
  "title": "Updated Title",
  "position": {"x": 100, "y": 100},
  "size": {"width": 500, "height": 400},
  "data": {},
  "config": {}
}
```

**Response 200:**
```json
{
  "success": true,
  "data": {
    "widget": { /* widget atualizado */ }
  }
}
```

**Permissões:** Membro do workspace (com permissão de editar)

---

#### GET /api/v1/widgets/:id/data

**Descrição:** Obtém dados atualizados do widget

**Response 200:**
```json
{
  "success": true,
  "data": {
    "data": [ /* dados do widget */ ],
    "lastUpdated": "2025-01-15T10:30:00Z"
  }
}
```

**Permissões:** Membro do workspace

---

#### POST /api/v1/widgets/:id/refresh

**Descrição:** Força atualização de dados do widget

**Response 200:**
```json
{
  "success": true,
  "data": {
    "data": [ /* dados atualizados */ ],
    "lastUpdated": "2025-01-15T10:30:00Z"
  }
}
```

**Permissões:** Membro do workspace

---

### 5.5 Endpoints de Conexões de Dados

#### GET /api/v1/connections

**Descrição:** Lista conexões de dados

**Query Parameters:**
- `category` (optional): `database` | `document` | `api`
- `status` (optional): `active` | `inactive` | `error`
- `spaceId` (optional): UUID
- `crewId` (optional): UUID
- `search` (optional): string
- `page` (optional): integer
- `limit` (optional): integer

**Response 200:**
```json
{
  "success": true,
  "data": {
    "connections": [
      {
        "id": "connection-id",
        "name": "PostgreSQL Production",
        "connectorId": "postgresql",
        "status": "active",
        "lastSync": "2025-01-15T10:30:00Z",
        "createdAt": "2025-01-15T10:30:00Z"
      }
    ],
    "total": 1
  }
}
```

**Permissões:** Autenticado (filtrado por permissões)

---

#### POST /api/v1/connections

**Descrição:** Cria nova conexão de dados

**Request Body:**
```json
{
  "name": "New Connection",
  "connectorId": "postgresql",
  "description": "Connection description",
  "config": {
    "host": "localhost",
    "port": 5432,
    "database": "mydb",
    "username": "user",
    "password": "password"
  },
  "syncFrequency": "0 */6 * * *" // Cron expression
}
```

**Response 201:**
```json
{
  "success": true,
  "data": {
    "connection": { /* connection criada */ }
  }
}
```

**Permissões:** Autenticado

**Validações:**
- `name`: obrigatório, 1-255 caracteres
- `connectorId`: obrigatório, deve existir no registry
- `config`: obrigatório, validado pelo connector

---

#### POST /api/v1/connections/:id/test

**Descrição:** Testa conexão

**Response 200:**
```json
{
  "success": true,
  "data": {
    "success": true,
    "message": "Conexão bem-sucedida",
    "latency": 45 // milliseconds
  }
}
```

**Permissões:** Owner da conexão

---

#### GET /api/v1/connections/:id/metadata

**Descrição:** Obtém metadados da conexão

**Response 200:**
```json
{
  "success": true,
  "data": {
    "tables": [
      {
        "name": "users",
        "schema": "public",
        "rowCount": 1000,
        "columns": [
          {
            "name": "id",
            "type": "uuid",
            "nullable": false
          }
        ]
      }
    ],
    "schemas": ["public"],
    "lastMetadataUpdate": "2025-01-15T10:30:00Z"
  }
}
```

**Permissões:** Com acesso à conexão

---

#### POST /api/v1/connections/:id/sync

**Descrição:** Força sincronização de metadados

**Response 200:**
```json
{
  "success": true,
  "data": {
    "success": true,
    "lastSync": "2025-01-15T10:30:00Z",
    "nextSync": "2025-01-15T16:30:00Z"
  }
}
```

**Permissões:** Owner da conexão

---

### 5.6 Endpoints de IA

#### POST /api/v1/ai/query

**Descrição:** Processa pergunta do usuário

**Request Body:**
```json
{
  "question": "Qual foi o total de vendas em janeiro?",
  "widgetId": "widget-id", // optional
  "knowledge": ["connection-id-1", "connection-id-2"],
  "configureData": {
    "responseFormat": "text",
    "creativity": 50,
    "length": 50
  }
}
```

**Response 200:**
```json
{
  "success": true,
  "data": {
    "answer": "O total de vendas em janeiro foi de R$ 150.000,00",
    "pipelineId": "pipeline-id",
    "steps": [
      {
        "id": "step-1",
        "name": "Question Specialist",
        "kind": "question",
        "status": "COMPLETED"
      }
    ]
  }
}
```

**Permissões:** Autenticado

**Rate Limit:** 10 queries/minuto por usuário

---

#### POST /api/v1/ai/chat

**Descrição:** Envia mensagem no chat do widget

**Request Body:**
```json
{
  "message": "Pode me mostrar mais detalhes?",
  "widgetId": "widget-id",
  "context": {}
}
```

**Response 200:**
```json
{
  "success": true,
  "data": {
    "response": "Claro! Aqui estão os detalhes...",
    "timestamp": "2025-01-15T10:30:00Z"
  }
}
```

**Permissões:** Membro do workspace

---

#### GET /api/v1/ai/history

**Descrição:** Obtém histórico de interações

**Query Parameters:**
- `filter` (optional): `today` | `week` | `pinned`
- `search` (optional): string
- `category` (optional): string
- `page` (optional): integer
- `limit` (optional): integer

**Response 200:**
```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "history-id",
        "query": "Qual foi o total de vendas?",
        "preview": "O total de vendas foi...",
        "date": "2025-01-15T10:30:00Z",
        "category": "Finance",
        "pinned": false
      }
    ],
    "total": 1
  }
}
```

**Permissões:** Autenticado (próprio histórico)

---

#### POST /api/v1/ai/generate-sql

**Descrição:** Gera SQL a partir de pergunta

**Request Body:**
```json
{
  "question": "Total de vendas por mês",
  "knowledge": ["connection-id"],
  "sqlInstructions": "Use apenas tabelas de vendas",
  "creativity": 50
}
```

**Response 200:**
```json
{
  "success": true,
  "data": {
    "sql": "SELECT DATE_TRUNC('month', date) as month, SUM(amount) as total FROM sales GROUP BY month",
    "explanation": "Query agrupa vendas por mês"
  }
}
```

**Permissões:** Autenticado

---

#### GET /api/v1/ai/pipeline/:id/status

**Descrição:** Obtém status do pipeline

**Response 200:**
```json
{
  "success": true,
  "data": {
    "status": "processing",
    "steps": [
      {
        "id": "step-1",
        "name": "Question Specialist",
        "kind": "question",
        "status": "COMPLETED",
        "content": "..."
      }
    ],
    "currentStep": "sql",
    "errors": []
  }
}
```

**Permissões:** Owner da query

---

### 5.7 Endpoints de Templates

#### GET /api/v1/templates

**Descrição:** Lista templates disponíveis

**Query Parameters:**
- `category` (optional): string
- `search` (optional): string
- `popular` (optional): boolean

**Response 200:**
```json
{
  "success": true,
  "data": {
    "templates": [
      {
        "id": "template-id",
        "name": "Sales Dashboard",
        "category": "Sales",
        "description": "Template for sales analytics",
        "thumbnail": "https://...",
        "popular": true
      }
    ]
  }
}
```

**Permissões:** Autenticado

---

#### POST /api/v1/templates/:id/apply

**Descrição:** Aplica template a um dashboard

**Request Body:**
```json
{
  "dashboardId": "dashboard-id",
  "position": {"x": 0, "y": 0} // optional
}
```

**Response 200:**
```json
{
  "success": true,
  "data": {
    "widgets": [ /* widgets criados */ ]
  }
}
```

**Permissões:** Membro do workspace (com permissão de editar)

---

### 5.8 Endpoints de Upload

#### POST /api/v1/upload

**Descrição:** Upload genérico de arquivo

**Request:** `multipart/form-data`
- `file`: File

**Response 200:**
```json
{
  "success": true,
  "data": {
    "fileId": "file-id",
    "url": "https://...",
    "type": "image/png",
    "size": 1024000
  }
}
```

**Permissões:** Autenticado

**Rate Limit:** 5 arquivos/minuto por usuário

**Validações:**
- Tamanho máximo: 50MB
- Tipos permitidos: configurável por endpoint

---

#### POST /api/v1/upload/csv

**Descrição:** Upload e parse de CSV

**Response 200:**
```json
{
  "success": true,
  "data": {
    "fileId": "file-id",
    "data": [ /* parsed data */ ],
    "columns": ["col1", "col2"],
    "preview": [ /* first 10 rows */ ]
  }
}
```

**Permissões:** Autenticado

---

### 5.9 Endpoints de Connectors

#### GET /api/v1/connectors

**Descrição:** Lista todos os connectors disponíveis

**Response 200:**
```json
{
  "success": true,
  "data": {
    "connectors": [
      {
        "id": "postgresql",
        "name": "PostgreSQL",
        "category": "database",
        "description": "PostgreSQL database connector",
        "configSchema": {
          "host": {"type": "string", "required": true},
          "port": {"type": "number", "required": true}
        }
      }
    ]
  }
}
```

**Permissões:** Autenticado

---

### 5.10 Endpoints de Health

#### GET /health

**Descrição:** Health check básico

**Response 200:**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-15T10:30:00Z"
}
```

**Permissões:** Público

---

#### GET /ready

**Descrição:** Readiness check (dependências)

**Response 200:**
```json
{
  "status": "ready",
  "database": "connected",
  "redis": "connected",
  "timestamp": "2025-01-15T10:30:00Z"
}
```

**Permissões:** Público

---

#### GET /live

**Descrição:** Liveness check

**Response 200:**
```json
{
  "status": "alive"
}
```

**Permissões:** Público

---

## 6. Fluxos Internos Detalhados

### 6.1 Fluxo de Autenticação

**Descrição:** Processo completo de login e gerenciamento de sessão

**Diagrama Textual:**
```
1. Cliente → POST /api/v1/auth/login {email, password}
2. API → AuthenticationService.login()
3. AuthenticationService → UserRepository.find_by_email()
4. AuthenticationService → bcrypt.verify(password, password_hash)
5. Se válido:
   a. AuthenticationService → generate_jwt_token(user)
   b. AuthenticationService → generate_refresh_token(user)
   c. AuthenticationService → RefreshTokenRepository.create()
   d. AuthenticationService → UserRepository.update_last_login()
   e. API → Retorna {token, refreshToken, user}
6. Se inválido:
   a. AuthenticationService → increment_failed_attempts()
   b. Se >= 5 tentativas → lock_account()
   c. API → Retorna 401
```

**Responsabilidades:**
- **API Layer**: Receber request, validar formato
- **AuthenticationService**: Lógica de autenticação
- **UserRepository**: Buscar usuário
- **Security Utils**: Hash/verify senha, gerar tokens

**Validações:**
- Email formato válido
- Senha não vazia
- Usuário existe
- Usuário não está bloqueado
- Conta não está desativada

**Erros Possíveis:**
- `INVALID_CREDENTIALS`: Email ou senha inválidos
- `ACCOUNT_LOCKED`: Conta bloqueada por tentativas
- `ACCOUNT_DISABLED`: Conta desativada
- `EMAIL_NOT_VERIFIED`: Email não verificado

---

### 6.2 Fluxo de Autorização (RBAC)

**Descrição:** Verificação de permissões antes de acessar recursos

**Diagrama Textual:**
```
1. Cliente → Request com Authorization header
2. Middleware → Extrai token JWT
3. Middleware → Valida token (expiração, assinatura)
4. Middleware → Busca usuário do token
5. Middleware → Verifica role do usuário
6. Para recursos específicos:
   a. PermissionService → check_workspace_access(user_id, workspace_id)
   b. PermissionService → WorkspaceMemberRepository.find_by_user_and_workspace()
   c. PermissionService → Verifica role (owner/admin/member/viewer)
   d. PermissionService → Verifica ação permitida para role
7. Se autorizado → Continua request
8. Se não autorizado → Retorna 403
```

**Responsabilidades:**
- **Auth Middleware**: Validação de token
- **PermissionService**: Lógica de autorização
- **WorkspaceMemberRepository**: Buscar membros
- **Cache**: Cache de permissões (15min TTL)

**Validações:**
- Token válido e não expirado
- Usuário existe e está ativo
- Usuário tem acesso ao workspace
- Role permite ação solicitada

**Erros Possíveis:**
- `UNAUTHORIZED`: Token inválido ou expirado
- `FORBIDDEN`: Sem permissão para ação
- `RESOURCE_NOT_FOUND`: Recurso não existe ou sem acesso

---

### 6.3 Fluxo de Criação de Widget com IA

**Descrição:** Processo completo de criação de widget usando IA

**Diagrama Textual:**
```
1. Cliente → POST /api/v1/dashboards/:id/widgets {type: 'ai-box', question: '...'}
2. API → WidgetRepository.create() (widget vazio)
3. API → AIService.process_query(question, widget_id, knowledge)
4. AIService → Cria AIQuery (status: 'processing')
5. AIService → Cria Pipeline (status: 'processing')
6. AIService → Envia job para fila (AIWorker)
7. API → Retorna {widget, pipelineId} (assíncrono)
8. AIWorker (background):
   a. Question Specialist → Analisa pergunta
   b. Orchestrator → Identifica datasets relevantes
   c. SQL Specialist → Gera SQL (mockado)
   d. ConnectionService → Executa SQL
   e. Answer Specialist → Gera resposta (mockado)
   f. AIService → Atualiza AIQuery (status: 'completed', answer)
   g. AIService → Atualiza Widget.data
   h. AIService → Salva AIHistory
   i. NotificationService → Notifica conclusão (opcional)
9. Cliente → Polling GET /api/v1/ai/pipeline/:id/status
10. Cliente → Atualiza widget quando completo
```

**Responsabilidades:**
- **API Layer**: Receber request, criar widget inicial
- **AIService**: Orquestrar pipeline
- **AIWorker**: Processar pipeline em background
- **ConnectionService**: Executar queries
- **WidgetRepository**: Atualizar widget

**Validações:**
- Dashboard existe e usuário tem acesso
- Question não vazia
- Knowledge (connections) acessíveis
- Rate limit não excedido

**Erros Possíveis:**
- `DASHBOARD_NOT_FOUND`: Dashboard não existe
- `ACCESS_DENIED`: Sem acesso ao dashboard
- `RATE_LIMIT_EXCEEDED`: Muitas queries
- `INVALID_QUESTION`: Pergunta inválida
- `PIPELINE_ERROR`: Erro no processamento

---

### 6.4 Fluxo de Sincronização de Conexão

**Descrição:** Sincronização agendada de metadados de conexão

**Diagrama Textual:**
```
1. Cron Job → Dispara sync (baseado em syncFrequency)
2. SyncService → Busca conexões com next_sync <= NOW()
3. Para cada conexão:
   a. SyncService → Cria SyncLog (status: 'processing')
   b. SyncService → Envia job para fila (SyncWorker)
4. SyncWorker (background):
   a. ConnectionService → Testa conexão
   b. Se conectado:
      i. Connector → Descobre schema (tabelas, colunas)
      ii. ConnectionService → Atualiza ConnectionMetadata
      iii. SyncService → Atualiza SyncLog (status: 'success', records_synced)
      iv. SyncService → Calcula next_sync
   c. Se falhou:
      i. SyncService → Atualiza SyncLog (status: 'error', error)
      ii. SyncService → Atualiza DataConnection.error
      iii. NotificationService → Notifica usuário
5. SyncService → Atualiza DataConnection (last_sync, next_sync)
```

**Responsabilidades:**
- **Cron Job**: Agendar sincronizações
- **SyncService**: Orquestrar syncs
- **SyncWorker**: Executar sync em background
- **ConnectionService**: Conectar e descobrir schema
- **Connector**: Driver específico do banco

**Validações:**
- Conexão existe e está ativa
- Credenciais válidas
- Timeout não excedido (5min)

**Erros Possíveis:**
- `CONNECTION_FAILED`: Não foi possível conectar
- `AUTHENTICATION_FAILED`: Credenciais inválidas
- `TIMEOUT`: Operação excedeu tempo limite
- `SCHEMA_DISCOVERY_FAILED`: Erro ao descobrir schema

---

### 6.5 Fluxo de Aplicação de Template

**Descrição:** Aplicar template a um dashboard existente

**Diagrama Textual:**
```
1. Cliente → POST /api/v1/templates/:id/apply {dashboardId, position}
2. API → TemplateService.apply_template()
3. TemplateService → TemplateRepository.find_by_id()
4. TemplateService → DashboardRepository.find_by_id()
5. TemplateService → Valida acesso ao dashboard
6. TemplateService → Para cada widget no template:
   a. Ajusta posição relativa ao viewport
   b. Cria Widget com dados do template
   c. WidgetRepository.create()
7. TemplateService → Retorna lista de widgets criados
8. API → Retorna {widgets}
```

**Responsabilidades:**
- **TemplateService**: Lógica de aplicação
- **TemplateRepository**: Buscar template
- **DashboardRepository**: Buscar dashboard
- **WidgetRepository**: Criar widgets

**Validações:**
- Template existe
- Dashboard existe e usuário tem acesso
- Estrutura de widgets válida

**Erros Possíveis:**
- `TEMPLATE_NOT_FOUND`: Template não existe
- `DASHBOARD_NOT_FOUND`: Dashboard não existe
- `ACCESS_DENIED`: Sem acesso ao dashboard
- `INVALID_TEMPLATE`: Estrutura inválida

---

### 6.6 Fluxo de Compartilhamento de Dashboard

**Descrição:** Compartilhar dashboard com outros usuários

**Diagrama Textual:**
```
1. Cliente → POST /api/v1/workspaces/:id/members {userId, role}
2. API → WorkspaceService.add_member()
3. WorkspaceService → Valida que usuário atual é owner/admin
4. WorkspaceService → Valida que usuário a adicionar existe
5. WorkspaceService → WorkspaceMemberRepository.create()
6. WorkspaceService → PermissionService.validate_dashboard_access()
   a. Verifica se usuário tem acesso às conexões usadas no dashboard
   b. Se não → Retorna erro
7. Se válido:
   a. NotificationService → Envia notificação ao novo membro
   b. WorkspaceService → Retorna member criado
```

**Responsabilidades:**
- **WorkspaceService**: Lógica de compartilhamento
- **PermissionService**: Validar acesso a conexões
- **NotificationService**: Notificar usuários

**Validações:**
- Usuário atual tem permissão (owner/admin)
- Usuário a adicionar existe
- Usuário não é já membro
- Novo membro tem acesso às conexões necessárias

**Erros Possíveis:**
- `ACCESS_DENIED`: Sem permissão para adicionar membros
- `USER_NOT_FOUND`: Usuário não existe
- `ALREADY_MEMBER`: Usuário já é membro
- `INSUFFICIENT_PERMISSIONS`: Novo membro não tem acesso às conexões

---

## 7. Módulo de Integração / Third-Party Integrations

### 7.1 Arquitetura de Connectors

**Interface Base:**
```python
class BaseConnector(ABC):
    @abstractmethod
    async def connect(self, config: dict) -> Connection:
        """Estabelece conexão"""
        pass
    
    @abstractmethod
    async def test_connection(self, config: dict) -> ConnectionTestResult:
        """Testa conectividade"""
        pass
    
    @abstractmethod
    async def discover_schema(self, connection: Connection) -> SchemaMetadata:
        """Descobre schema (tabelas, colunas)"""
        pass
    
    @abstractmethod
    async def execute_query(self, connection: Connection, query: str, params: dict) -> QueryResult:
        """Executa query"""
        pass
    
    @abstractmethod
    async def close(self, connection: Connection) -> None:
        """Fecha conexão"""
        pass
```

### 7.2 Connectors Implementados

#### 7.2.1 PostgreSQL Connector

**Config Schema:**
```json
{
  "host": "string (required)",
  "port": "number (default: 5432)",
  "database": "string (required)",
  "username": "string (required)",
  "password": "string (required)",
  "ssl": "boolean (default: false)",
  "schema": "string (default: public)"
}
```

**Implementação:**
- Usa `asyncpg` para conexões assíncronas
- Pool de conexões (max 10 por connection_id)
- Timeout: 30s
- Query sanitization com parameterized queries

**Schema Discovery:**
```sql
-- Lista tabelas
SELECT table_name, table_schema 
FROM information_schema.tables 
WHERE table_schema = $1;

-- Lista colunas
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = $1 AND table_name = $2;
```

---

#### 7.2.2 MySQL Connector

**Config Schema:**
```json
{
  "host": "string (required)",
  "port": "number (default: 3306)",
  "database": "string (required)",
  "username": "string (required)",
  "password": "string (required)",
  "ssl": "boolean (default: false)"
}
```

**Implementação:**
- Usa `aiomysql` para conexões assíncronas
- Pool de conexões
- Timeout: 30s

---

#### 7.2.3 MongoDB Connector

**Config Schema:**
```json
{
  "connectionString": "string (required)",
  "database": "string (required)",
  "authSource": "string (optional)"
}
```

**Implementação:**
- Usa `motor` (async MongoDB driver)
- Descobre collections e documentos
- Suporta queries agregadas

---

#### 7.2.4 Google Sheets Connector

**Config Schema:**
```json
{
  "spreadsheetId": "string (required)",
  "credentials": "object (OAuth token or service account)",
  "sheetName": "string (optional)"
}
```

**Implementação:**
- Usa `gspread` com OAuth
- Descobre sheets e ranges
- Lê dados via API

---

#### 7.2.5 REST API Connector

**Config Schema:**
```json
{
  "baseUrl": "string (required)",
  "authType": "string (api_key | bearer | basic)",
  "apiKey": "string (if authType = api_key)",
  "bearerToken": "string (if authType = bearer)",
  "username": "string (if authType = basic)",
  "password": "string (if authType = basic)",
  "endpoints": "array (optional)"
}
```

**Implementação:**
- Usa `httpx` (async HTTP client)
- Descobre endpoints disponíveis
- Suporta GET, POST, PUT, DELETE

---

### 7.3 Connector Registry

**Estrutura:**
```python
class ConnectorRegistry:
    _connectors: Dict[str, Type[BaseConnector]] = {
        "postgresql": PostgreSQLConnector,
        "mysql": MySQLConnector,
        "mongodb": MongoDBConnector,
        "google-sheets": GoogleSheetsConnector,
        "rest-api": RESTAPIConnector
    }
    
    def get_connector(self, connector_id: str) -> Type[BaseConnector]:
        return self._connectors[connector_id]
    
    def list_connectors(self) -> List[ConnectorDefinition]:
        return [
            {
                "id": id,
                "name": connector.name,
                "category": connector.category,
                "configSchema": connector.config_schema
            }
            for id, connector in self._connectors.items()
        ]
```

### 7.4 Testes de Conectividade

**Fluxo:**
```
1. ConnectionService.test_connection()
2. Connector.test_connection(config)
3. Tenta conectar com timeout (5s)
4. Se sucesso:
   a. Mede latência
   b. Retorna {success: true, latency: ms}
5. Se falha:
   a. Captura erro
   b. Retorna {success: false, message: error}
```

### 7.5 Reconexão Automática

**Estratégia:**
- Pool de conexões com retry automático
- Backoff exponencial (1s, 2s, 4s, 8s)
- Máximo 3 tentativas
- Log de falhas para debugging

### 7.6 Logs Técnicos

**Informações Logadas:**
- Tentativas de conexão (sucesso/falha)
- Queries executadas (sem dados sensíveis)
- Tempo de execução
- Erros e stack traces
- Métricas de performance

---

## 8. Cache + Performance + Otimizações

### 8.1 Estratégia de Cache com Redis

**Estrutura de Chaves:**
```
user:{user_id}:permissions          # TTL: 15min
workspace:{workspace_id}:members    # TTL: 10min
connection:{connection_id}:metadata # TTL: 1h
widget:{widget_id}:data            # TTL: 5min
template:{template_id}              # TTL: 24h
ai:query:{hash}:response           # TTL: 1h (cache de respostas similares)
```

### 8.2 Cache por Tipo de Dado

#### 8.2.1 Metadados de Conexão
- **Chave:** `connection:{connection_id}:metadata`
- **TTL:** 1 hora
- **Invalidação:** On sync, on connection update
- **Conteúdo:** Tabelas, schemas, colunas

#### 8.2.2 Dados de Widgets
- **Chave:** `widget:{widget_id}:data`
- **TTL:** 5 minutos
- **Invalidação:** On refresh, on connection sync
- **Conteúdo:** Dados do widget (resultado de query)

#### 8.2.3 Permissões
- **Chave:** `user:{user_id}:permissions:{resource_type}:{resource_id}`
- **TTL:** 15 minutos
- **Invalidação:** On permission change
- **Conteúdo:** Boolean (tem permissão ou não)

#### 8.2.4 Templates
- **Chave:** `template:{template_id}`
- **TTL:** 24 horas
- **Invalidação:** On template update
- **Conteúdo:** Template completo

#### 8.2.5 Respostas de IA
- **Chave:** `ai:query:{hash(question+knowledge)}:response`
- **TTL:** 1 hora
- **Invalidação:** Manual (quando necessário)
- **Conteúdo:** Resposta completa da IA

### 8.3 Invalidação de Cache

**Estratégias:**
1. **Cache Invalidation on Write:** Invalida imediatamente ao atualizar
2. **TTL Automático:** Expira após TTL
3. **Manual:** Via API `/api/v1/cache/invalidate`

**Implementação:**
```python
async def invalidate_cache(pattern: str):
    keys = await redis.keys(pattern)
    if keys:
        await redis.delete(*keys)
```

### 8.4 Otimizações de Queries

#### 8.4.1 Índices
- Todos os foreign keys indexados
- Índices compostos para queries frequentes
- Índices parciais para soft deletes

#### 8.4.2 Eager Loading
- Carregar relacionamentos necessários em uma query
- Evitar N+1 queries

#### 8.4.3 Paginação
- Todas as listagens paginadas (default: 20 itens)
- Cursor-based pagination para grandes datasets

#### 8.4.4 Query Optimization
- Análise de slow queries (log queries > 1s)
- Uso de EXPLAIN para otimizar
- Limite de resultados (max 10.000 rows)

### 8.5 Lazy Loading

**Implementação:**
- Carregar dados apenas quando necessário
- Widget data carregado sob demanda
- Metadata de conexão carregado apenas quando acessado

### 8.6 Estratégia de Fallback

**Cache Miss:**
1. Tenta buscar do cache
2. Se miss → Busca do banco
3. Armazena no cache
4. Retorna dados

**Database Failure:**
1. Tenta buscar do cache (dados antigos)
2. Se cache miss → Retorna erro
3. Log erro para monitoramento

---

## 9. Filas e Processamento Assíncrono

### 9.1 Escolha de Tecnologia

**Decisão: Celery com Redis Broker**

**Justificativa:**
- Mature e battle-tested
- Suporta retry, priority, scheduling
- Integração fácil com FastAPI
- Redis já usado para cache

**Alternativa Considerada:** RQ (Redis Queue)
- Mais simples, mas menos features
- Adequado para MVP, mas Celery é melhor para escala

### 9.2 Estrutura de Filas

**Filas Principais:**
- `sync`: Sincronizações de conexões
- `ai`: Processamento de IA
- `email`: Envio de emails
- `file`: Processamento de arquivos
- `webhook`: Entrega de webhooks

### 9.3 Jobs Definidos

#### 9.3.1 Sync Jobs

**Job:** `sync_connection_metadata`
```python
@celery.task(name='sync_connection_metadata')
def sync_connection_metadata(connection_id: str):
    # Sync metadata
    pass
```

**Configuração:**
- Retry: 3 tentativas
- Backoff: Exponencial (60s, 120s, 240s)
- Timeout: 5 minutos
- Priority: Normal

---

#### 9.3.2 AI Jobs

**Job:** `process_ai_query`
```python
@celery.task(name='process_ai_query')
def process_ai_query(query_id: str):
    # Process AI query
    pass
```

**Configuração:**
- Retry: 2 tentativas
- Backoff: Exponencial (30s, 60s)
- Timeout: 2 minutos
- Priority: High

---

#### 9.3.3 Email Jobs

**Job:** `send_email`
```python
@celery.task(name='send_email')
def send_email(to: str, subject: str, body: str):
    # Send email
    pass
```

**Configuração:**
- Retry: 5 tentativas
- Backoff: Exponencial (10s, 20s, 40s, 80s, 160s)
- Timeout: 30 segundos
- Priority: Low

---

#### 9.3.4 File Jobs

**Job:** `process_file_upload`
```python
@celery.task(name='process_file_upload')
def process_file_upload(file_id: str):
    # Parse CSV/Excel
    pass
```

**Configuração:**
- Retry: 2 tentativas
- Backoff: Exponencial (30s, 60s)
- Timeout: 5 minutos
- Priority: Normal

---

### 9.4 Workers

**Workers Separados:**
- `sync_worker`: Apenas jobs de sync (1 worker)
- `ai_worker`: Apenas jobs de IA (2 workers)
- `email_worker`: Apenas emails (1 worker)
- `file_worker`: Apenas arquivos (1 worker)
- `general_worker`: Outros jobs (1 worker)

**Configuração:**
```bash
celery -A app.workers worker -Q sync -n sync_worker@%h
celery -A app.workers worker -Q ai -n ai_worker@%h -c 2
celery -A app.workers worker -Q email -n email_worker@%h
celery -A app.workers worker -Q file -n file_worker@%h
celery -A app.workers worker -Q default -n general_worker@%h
```

### 9.5 Retry Logic

**Estratégia:**
- Backoff exponencial
- Máximo de tentativas por tipo de job
- Dead letter queue após esgotar tentativas

**Implementação:**
```python
@celery.task(bind=True, max_retries=3)
def my_task(self, arg):
    try:
        # Task logic
        pass
    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
```

### 9.6 Dead Letter Queue

**Configuração:**
- Jobs que falharam após todas as tentativas
- Armazenados em fila `dlq` (dead letter queue)
- Logged para análise
- Notificação para admins

### 9.7 Monitoramento de Filas

**Métricas:**
- Tamanho das filas
- Taxa de processamento (jobs/segundo)
- Taxa de falhas
- Tempo médio de processamento
- Jobs em dead letter queue

**Ferramentas:**
- Flower (Celery monitoring)
- Prometheus metrics
- Grafana dashboards

---

## 10. Segurança Completa

### 10.1 Autenticação JWT

**Implementação:**
```python
def create_access_token(data: dict, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm="HS256")

def create_refresh_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=7)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm="HS256")
```

**Configuração:**
- Access token: 15 minutos
- Refresh token: 7 dias
- Algoritmo: HS256
- Secret key: Variável de ambiente (mínimo 32 caracteres)

**Token Blacklist:**
- Redis para blacklist de tokens
- Chave: `blacklist:{token_jti}`
- TTL: Tempo restante do token
- Verificado em cada request autenticado

---

### 10.2 Password Hashing

**Implementação:**
```python
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)
```

**Configuração:**
- Algoritmo: bcrypt
- Salt rounds: 10
- Nunca armazenar senha em plain text

---

### 10.3 RBAC Implementation

**Roles:**
- `admin`: Acesso total
- `user`: Acesso aos próprios recursos
- `viewer`: Apenas leitura

**Workspace Roles:**
- `owner`: CRUD completo, gerenciar membros
- `admin`: CRUD completo, gerenciar membros
- `member`: Criar dashboards, editar widgets
- `viewer`: Apenas visualização

**Crew Roles:**
- `commander`: Gerenciar crew, definir permissões
- `navigator`: Acesso a conexões do crew
- `explorer`: Acesso limitado
- `guest`: Apenas visualização

**Implementação:**
```python
def require_role(allowed_roles: List[str]):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            user = get_current_user()
            if user.role not in allowed_roles:
                raise HTTPException(403, "Insufficient permissions")
            return await func(*args, **kwargs)
        return wrapper
    return decorator
```

---

### 10.4 Input Validation

**Pydantic Schemas:**
```python
from pydantic import BaseModel, EmailStr, validator

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v
    
    @validator('name')
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError('Name cannot be empty')
        return v.strip()
```

**Validações Aplicadas:**
- Tipos de dados
- Formatos (email, URL, etc.)
- Tamanhos (min/max length)
- Valores permitidos (enums)
- Regras de negócio

---

### 10.5 SQL Injection Prevention

**Estratégias:**
1. **Parameterized Queries:** Sempre usar placeholders
2. **ORM:** SQLAlchemy previne injection automaticamente
3. **Whitelist:** Validar tabelas/colunas permitidas
4. **Query Complexity Limits:** Limitar joins, subqueries

**Exemplo:**
```python
# ❌ ERRADO
query = f"SELECT * FROM {table_name} WHERE id = {user_id}"

# ✅ CORRETO
query = "SELECT * FROM users WHERE id = :user_id"
params = {"user_id": user_id}
```

---

### 10.6 XSS Prevention

**Estratégias:**
1. **Sanitização:** Limpar HTML/JavaScript de inputs
2. **Output Encoding:** Escapar caracteres especiais
3. **CSP Headers:** Content Security Policy
4. **Validação:** Rejeitar conteúdo suspeito

**Implementação:**
```python
from markupsafe import escape

def sanitize_input(text: str) -> str:
    return escape(text)
```

---

### 10.7 CSRF Protection

**Estratégias:**
1. **SameSite Cookies:** `SameSite=Strict`
2. **CSRF Tokens:** Para operações críticas (futuro)
3. **Origin Validation:** Verificar Origin header

---

### 10.8 Rate Limiting

**Implementação com Redis:**
```python
async def rate_limit(key: str, limit: int, window: int) -> bool:
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, window)
    return current <= limit
```

**Limites por Endpoint:**
- Login: 5/minuto por IP
- AI Queries: 10/minuto por usuário
- API Calls: 100/minuto por usuário
- Upload: 5/minuto por usuário

**Headers de Resposta:**
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 99
X-RateLimit-Reset: 1609459200
Retry-After: 60
```

---

### 10.9 Encryption

**Credenciais de Conexão:**
- Criptografadas com AES-256 antes de armazenar
- Chave de criptografia em variável de ambiente
- Rotação de chaves periódica

**Implementação:**
```python
from cryptography.fernet import Fernet

def encrypt_credentials(data: dict) -> str:
    key = os.getenv("ENCRYPTION_KEY")
    f = Fernet(key)
    return f.encrypt(json.dumps(data).encode())

def decrypt_credentials(encrypted: str) -> dict:
    key = os.getenv("ENCRYPTION_KEY")
    f = Fernet(key)
    return json.loads(f.decrypt(encrypted))
```

---

### 10.10 Audit Logging

**Eventos Auditados:**
- Login/logout
- Criação/edição/deleção de recursos críticos
- Acessos a dados sensíveis
- Mudanças de permissões
- Ações administrativas

**Estrutura do Log:**
```json
{
  "timestamp": "2025-01-15T10:30:00Z",
  "user_id": "user-id",
  "action": "dashboard.created",
  "resource_type": "dashboard",
  "resource_id": "dashboard-id",
  "ip_address": "192.168.1.1",
  "user_agent": "Mozilla/5.0...",
  "metadata": {}
}
```

**Armazenamento:**
- Tabela `audit_logs` no PostgreSQL
- Retenção: 1 ano
- Índices: user_id, action, timestamp

---

## 11. Observabilidade (Monitoramento)

### 11.1 Logging Estruturado

**Formato JSON:**
```python
import structlog

logger = structlog.get_logger()

logger.info(
    "request_completed",
    method="POST",
    path="/api/v1/dashboards",
    status_code=201,
    duration_ms=45,
    user_id="user-id",
    request_id="request-id"
)
```

**Níveis:**
- `DEBUG`: Informações detalhadas (dev only)
- `INFO`: Informações gerais
- `WARNING`: Avisos
- `ERROR`: Erros
- `CRITICAL`: Erros críticos

**Campos Padrão:**
- `timestamp`: ISO 8601
- `level`: Log level
- `message`: Mensagem
- `request_id`: ID único da request
- `user_id`: ID do usuário (se autenticado)
- `ip_address`: IP do cliente

---

### 11.2 Métricas

**Métricas Coletadas:**

**Performance:**
- `http_request_duration_seconds` (histogram)
- `http_requests_total` (counter)
- `database_query_duration_seconds` (histogram)
- `cache_hit_rate` (gauge)

**Erros:**
- `http_errors_total` (counter, por status code)
- `database_errors_total` (counter)
- `cache_errors_total` (counter)

**Business:**
- `users_total` (gauge)
- `workspaces_total` (gauge)
- `dashboards_total` (gauge)
- `ai_queries_total` (counter)
- `connections_total` (gauge)

**Infrastructure:**
- `queue_size` (gauge, por fila)
- `queue_processing_time` (histogram)
- `redis_connections` (gauge)

**Exposição:**
- Endpoint `/metrics` (Prometheus format)
- Coletado a cada 15 segundos

---

### 11.3 Health Checks

**Endpoints:**

**GET /health:**
- Verifica se aplicação está rodando
- Sem dependências

**GET /ready:**
- Verifica dependências (DB, Redis)
- Retorna 503 se não pronto

**GET /live:**
- Verifica se processo está vivo
- Usado por Kubernetes liveness probe

**Implementação:**
```python
@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/ready")
async def ready():
    db_ok = await check_database()
    redis_ok = await check_redis()
    if db_ok and redis_ok:
        return {"status": "ready"}
    raise HTTPException(503, "Not ready")
```

---

### 11.4 Error Tracking

**Sentry Integration:**
```python
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    integrations=[FastApiIntegration()],
    traces_sample_rate=0.1
)
```

**Informações Capturadas:**
- Stack traces
- Request context
- User context
- Breadcrumbs
- Tags (environment, version)

---

### 11.5 APM Básico

**Métricas de Performance:**
- Response time por endpoint (p50, p95, p99)
- Throughput (requests/segundo)
- Database query time
- Cache hit rate
- Queue processing time

**Dashboards:**
- Grafana para visualização
- Alertas configurados

---

## 12. Deployment e Infraestrutura

### 12.1 Docker

**Dockerfile:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Docker Compose:**
```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/dbname
      - REDIS_URL=redis://redis:6379
    depends_on:
      - db
      - redis
  
  db:
    image: postgres:14
    environment:
      - POSTGRES_DB=dbname
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
    volumes:
      - postgres_data:/var/lib/postgresql/data
  
  redis:
    image: redis:7-alpine
  
  worker:
    build: .
    command: celery -A app.workers worker -l info
    depends_on:
      - db
      - redis

volumes:
  postgres_data:
```

---

### 12.2 CI/CD Básico

**GitHub Actions Workflow:**
```yaml
name: CI/CD

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pytest
  
  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build Docker image
        run: docker build -t app:latest .
  
  deploy-staging:
    needs: build
    if: github.ref == 'refs/heads/develop'
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to staging
        run: |
          # Deploy logic
  
  deploy-production:
    needs: build
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to production
        run: |
          # Deploy logic
```

---

### 12.3 Ambientes

**Development:**
- Local com Docker Compose
- Database local
- Redis local
- Logs no console
- Debug mode ativado

**Staging:**
- Similar a produção
- Dados de teste
- Monitoramento básico
- Deploy automático do branch `develop`

**Production:**
- Infraestrutura cloud (AWS/GCP/Azure)
- Database gerenciado
- Redis cluster
- Monitoramento completo
- Deploy manual com aprovação

---

### 12.4 Variáveis de Ambiente

**Arquivo `.env.example`:**
```env
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/dbname

# Redis
REDIS_URL=redis://localhost:6379

# Security
SECRET_KEY=your-secret-key-here-min-32-chars
ENCRYPTION_KEY=your-encryption-key-here

# JWT
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# CORS
CORS_ORIGINS=http://localhost:3000,http://localhost:3001

# Sentry
SENTRY_DSN=your-sentry-dsn

# Storage
STORAGE_TYPE=s3
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
AWS_S3_BUCKET=your-bucket

# Email
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=user
SMTP_PASSWORD=pass
```

---

### 12.5 Secrets Management

**Desenvolvimento:**
- Arquivo `.env` (não commitado)
- `.env.example` no repo

**Produção:**
- AWS Secrets Manager ou
- HashiCorp Vault ou
- Variáveis de ambiente do provedor cloud

---

### 12.6 Database Migrations

**Alembic:**
```bash
# Criar migration
alembic revision --autogenerate -m "create users table"

# Aplicar migrations
alembic upgrade head

# Reverter migration
alembic downgrade -1
```

**No CI/CD:**
- Migrations executadas automaticamente no deploy
- Rollback automático em caso de falha

---

### 12.7 Rollback Strategy

**Estratégia:**
1. Manter últimas 3 versões de imagens Docker
2. Database migrations reversíveis
3. Blue-green deployment (futuro)
4. Health checks antes de considerar deploy bem-sucedido

**Processo:**
1. Deploy nova versão
2. Health check
3. Se falhar → Rollback automático
4. Se sucesso → Marcar como estável

---

## 13. Plano de Implementação em Etapas (Roadmap Técnico)

### 13.1 Fase 1: Fundação (Semanas 1-4)

**Objetivo:** Infraestrutura básica e autenticação

**Entregas:**
- [ ] Setup do projeto (FastAPI, estrutura de pastas)
- [ ] Configuração do banco de dados (PostgreSQL, migrations)
- [ ] Configuração do Redis
- [ ] Modelos de dados básicos (User, Workspace, RefreshToken)
- [ ] AuthenticationService completo
- [ ] Endpoints de autenticação (login, logout, refresh, me)
- [ ] Middleware de autenticação
- [ ] Testes unitários básicos
- [ ] Docker e Docker Compose
- [ ] CI/CD básico

**Dependências:** Nenhuma

**Estimativa:** 4 semanas (1 desenvolvedor)

**Critérios de Aceite:**
- Usuário pode fazer login e obter tokens
- Tokens são validados corretamente
- Refresh token funciona
- Testes passando (>80% coverage)

---

### 13.2 Fase 2: Core Features (Semanas 5-8)

**Objetivo:** Workspaces, Dashboards e Widgets

**Entregas:**
- [ ] Modelos: Workspace, WorkspaceMember, Dashboard, Widget
- [ ] WorkspaceService completo
- [ ] DashboardService completo
- [ ] WidgetService completo
- [ ] Endpoints de workspaces (CRUD, membros)
- [ ] Endpoints de dashboards (CRUD)
- [ ] Endpoints de widgets (CRUD, data, refresh)
- [ ] PermissionService básico
- [ ] Cache básico (Redis)
- [ ] Testes de integração

**Dependências:** Fase 1

**Estimativa:** 4 semanas (1-2 desenvolvedores)

**Critérios de Aceite:**
- Usuário pode criar workspaces
- Usuário pode criar dashboards
- Usuário pode adicionar widgets
- Permissões básicas funcionando
- Cache funcionando

---

### 13.3 Fase 3: Conexões e Integrações (Semanas 9-12)

**Objetivo:** Conexões de dados e connectors

**Entregas:**
- [ ] Modelos: DataConnection, ConnectionMetadata
- [ ] BaseConnector interface
- [ ] PostgreSQL connector
- [ ] MySQL connector
- [ ] MongoDB connector (opcional)
- [ ] ConnectionService completo
- [ ] SyncService completo
- [ ] Endpoints de conexões (CRUD, test, sync, metadata)
- [ ] Celery workers (sync)
- [ ] Testes de conectividade

**Dependências:** Fase 2

**Estimativa:** 4 semanas (1-2 desenvolvedores)

**Critérios de Aceite:**
- Usuário pode criar conexões
- Conexões são testadas
- Metadados são sincronizados
- Sync funciona em background

---

### 13.4 Fase 4: IA e Pipeline (Semanas 13-16)

**Objetivo:** Integração com IA (mockada)

**Entregas:**
- [ ] Modelos: AIQuery, AIHistory, Pipeline, PipelineStep
- [ ] MockAIService completo
- [ ] AIService com pipeline
- [ ] AIWorker (Celery)
- [ ] Endpoints de IA (query, chat, history, pipeline)
- [ ] Cache de respostas de IA
- [ ] Testes do pipeline

**Dependências:** Fase 3

**Estimativa:** 4 semanas (1-2 desenvolvedores)

**Critérios de Aceite:**
- Usuário pode fazer perguntas
- Pipeline processa perguntas (mockado)
- Histórico é salvo
- Cache funciona

---

### 13.5 Fase 5: Features Avançadas (Semanas 17-20)

**Objetivo:** Templates, Spaces, Crews, Permissões avançadas

**Entregas:**
- [ ] Modelos: Template, Space, Crew, CrewMember, ConnectionPermission
- [ ] TemplateService completo
- [ ] SpaceService completo
- [ ] CrewService completo
- [ ] PermissionService avançado
- [ ] Endpoints de templates
- [ ] Endpoints de spaces e crews
- [ ] Endpoints de permissões
- [ ] Upload de arquivos
- [ ] FileUploadService

**Dependências:** Fase 4

**Estimativa:** 4 semanas (2 desenvolvedores)

**Critérios de Aceite:**
- Templates podem ser aplicados
- Spaces e crews funcionam
- Permissões granulares funcionando
- Upload de arquivos funciona

---

### 13.6 Fase 6: Produção (Semanas 21-24)

**Objetivo:** Preparar para produção

**Entregas:**
- [ ] Logging estruturado completo
- [ ] Métricas (Prometheus)
- [ ] Health checks
- [ ] Error tracking (Sentry)
- [ ] Rate limiting completo
- [ ] Security audit
- [ ] Performance optimization
- [ ] Load testing
- [ ] Documentação completa
- [ ] Runbooks

**Dependências:** Fase 5

**Estimativa:** 4 semanas (2 desenvolvedores)

**Critérios de Aceite:**
- Monitoramento completo
- Performance aceitável (p95 < 500ms)
- Segurança validada
- Documentação completa

---

### 13.7 Divisão por Squads (Recomendado)

**Squad Backend Core (2-3 devs):**
- Fases 1, 2, 3, 6
- Foco em infraestrutura e features core

**Squad Backend AI (1-2 devs):**
- Fase 4
- Foco em IA e pipeline

**Squad Backend Advanced (1-2 devs):**
- Fase 5
- Foco em features avançadas

---

### 13.8 Estimativas Macros

**Total de Esforço:**
- 24 semanas (6 meses)
- 2-3 desenvolvedores em média
- ~48-72 pessoa-semanas

**Breakdown:**
- Fase 1: 4 semanas
- Fase 2: 4 semanas
- Fase 3: 4 semanas
- Fase 4: 4 semanas
- Fase 5: 4 semanas
- Fase 6: 4 semanas

**Buffer:**
- +20% para imprevistos
- Total: ~29 semanas (7 meses)

---

## Conclusão

Este documento consolida todos os requisitos e especificações técnicas necessárias para implementar o backend completo da plataforma SaaS de Business Intelligence com IA.

**Principais Decisões:**
- Arquitetura: Monolito Modular
- Stack: Python + FastAPI
- Database: PostgreSQL + Redis
- Queue: Celery
- IA: Mockado inicialmente

**Próximos Passos:**
1. Revisar e aprovar este documento
2. Setup do repositório e estrutura inicial
3. Iniciar Fase 1 (Fundação)
4. Revisões semanais de progresso

**Manutenção:**
- Este documento deve ser atualizado conforme a implementação evolui
- Versões devem ser controladas
- Mudanças arquiteturais devem ser documentadas

---

**Documento gerado em:** 2025-01-15  
**Versão:** 1.0.0  
**Status:** Completo ✅


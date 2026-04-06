# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Development
uvicorn src.main:app --reload --port 8000

# Celery worker
celery -A src.workers.celery_app worker --loglevel=info

# Celery Beat (scheduled tasks)
celery -A src.workers.celery_app beat --loglevel=info

# Migrations
alembic upgrade head
alembic revision --autogenerate -m "description"

# Tests (71% coverage required)
pytest
pytest tests/path/to/test.py::test_function   # single test
pytest --cov=src --cov-report=html

# Linting/formatting
black src/
isort src/
```

## Architecture

**FastAPI** backend with async SQLAlchemy 2.0, Celery for background tasks, and Redis for caching/queue.

### Source Layout

```
src/
├── main.py                # FastAPI app, lifespan, middleware stack
├── api/v1/
│   ├── router.py          # Registers all 25+ route groups
│   └── *.py               # One file per domain (auth, planets, widgets, ai, ...)
├── models/                # SQLAlchemy models (22 files)
├── schemas/               # Pydantic v2 request/response models
├── services/              # Business logic layer (29 services)
├── repositories/          # Data access layer (20+ files, async queries)
├── workers/
│   ├── celery_app.py      # Celery config (Redis broker/backend)
│   ├── sync_worker.py     # Connection metadata sync
│   ├── ai_worker.py       # AI query processing + dashboard build jobs
│   └── cache_warming_worker.py
├── connectors/            # Database connectors (BigQuery, MySQL, Postgres)
├── ai/                    # HTTP client to sky-poc-ai service
├── config/
│   └── settings.py        # Pydantic settings, env var loading
└── core/
    ├── errors/            # Error handlers + custom exceptions
    ├── permissions.py     # RBAC utilities
    └── security.py        # JWT, password hashing
```

### Middleware Stack (execution order)

1. CORS
2. Correlation ID (request tracing)
3. Authentication (sets `request.state.user_id` from JWT)
4. Rate Limiting
5. Idempotency

All routes under `/api/v1`. Health/readiness at `/health`, `/ready`, `/live`. Metrics at `/metrics` (Prometheus).

### Request Flow

```
HTTP Request → Middleware stack → Route handler
    → Service layer (business logic)
        → Repository layer (async DB queries)
        → AI service client (for AI routes)
        → Celery (for async jobs)
```

### Key Patterns

**Service + Repository separation** — Services (`src/services/`) contain business logic and call repositories (`src/repositories/`) for DB access. Route handlers should only call services, never repositories directly.

**Async everywhere** — All DB operations use `AsyncSession`. Celery tasks use a separate sync session (`psycopg2`) when needed for LangGraph compatibility.

**Encrypted credentials** — Connection configs are stored AES-256 encrypted. `src/core/security.py` handles encryption/decryption.

**AI integration** — `src/ai/` contains an HTTP client that calls the AI service at `AI_SERVICE_URL` (default `:8001`). There's also a mock implementation for testing (`real_service.py` vs `mock.py`), controlled by `AI_SERVICE_TYPE` env var.

### Database Models (key ones)

- `User` — with Auth0 SSO metadata, invite system
- `Planet` — workspace container (personal or shared)
- `Dashboard` + `Widget` — canvas layout, 6 widget types (chart, KPI, table, AI-box, text, infographic)
- `Connection` — data source with encrypted config; supports Postgres, MySQL, MongoDB, BigQuery, Google Sheets
- `IntelligenceSignal` + `SignalEvent` — AI-detected alerts
- `Strategy` — strategic goals/OKRs
- `EnterpriseRelationship` / `EnterpriseApi` — B2B context graph data

All models use UUID PKs, soft deletes (`deleted_at`), and `created_at`/`updated_at` timestamps.

### Celery Tasks

| Task | Trigger | What it does |
|---|---|---|
| `sync_connection` | Manual | Syncs a data connection |
| `sync_connection_metadata` | Manual | Extracts table/column metadata from a connection |
| `process_ai_query` | On AI query | Async AI query processing |
| `build_dashboard_job` | On dashboard build | Generates dashboard widgets via Davinci plan |
| `warm_ai_response_cache` | Beat (every 60s) | Pre-warms AI response cache |

### Environment Variables

Key vars (see `src/config/settings.py` for all):

```bash
DATABASE_URL=postgresql+asyncpg://...
REDIS_HOST=...
AI_SERVICE_URL=http://localhost:8001
AI_SERVICE_TYPE=real   # or "mock"
AUTH0_DOMAIN=...
AUTH0_CLIENT_ID=...
ENCRYPTION_KEY=...      # AES-256 key for connection credentials
SECRET_KEY=...          # JWT signing key
```

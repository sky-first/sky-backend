# Projeto A — Multi-tenant runbook

End-to-end recipe for arrancar / operar o stack multi-tenant Model B
em local dev. Pre-requisitos: docker-compose com Postgres + Redis +
Celery a correr (`sky_poc_postgres`, `sky_poc_redis`,
`sky_poc_worker`, `sky_poc_beat` no `docker ps`).

## 1. Estado da migração

```bash
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db" \
  venv/Scripts/python.exe -m alembic current
```

Deve dizer `tenant_registry_20260526 (head)`. Se não estiver no head,
correr `alembic upgrade head`.

## 2. Seed dos tenants demo

```bash
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db" \
POSTGRES_PASSWORD=postgres \
  venv/Scripts/python.exe scripts/seed_tenants.py
```

Cria 2 rows no `tenant_registry` (`alpha` pilot, `beta` foundation).
Tenant DBs (`tenant_alpha`, `tenant_beta`) precisam de existir — criar
com:

```bash
docker exec sky_poc_postgres psql -U postgres -c "CREATE DATABASE tenant_alpha;"
docker exec sky_poc_postgres psql -U postgres -c "CREATE DATABASE tenant_beta;"
```

Para remover os seeds:

```bash
venv/Scripts/python.exe scripts/seed_tenants.py remove
```

## 2.5. Bootstrap dos tenant DBs (schema + admin user)

Cada tenant precisa de schema + um admin user antes de poder ser
usado. Em prod o `new-client.sh` (PR #586 sky-infra) trata disto; em
local:

```bash
# Aplicar schema (idealmente alembic; se pgvector não estiver instalado,
# clonar via pg_dump — ver fallback no docstring do bootstrap_tenant.py)
docker exec sky_poc_postgres pg_dump -U postgres --schema-only \
  --no-owner --no-acl -d ai_saas_db | grep -v 'EXTENSION.*vector' \
  | docker exec -i sky_poc_postgres psql -U postgres -d tenant_alpha
docker exec sky_poc_postgres psql -U postgres -d tenant_alpha -c \
  "INSERT INTO alembic_version VALUES ('tenant_registry_20260526');"

# Criar admin user
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db \
POSTGRES_PASSWORD=postgres \
TENANT_DB_URL_TEMPLATE=postgresql+asyncpg://postgres:postgres@localhost:5432/{db_name} \
  venv/Scripts/python.exe scripts/bootstrap_tenant.py alpha \
    --admin-email admin@alpha-demo.example.com
```

Default password: `ChangeMe!2026`. Override com `--admin-password`.

Repetir para `beta` (ou qualquer outro slug seeded).

## 3. Arrancar o backend com flag ON

```bash
cd sky-poc-backend
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db" \
POSTGRES_PASSWORD=postgres \
MULTI_TENANT_ENABLED=true \
TENANT_DB_URL_TEMPLATE="postgresql+asyncpg://postgres:postgres@localhost:5432/{db_name}" \
  venv/Scripts/python.exe -m uvicorn src.main:app --port 8000 --no-access-log
```

## 4. Arrancar sky-poc-ai com flag ON

```bash
cd sky-poc-ai
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db" \
MULTI_TENANT_ENABLED=true \
  venv/Scripts/python.exe run_api.py
```

## 5. Arrancar sky-poc-frontend

```bash
cd sky-poc-frontend
# Sem env var → host normal serve o tenant default
npm run dev

# Para simular um tenant em localhost:
NEXT_PUBLIC_TENANT_SLUG=alpha npm run dev
```

## 6. Validar end-to-end

```bash
cd sky-poc-backend
venv/Scripts/python.exe scripts/smoke_multi_tenant.py
```

Output esperado (com flag ON):

```
== 1. tenant-echo with default context ==
  [ OK  ] echo returned default slug (got 'default')
  [ OK  ] default context flagged is_default=True

== 2. tenant-echo with X-Tenant-Slug: alpha ==
  [ OK  ] echo returned alpha for X-Tenant-Slug: alpha (got 'alpha')
  [ OK  ] alpha resolved to its tier (got 'pilot')

== 3. tenant-echo with X-Tenant-Slug: beta ==
  [ OK  ] echo returned beta for X-Tenant-Slug: beta (got 'beta')
  [ OK  ] beta resolved to its tier (got 'foundation')

== 4. tenant-echo with subdomain (Host header) ==
  [ OK  ] subdomain workspace-alpha resolved to alpha (got 'alpha')

== 5. tenant-db-ping per tenant routes to its pool ==
  [ OK  ] alpha db-ping -> tenant:alpha pool (got 'tenant:alpha')
  [ OK  ] beta db-ping -> tenant:beta pool (got 'tenant:beta')
  [ OK  ] both tenants cached in connection manager

== 6. tenant-echo with unknown slug returns 404 ==
  [ OK  ] unknown slug correctly 404s

ALL CHECKS PASSED.
```

## 7. Endpoints úteis

| Endpoint | Para que serve |
|---|---|
| `GET /api/v1/_test/tenant-echo` | Mostra o `TenantContext` resolvido para a request |
| `GET /api/v1/_test/tenant-db-ping` | Faz `SELECT 1` na DB do tenant e diz que pool usou |

Ambos aceitam `X-Tenant-Slug` header ou subdomain `workspace-{slug}.…`.

## 8. Componentes implementados (resumo dos 15 PRs)

| PR | Onde | O que |
|---|---|---|
| #1 | sky-be | `tenant_registry` table + Tenant model |
| #2 | sky-be | `TenantResolverMiddleware` (no-op quando flag OFF) |
| #3 | sky-be | `TenantConnectionManager` + `get_tenant_db` |
| #4 | sky-be | Multi-tenant isolation fixture + static-analysis canaries |
| #5 | sky-be | `/api/v1/_test/tenant-echo` + `tenant-db-ping` |
| #6-7 | sky-be | `get_db_session` tenant-aware (migra 287 callers de uma vez) |
| #8 | sky-be | Celery signal propagation (before_publish / pre_run / post_run) |
| #9 | sky-ai | `AgentState.tenant_slug` + `X-Tenant-Slug` dependency |
| #10 | sky-ai | Bedrock per-tenant Application Inference Profile |
| #11 | sky-fe | Subdomain → slug + `X-Tenant-Slug` header on every API call |
| #12 | sky-fe | Zustand persist keys prefixadas com tenant slug |
| #13 | sky-be | `seed_tenants.py` + `smoke_multi_tenant.py` |
| #14 | sky-be | `tenant_guard.assert_tenant_scoped()` + `STRICT_TENANT_REQUIRED` setting |
| #15 | sky-be | Runbook (este documento) |

## 9. Próximos passos (não bloqueantes)

* Phase 3 cleanup: migrar os 12 callers diretos de `AsyncSessionLocal()`
  em `src/workers/*` para usarem `get_db_session_for_context()` ou
  `tenant_connection_manager.session_for(current_tenant())`. O lint
  baseline em `test_multi_tenant_isolation.py` baixa à medida que
  cada um for migrado.
* Habilitar `STRICT_TENANT_REQUIRED=true` no ambiente onde TODAS as
  rotas tiverem sido confirmadas. Em produção, fazer staged: primeiro
  staging por uma semana, depois prod.
* AWS Application Inference Profiles para tenants reais. Spec em
  `~/Downloads/SkyFirst-Docs/04-technical-specs/04-bedrock-multi-tenant-spec.md`.

## 10. Rollback

Se algo correr mal:

```bash
# 1. Backend: parar o uvicorn e re-arrancar com flag OFF
MULTI_TENANT_ENABLED=false venv/Scripts/python.exe -m uvicorn src.main:app --port 8000
```

A flag desligada faz com que o middleware nunca consulte o registry,
todos os requests caem no DEFAULT_TENANT_CONTEXT e o
`TenantConnectionManager` devolve a pool global. Zero mudanças de
comportamento — a plataforma volta ao single-tenant.

Se for preciso reverter a migration alembic:

```bash
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db" \
  venv/Scripts/python.exe -m alembic downgrade -1
```

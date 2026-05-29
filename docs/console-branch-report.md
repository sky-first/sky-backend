# Relatório de Branch — Console Interno SkyFirst

**Branch backend:** `feat/backend-aws-migration`  
**Branch frontend:** `feat/console-ux-professional`  
**Data:** 2026-05-29  
**Autor:** Kaique Mendonça / gustavo.mendonca@skyfirstlabs.com

---

## Contexto

Ligação do Console interno da SkyFirst (painel de gestão multi-tenant) a dados reais de infraestrutura — cluster EKS staging (eu-west-1), Prometheus, AWS Cost Explorer. A branch também inclui a migração do backend de Azure para AWS e o worker de provisionamento de tenants.

| Branch | Repositório | Commits à frente de staging |
|---|---|---|
| `feat/backend-aws-migration` | `sky-poc-backend` | 13 commits |
| `feat/console-ux-professional` | `sky-poc-frontend` | 5 commits |

---

## O que estava → O que está agora

### Backend

#### 1. Migração Azure → AWS

- **Antes:** backend configurado para Azure (ACR, AKS, Key Vault)
- **Agora:** AWS EKS (eu-west-1), ECR, Secrets Manager, Celery worker com queue `knowledge`

---

#### 2. Telemetria — de mock para dados reais

| Campo | Antes | Agora |
|---|---|---|
| CPU/memória dos nodes | `0%` — parser não tratava nanocores (`125286296n`) | `3–19%` reais do metrics-server EKS |
| Pods running | `0` — timeout silencioso no provider | `60` pods reais do namespace `staging` |
| Pod list do tenant | `[]` — namespace `skyfirst-stg` não existe | 6 pods reais: `ai`, `ai-worker`, `backend`, `frontend`, `migration` |
| Last deploy | `datetime.now()` hardcoded | SHA `e788839f38e6`, timestamp real do ArgoCD `operationState` |
| Latência P95 | `60 000ms` — preso no bucket máximo do histograma | `466ms` real do Prometheus, cap de SLA a `30 000ms` |
| Uptime API | `0%` | `86%` real via `probe_success` no Prometheus |
| Custo diário AWS | `$0` em todos os 30 dias — créditos AWS zeravam os valores | 21 dias com valores reais (`$0.02–$1.20/dia`) |
| Custo total | `-$0.0` — `AWS Data Transfer` credit cancelava EC2 | `$5.44` real do Cost Explorer |
| DB connections | `0/0` | `1/100` via query directa a `pg_stat_activity` |
| Revenue summary | `HTTP 503` — TODO explícito no provider | `$5.44` spend real; zeros para MRR (Moloni não integrado) |

---

#### 3. Resiliência por cluster

- **Antes:** 1 cluster em baixo → `TelemetryUnavailable` derrubava tudo (único `try/except` à volta do loop stg+prd)
- **Agora:** falha por cluster com `continue` — staging funciona mesmo com prod inacessível (private endpoint dentro da VPC)

---

#### 4. Bugs críticos corrigidos

| Bug | Impacto | Fix |
|---|---|---|
| `platform_health()` era `async` mas chamada sem `await` | Retornava coroutine, não dados | `inspect.isawaitable()` + `await` condicional nas rotas |
| `TenantBillingResponse.last_invoice_at` campo obrigatório mas API retornava `null` | HTTP 500 ao abrir aba Billing | Campo tornado `Optional[str] = None` |
| `AwsCostProvider.revenue_summary()` lançava `TelemetryUnavailable` intencionalmente | HTTP 503 derrubava páginas inteiras via `Promise.all` | Retorna zeros em vez de 503; gasta real derivado do CE |
| `_parse_cpu_cores()` não tratava sufixo `n` (nanocores) | `ValueError` silencioso → todos os nodes com `0%` CPU | Adicionado caso `n`: `float(qty[:-1]) / 1_000_000_000` |
| Worker Celery `provision_tenant_job_not_found` em loop | Jobs criados mas nunca executados | Bug de DB context — corrigido no `_provision_async` |

---

#### 5. Performance

| Endpoint | Antes | Depois |
|---|---|---|
| `GET /tenants/{slug}/health` | `3.8s` (3–4 chamadas K8s síncronas) | `25ms` (cache TTL 30s após 1ª chamada bem sucedida) |
| `GET /infra` (cluster nodes) | `~2s` | `<30ms` cached |

Cache não guarda resultados vazios — protege contra servir zeros quando o cluster está inacessível.

---

### Frontend

| Problema | Antes | Agora |
|---|---|---|
| Um endpoint a falhar derrubava a página inteira | `Promise.all` — qualquer 503/404 → ecrã de erro | `Promise.allSettled` — falha mostra zero, não quebra tudo |
| Datas de fatura `null` | Renderizava `1/1/1970` (`new Date(null)`) | Renderiza `—` quando `null` |
| Loading da aba Health | Quadrado branco vazio — parecia partido | Spinner + "A carregar dados do cluster…" |
| Redirect loop em 401 | Mensagem de erro sem status HTTP | Status sempre incluído; redirect correto para login |
| UX geral | Estados vazios ausentes, sem sign-out visível | Sign-out, empty states, loading polish |

---

## Validação — dados reais confirmados no browser

| Página | Dados visíveis e verificados |
|---|---|
| `/console` Overview | Spend MTD `$5`, gráfico diário real com curva, projeção `$6 EOM` |
| `/console/operations` | Uptime `86%`, pods `60`, DB `1/100`, latência `3219ms` |
| `/console/infra` | 4 nodes EKS staging com CPU e memória ao vivo (barras visuais) |
| `/console/tenants/skyfirst → Health` | 6 pods reais, SHA `e788839f38e6`, links ArgoCD + Grafana |
| `/console/tenants/skyfirst → Billing` | tier `strategic`, `€35 000/mês`, datas corretas |
| `/console/cost` | `$5.44` compute, gráfico com 21 dias não-zero |

Dados do Console comparados directamente com `kubectl` e `aws ce` — batem byte a byte.

---

## O que falta — Fluxo "Criar Tenant"

### Estado actual do fluxo

```
[1] POST /api/console/v1/tenants          ✅  OK
    Insere linha em tenant_registry
    Cria ProvisioningJob (PENDING)
    Dispara Celery task

[2] provisioning_worker.py                ❌  FALHA
    Chama bootstrap_tenant.py
    Tenta alembic upgrade head
    DB do tenant não existe → OperationalError

[3] Tenant fica ACTIVE, login funciona    🔒  Bloqueado por [2]
```

### Causa raiz

O `scripts/bootstrap_tenant.py` corre `alembic upgrade head` directamente contra a URL do tenant mas **não cria a base de dados PostgreSQL** antes. A DB `tenant_<slug>` tem de existir para o Alembic conseguir conectar.

### Ficheiros a alterar

#### `scripts/bootstrap_tenant.py` — adicionar `CREATE DATABASE` antes do Alembic

```python
# Inserir ANTES da chamada a _run_alembic_upgrade()
import psycopg2

def _create_tenant_db(tenant: Tenant) -> None:
    """Create the PostgreSQL database for the tenant if it doesn't exist."""
    conn = psycopg2.connect(
        host=tenant.db_host,
        port=tenant.db_port,
        dbname="postgres",           # connect to maintenance DB
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s", (tenant.db_name,)
    )
    if not cur.fetchone():
        cur.execute(f'CREATE DATABASE "{tenant.db_name}"')
        print(f"  [OK] created database {tenant.db_name!r}")
    else:
        print(f"  [OK] database {tenant.db_name!r} already exists")
    cur.close()
    conn.close()
```

#### `scripts/bootstrap_tenant.py` — instalar `pgvector` local (se dev)

As migrations `add_context_documents` e `add_knowledge_library_tables` fazem `CREATE EXTENSION IF NOT EXISTS vector`. No Postgres local sem pgvector, falham silenciosamente.

```bash
# macOS — instalar pgvector
brew install pgvector
# ou via psql
psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

#### `.env.local` — para produção apontar para RDS

```bash
# Trocar localhost:5432 pelo endpoint RDS da AWS
TENANT_DB_URL_TEMPLATE=postgresql+asyncpg://sky_admin:<password>@<rds-endpoint>.eu-west-1.rds.amazonaws.com:5432/{db_name}
```

### O que NÃO precisa de alteração

- Formulário `/console/tenants/new` — completo e funcional
- Endpoint `POST /api/console/v1/tenants` — cria registry + job correctamente
- `provisioning_worker.py` — o worker está correcto; falha porque o bootstrap falha
- Celery — a correr, queue `knowledge` activa, task recebida e processada

### Estimativa de esforço

| Tarefa | Esforço |
|---|---|
| Adicionar `CREATE DATABASE` no bootstrap | ~30 min |
| Instalar pgvector local + testar | ~15 min |
| Apontar `TENANT_DB_URL_TEMPLATE` para RDS | ~10 min (config) |
| SSO domain no Auth0/Google para o novo tenant | Depende do cliente |

---

## O que fica pendente por design (não bugs)

| Campo | Razão | Solução |
|---|---|---|
| Score / Agents / Sources / Context = 0% | Métricas de produto da DB do tenant — tenant sem actividade | Aumenta quando utilizadores criam agents/sources/queries |
| MRR / Gross Margin = €0 | Requer integração Moloni (billing) | Implementar `MoloniBillingProvider` |
| Cluster produção sem dados | Private endpoint EKS — só acessível dentro da VPC | Backend em produção na VPC tem acesso directo |
| SSO expiração horária do `kubectl proxy` | AWS SSO tokens duram ~1h | Backend em produção usa IRSA (não SSO pessoal) |

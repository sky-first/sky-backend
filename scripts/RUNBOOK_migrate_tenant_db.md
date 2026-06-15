# Runbook — migrar uma tenant DB (chat "rodando rodando")

> **Estado: PLANO. Nada aqui foi executado contra a DB live.**
> Preparado 2026-06-14. Requer autorização explícita do Lucas para os passos
> que escrevem (4 em diante).

## Causa-raiz

`tenant_gbtsolutions` **não tem** a migração `chat_sessions_20260609`:
- falta a tabela `chat_sessions` e a coluna `conversations.session_id`;
- por isso `GET /api/v1/pages/{page_id}/conversations` devolve **500**
  (`asyncpg UndefinedColumnError: column conversations.session_id does not exist`);
- o chat de thread nunca recebe a conversa → spinner "Sky is thinking…" eterno.

O **Migrate Job da plataforma só migra a PLATFORM DB**; as tenant DBs nunca são
migradas. Logo cada tenant DB tem de ser migrada à parte.

## O que precisa de ser aplicado

Cadeia sky-be (head atual): `password_reset_cols_20260614`
```
… → tenant_logo_url_20260603 → chat_sessions_20260609 → password_reset_cols_20260614 (head)
```
A tenant DB precisa de subir até **head**:
- `chat_sessions_20260609` — corrige o chat (a causa-raiz);
- `password_reset_cols_20260614` — colunas de reset de password (os users do
  tenant vivem na tenant DB, por isso esta também se aplica).

## Segurança do alembic partilhado (já resolvida)

sky-be e sky-ai partilhavam a tabela `alembic_version`. Isto **já está tratado**:
- `migrations/env.py` usa `version_table="alembic_version_be"` (linhas 84/123);
- `scripts/migrate_alembic_version_table.py` separa a linha do sky-be do
  `alembic_version` legado para `alembic_version_be`, **deixando as linhas do
  sky-ai intactas**;
- depois disto, `alembic upgrade head` (a partir do sky-be) ignora as revisões
  do sky-ai e aplica só as do sky-be.

É **exatamente** o que o Job de migração de staging faz contra a platform DB
(`sky-poc-infra/gitops/bootstrap/staging-aws/backend.yaml`, ~linha 278):
```
python scripts/migrate_alembic_version_table.py && alembic upgrade head
```
O plano abaixo corre o mesmo, mas com `DATABASE_URL` = tenant DB.

---

## Passo 0 — acesso ao cluster (read-only)

```bash
# Túnel SSM (ver memória skyfirst-staging-cluster-access)
export KUBECONFIG=C:/Users/paulo/.kube/stg-tunnel.yaml
export AWS_PROFILE=sky-staging
# (abrir o port-forward SSM para i-05746fe9a49777f1d conforme a memória)
kubectl --context stg-tunnel get pods -n <ns-sky-be>   # confirmar acesso
```

## Passo 1 — LER o estado atual da tenant DB (READ-ONLY, seguro)

Resolver a `DATABASE_URL` da `tenant_gbtsolutions` (host da platform RDS +
nome `tenant_gbtsolutions` + credenciais do secret do tenant; o
`TenantConnectionManager` usa `DEFAULT_TENANT_DB_*`). Depois, **só leituras**:

```sql
-- 1a. Estado alembic (as duas tabelas podem existir)
SELECT 'legacy' AS t, version_num FROM alembic_version
UNION ALL
SELECT 'be', version_num FROM alembic_version_be;   -- pode não existir ainda

-- 1b. Confirmar a causa-raiz: a coluna em falta
SELECT column_name FROM information_schema.columns
WHERE table_name='conversations' AND column_name='session_id';   -- esperado: 0 linhas

-- 1c. A tabela chat_sessions existe?
SELECT to_regclass('public.chat_sessions');   -- esperado: NULL
```

**Registar os resultados.** Decisão:
- Se `alembic_version_be` já = `chat_sessions_20260609` ou head **e** `session_id`
  já existe → a tenant já está migrada; o bug é outro → **PARAR** e reavaliar.
- Caso contrário → seguir para o Passo 4.

> Se o Passo 1b/1c confirmarem coluna/tabela em falta mas o alembic disser que já
> está em head, há *drift* — nesse caso aplicar o DDL manualmente (ver Anexo) em
> vez de `alembic upgrade`.

## Passo 2 — backup leve (recomendado)

A migração é aditiva (coluna nullable + tabela nova + backfill idempotente), mas
antes de escrever:
```bash
pg_dump --schema-only -t conversations -t chat_sessions "<tenant DB URL>" > /tmp/tenant_gbt_pre.sql
```

## Passo 3 — dry-run da separação alembic (sem upgrade)

`migrate_alembic_version_table.py` é idempotente e só mexe nas linhas do sky-be.
Correr primeiro **sem** o `alembic upgrade` e ler o output ("classified: N sky-be · M other",
"inserted X into alembic_version_be") para confirmar que vai semear a revisão certa.

## Passo 4 — APLICAR (precisa de autorização) — espelhar o Job da plataforma

**Forma preferida (mais segura): um Job one-off clonado do Migrate Job de staging**,
com `DATABASE_URL` sobreposta para a tenant DB — usa a imagem + env do deploy,
idêntico ao que já corre em produção contra a platform DB:

```
env: DATABASE_URL=<tenant_gbtsolutions URL>
command: ["/bin/sh","-c"]
args: ["python scripts/migrate_alembic_version_table.py && alembic upgrade head"]
```

Alternativa (exec direto num pod sky-be):
```bash
kubectl --context stg-tunnel exec -n <ns> deploy/sky-be -- /bin/sh -c \
  'DATABASE_URL="<tenant_gbtsolutions URL>" python scripts/migrate_alembic_version_table.py && \
   DATABASE_URL="<tenant_gbtsolutions URL>" alembic upgrade head'
```
> Se o Passo 1 mostrar que a tabela legada NÃO tem nenhuma revisão sky-be (só
> sky-ai), passar `--expected-head <rev sky-be atual da tenant>` ao script para
> semear `alembic_version_be` corretamente.

## Passo 5 — VERIFICAR (read-only)

```sql
SELECT version_num FROM alembic_version_be;          -- esperado: password_reset_cols_20260614
SELECT to_regclass('public.chat_sessions');          -- esperado: não-NULL
SELECT column_name FROM information_schema.columns
WHERE table_name='conversations' AND column_name='session_id';   -- esperado: 1 linha
```

## Passo 6 — verificação funcional

- Abrir o chat do GBT (`lucas.ventura@gbtsolutions.pt`).
- `GET /api/v1/pages/{id}/conversations` deve dar **200** (não 500).
- Escrever no chat → a mensagem + resposta renderizam (sem "rodando rodando").

## Passo 7 — generalizar

- Repetir Passos 1–6 para **cada** tenant DB (hoje só `tenant_gbtsolutions`).
- **Promote-to-prod:** adicionar um passo de migração **por-tenant** ao
  `promote-to-production.yml`, senão as tenant DBs de prod ficam com o mesmo chat
  partido.

## Rollback

`chat_sessions_20260609` tem `downgrade()` completo (dropa índice/FK/coluna e a
tabela). Como é aditivo, o risco é baixo. Em caso de problema:
```bash
DATABASE_URL="<tenant DB>" alembic downgrade tenant_logo_url_20260603
```

## Anexo — DDL manual (só se houver drift alembic vs schema)

Equivalente exato a `chat_sessions_20260609.upgrade()` (ver
`migrations/versions/chat_sessions_20260609.py`): `CREATE TABLE chat_sessions …`,
4 índices, `ALTER TABLE conversations ADD COLUMN session_id UUID`, FK
`conversations_session_id_fkey` (ON DELETE SET NULL), índice
`ix_conversations_session_id`, e o backfill (1 "Chat 1" por página com
conversas + `UPDATE conversations SET session_id`). Depois `alembic stamp` para
a head correta na `alembic_version_be`.
```

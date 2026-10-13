# Fontes do sistema — contrato da API (Consola) · v1 · 13/10/2026

Para quem constrói a secção «Fontes do sistema» em `/console/tenants/[slug]` e a página de catálogo `/console/fontes-sistema`. Desenho aprovado pelo Lucas a 13/10/2026 (4 decisões: ligação em todos os projectos; não conta como fonte do plano; quotas TomTom só na fase 2; cruzamento pelo merger multi-ligação).

**Base:** `/api/console/v1` · autenticação da Consola (JWT de membro da equipa Sky, host da Consola) · respostas JSON.

**Envelope de erro** (o de toda a API): `{"error": {"code": "NOT_FOUND"|"FORBIDDEN"|"CONFLICT"|…, "message": "…", "details": {"reason": "<código estável>", …}}}`. A UI decide por `error.details.reason`, nunca pela `message`.

**Interruptor:** com `FONTES_SISTEMA_ENABLED=false` (omissão) **todas** as rotas abaixo respondem `404` com `reason: "fontes_sistema_desligadas"`. A UI deve tratar este 404 como «secção escondida», não como erro.

## Estados

| Campo | Valores |
|---|---|
| `estado` (catálogo) | `rascunho` · `ativa` · `retirada` — só `ativa` se pode marcar |
| `estado` (cliente) | `nunca_ativada` · `a_preparar` · `pronta` · `erro` · `a_desligar` · `desligada` |
| `tipo` | `A` (tabelas em `sky_world`) · `B` (API ao vivo — **ainda não disponível**, aparece em `rascunho`) |
| `motivo_nao_ativavel` | `fonte_nao_ativa` · `sem_uso_comercial` · `tipo_nao_suportado` · `sem_tabelas` · `tabela_proibida` · `plano_nao_permite` · `null` |

Transições: marcar → `a_preparar` → `pronta` | `erro`. Desmarcar → `a_desligar` → `desligada` | `erro`. Fazer **poll** de `GET …/fontes-sistema/{fonte_id}` de 2 em 2 s enquanto o estado for `a_preparar` ou `a_desligar` (meta: < 60 s). Um `erro` mostra `erro.mensagem` (sem segredos) e permite «Tentar outra vez» = `POST …/reconciliar`.

## 1. Catálogo

`GET /api/console/v1/fontes-sistema` — qualquer membro da equipa Sky.

```json
{
  "frescura_disponivel": true,
  "fontes": [
    {
      "id": "combustivel_es",
      "nome": {"pt": "Combustível Espanha (MITECO)", "es": "…", "en": "…"},
      "descricao": {"pt": "…", "es": "…", "en": "…"},
      "tipo": "A",
      "estado": "ativa",
      "tabelas": ["gasolineras_precio", "gasoleo_historico_diario"],
      "licenca": "MITECO — reutilização (Lei 37/2007, RD 1495/2011)",
      "atribuicao": {"pt": "Fuente: Ministerio para la Transición Ecológica"},
      "uso_comercial": true,
      "cadencia_min": 30,
      "planos_permitidos": ["starter", "core", "plus", "enterprise"],
      "conta_como_fonte": false,
      "versao": 1,
      "frescura": {
        "estado": "ok",
        "dado_de": "2026-10-13T07:30:00Z",
        "ultima_actualizacao": "2026-10-13T07:31:12Z",
        "linhas": 11532,
        "atrasada": false,
        "erro": null
      },
      "clientes_ativos": 2
    }
  ]
}
```

- `frescura` vem de `sky_world.mundo.fontes` (lida com o `world_admin`). `null` se a fonte não tem carregador ou se `frescura_disponivel=false` (base `sky_world` inacessível — mostrar «sem dados de frescura», não erro).
- `frescura.estado`: `ok` · `erro` · `sem_chave` (fonte paga sem chave) · `desconhecido` (o carregador nunca correu). `atrasada = agora − dado_de > 2 × cadencia_min` → mostrar a vermelho.

## 2. Fontes de um cliente

`GET /api/console/v1/tenants/{slug}/fontes-sistema` — qualquer membro da equipa Sky. `404` com `reason: "tenant_not_found"`.

```json
{
  "slug": "sandbox",
  "plano": "starter",
  "frescura_disponivel": true,
  "fontes": [
    {
      "fonte_id": "combustivel_es",
      "nome": {"pt": "…"},
      "tipo": "A",
      "estado_catalogo": "ativa",
      "ativa": true,
      "estado": "pronta",
      "erro": null,
      "permitida_pelo_plano": true,
      "ativavel": true,
      "motivo_nao_ativavel": null,
      "frescura": { "…": "igual ao catálogo" },
      "ativada_por": "lucas.ventura@skyfirstlabs.com",
      "ativada_em": "2026-10-13T08:00:00Z",
      "desativada_por": null,
      "desativada_em": null,
      "pronta_em": "2026-10-13T08:00:41Z",
      "actualizado_em": "2026-10-13T08:00:41Z"
    }
  ]
}
```

Lista todas as fontes do catálogo que não estão `retirada` (mais as retiradas que o cliente ainda tenha). O checkbox fica **desactivado** quando `ativavel=false` e a fonte não está `ativa` no cliente; o tooltip vem de `motivo_nao_ativavel`. Desmarcar é sempre possível.

`GET /api/console/v1/tenants/{slug}/fontes-sistema/{fonte_id}` — o mesmo objecto, só uma fonte (para o poll). `404` com `reason: "fonte_not_found"`.

## 3. Marcar / desmarcar

`PUT /api/console/v1/tenants/{slug}/fontes-sistema/{fonte_id}` — permissão RBAC `system_sources.toggle` (CEO, CTO, DevOps, CSM).

Pedido: `{"ativa": true}` ou `{"ativa": false}`.

| Status | Corpo | Quando |
|---|---|---|
| `202` | `{"fonte_id", "ativa", "estado": "a_preparar"\|"a_desligar"\|"desligada", "job_id": "…"\|null}` | Aceite. Idempotente: repetir o mesmo pedido volta a convergir. Desmarcar uma fonte que nunca esteve activa → `estado: "desligada"`, `job_id: null` |
| `403` | `reason: "permission_denied"`, `required_action: "system_sources.toggle"`, `user_roles: […]` | Sem permissão |
| `404` | `reason: "tenant_not_found"` \| `"fonte_not_found"` \| `"fontes_sistema_desligadas"` | |
| `409` | `reason: "<motivo_nao_ativavel>"`, `fonte_id`, `plano` | Só ao marcar: fonte não activa no catálogo, sem licença comercial, tipo B, ou plano que não a permite |

**Antes de desmarcar** a UI deve pedir confirmação: a partir daí, as perguntas, agentes e widgets do cliente que usam essas tabelas deixam de ter dados (o Postgres recusa no próprio instante). O endpoint de impacto (`GET …/{fonte_id}/impacto`) fica para a fase seguinte.

Auditoria: `enable_system_source` / `disable_system_source` em `internal_console_audit` (sucesso e recusas 409).

## 4. Reconciliar já («refrescar o estado»)

`POST /api/console/v1/tenants/{slug}/fontes-sistema/reconciliar` — permissão `system_sources.toggle`. Corpo vazio.

`202 {"slug": "sandbox", "job_id": "…"}`. Volta a convergir todas as fontes do cliente (GRANT/REVOKE, ligação, projectos, tabelas, discover) e actualiza os estados. A mesma coisa corre sozinha de hora a hora. Auditoria: `reconcile_system_sources`.

## O que o cliente vê (web e app — não é da Consola)

- Uma ligação «Dados públicos» (`connector_id: "sky-world"`, `sistema: true` em `GET /api/v1/connections`) em **todos** os projectos, incluindo os criados depois.
- Mutações dessa ligação (`PUT/DELETE /connections/{id}`, `POST /connections/{id}/test`, `PUT /connections/{id}/metadata`, `POST /permissions/connections/{id}`, `DELETE /spaces/{id}/connections/{id}`) → `403` com `error.details.reason = "ligacao_do_sistema"` e `error.details.messages.{pt,es,en}`. Mostrar cadeado e «Gerida pela Sky». `POST /connections/{id}/sync` continua permitido.
- Criar uma ligação com `connector_id: "sky-world"` → o mesmo `403`.
- Não conta para o limite de fontes do plano (`max_connections`).

## Notas de implementação (backend)

- A tarefa Celery `provisionar_fontes_do_cliente(slug)` converge o cliente inteiro; envia `X-Tenant-Slug` explícito ao sky-ai; escreve o estado só nas linhas cujo `pedido_id` não mudou entretanto (dois operadores ao mesmo tempo convergem, S17).
- A fronteira comercial está no Postgres: `GRANT wsrc_<fonte> TO wt_<slug>` / `REVOKE`. O que não está marcado, o Postgres recusa.
- `rotas_referencia` e `gasolineras_rota` nunca são concedidas a ninguém enquanto os termos da TomTom não estiverem confirmados.

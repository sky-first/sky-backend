# Contrato: dados ao vivo (13/10/2026)

**Para:** web (sky-fe) e app (sky-mobile).
**Decisão do Lucas, 13/10/2026:** a plataforma nunca guarda as linhas do cliente. O «ver a fonte», os widgets e os achados dos agentes voltam a correr o SQL na fonte do cliente quando se abrem.

## 1. O que muda, em resumo

| Onde | Antes | Agora |
|---|---|---|
| `GET /messages/{id}/fonte` | linhas guardadas no momento da resposta | linhas **de agora** (o SQL volta a correr) |
| `GET /messages/{id}/fonte.csv` | CSV das linhas guardadas (até 200) | CSV de agora (até 5000), enviado aos pedaços |
| `widgets.data` (lista, `GET /pages/{id}/widgets`, eventos `widget.*`) | trazia `data`/`rows`/`value` | **só a definição** (SQL, mapeamento, texto gerado), sem linhas |
| `GET /widgets/{id}/data` | devolvia o `widget.data` guardado | volta a correr o SQL e devolve as linhas **de agora** |
| `agent_findings.rows` (web) | `{columns, data}` | `{columns, row_count, sql, connection_id, connection_ids}`, sem `data` |
| `series` dos achados (feed da app) | série guardada | sempre `[]`. A série vem de `GET /insights/{id}/dados` |
| `POST /ai/query` → `data_sample` | igual | **igual**: quem pergunta continua a receber as linhas na resposta. Só deixam de ser gravadas |
| stream (`/ai/chat/stream`) → evento `rows` | igual | **igual** (não se grava) |
| Repetição com `Idempotency-Key` | devolvia o corpo inteiro guardado | devolve `{"id": …, "idempotent_replay": true}` com o mesmo estado HTTP |

Nada é cifrado no cliente e nada muda na autenticação.

## 2. O resultado ao vivo (forma comum)

Todas as leituras ao vivo trazem estas chaves:

```json
{
  "colunas": ["regiao", "total"],
  "linhas": [["Norte", 10], ["Sul", 7]],
  "total_linhas": 2,
  "truncado": false,
  "ao_vivo": true,
  "reexecutavel": true,
  "motivo": null,
  "consultado_em": "2026-10-13T12:00:00+00:00",
  "nota": "dados actuais, consultados agora",
  "total_na_resposta": 4,
  "mudou_desde_a_resposta": true,
  "em_cache": false
}
```

- **`nota`**: mostrar sempre junto da tabela. O resultado de hoje pode não ser o da resposta.
- **`mudou_desde_a_resposta`**: `true`/`false` quando a contagem de linhas permite dizer. `null` quando não se sabe (cortou, ou a resposta é antiga). Com `true`, mostrar um aviso discreto («os dados mudaram desde esta resposta»).
- **`em_cache`**: `true` quando veio da cache curta (até 5 min, por pessoa). Para forçar uma leitura nova num widget, usar `POST /widgets/{id}/refresh`.
- **`reexecutavel: false`**: não há tabela para mostrar. `motivo` diz porquê:
  - `sem_sql`: a resposta não consultou dados (ou é anterior a guardar o contexto);
  - `nao_reexecutavel`: o SQL juntou várias fontes em memória, a tabela saiu do catálogo, ou a fonte não é SQL (API, Mongo);
  - `fonte_indisponivel` / `fonte_recusou` / `prazo`: a base do cliente não respondeu.

  Nestes casos, mostrar a resposta (texto) e as tabelas/SQL sem a grelha. **Não** mostrar dados antigos em cache local.

### Erros

| Estado | Quando | O que mostrar |
|---|---|---|
| **404** | não pode ver a conversa / página / achado (ou não existe) | o mesmo de hoje |
| **403** | vê a conversa, mas **já não tem acesso às tabelas** desta consulta (mudou de equipa, perdeu permissões, ou foi outra equipa que perguntou) | «Já não tens acesso aos dados desta resposta.» e a resposta em texto |

As tabelas autorizadas são sempre as de **quem abre**, no contexto da pergunta (projeto, equipa, modo pessoal), calculadas com a mesma regra do `/ai/query`.

## 3. Endpoints

### 3.1 `GET /api/v1/messages/{message_id}/fonte`

Mantém as chaves antigas (`tabelas`, `sql`, `colunas`, `linhas`, `total_linhas`, `truncado`) e acrescenta as da secção 2. Até 200 linhas (`DADOS_AO_VIVO_LIMITE_VER`).

### 3.2 `GET /api/v1/messages/{message_id}/fonte.csv`

CSV `;` com BOM, até 5000 linhas (`DADOS_AO_VIVO_LIMITE_CSV`), enviado aos pedaços (`StreamingResponse`). Cabeçalhos:
- `X-Sky-Consultado-Em`: quando foi lido;
- `X-Sky-Truncado: 1`: quando cortou.

### 3.3 `GET /api/v1/widgets/{widget_id}/data`

```json
{
  "data": { "...forma de sempre do widget.data, com as linhas de agora..." },
  "last_updated": "2026-10-13T12:00:00+00:00",
  "ao_vivo": true,
  "reexecutavel": true,
  "motivo": null,
  "consultado_em": "2026-10-13T12:00:00+00:00",
  "nota": "dados actuais, consultados agora",
  "truncado": false,
  "em_cache": false
}
```

Dentro de `data`, as linhas ficam onde os componentes já as liam:
- `chart`: `data` = lista de objectos `{coluna: valor}`; `mapping`/`type` como antes;
- `table`: `columns` + `rows` (objectos) e também `data`;
- `kpi`: `value` (primeiro valor numérico da 1.ª linha) + `data`;
- `insight`: `data` e `content.chart_block.data`;
- widget vindo de um achado (`source: "agent_finding"`): `rows = {columns, data}` (listas).

Widgets de texto/forma e os de **demonstração** (`data.demo === true`) devolvem o `data` guardado com `ao_vivo: false`. Sem acesso à página: 404. Sem acesso às tabelas: 403. `POST /widgets/{id}/refresh` faz o mesmo, mas salta a cache.

**Para a web:** ao abrir uma página, a lista de widgets chega sem linhas. Cada widget de dados (`chart`, `kpi`, `table`, `insight`, `infographic`) pede `GET /widgets/{id}/data` e desenha um esqueleto enquanto espera. O `infographic_data` e o `answer` continuam no `widget.data` guardado (é texto gerado pela plataforma).

**Ao criar um widget** (`POST /pages/{id}/widgets`), mandar a definição: `sql`, `question`, `mapping`, `connection_id` e, se veio de uma resposta, `query_id`. O que vier em `data.data`/`rows`/`value` é descartado pelo servidor. A chave `data.demo` também é descartada.

### 3.4 `GET /api/v1/insights/{finding_id}/dados` (novo)

O resultado comum da secção 2, mais:

```json
{ "serie": [{"t": "Jan", "v": 10.0}, {"t": "Fev", "v": 12.5}] }
```

`serie` sai da primeira coluna de rótulo e da primeira numérica, ou `[]`. Visibilidade: a mesma de `GET /insights/{id}` (404 fora do âmbito). O âmbito da reexecução é o do agente: equipa, projeto ou pessoal. Os achados do scan autónomo não têm SQL: `reexecutavel: false`, `motivo: "sem_sql"`, e o cartão usa o número grande e os `stat_tiles`.

`InsightItem.series` passa a vir sempre `[]`. A app pede `/dados` ao abrir o detalhe (ou ao desenhar o gráfico do cartão, se quiser a sparkline).

### 3.5 `Idempotency-Key`

Repetir uma mutação com a mesma chave devolve o mesmo estado HTTP e `{"id": "<id do recurso>", "idempotent_replay": true}` (cabeçalho `X-Idempotency-Cache: HIT`). Quem precisa do recurso completo pede-o pelo id.

## 4. O que os clientes têm de deixar de fazer

- **Não guardar linhas no dispositivo.** Web: `sky:answer-rows-cache:v1`, o `responseData.data_sample` em `chatStorageKey(*)` e o `widget.data` na `widget-storage` persistida passam para memória da sessão. No logout, apagar as três chaves. Mobile: hoje não guarda; manter assim.
- **Não reenviar linhas ao servidor** (por exemplo, «Adicionar à página» a partir da cache do browser). Mandar `query_id`/`sql`/`connection_id`.
- **Não usar o `data` da lista de widgets como fonte de verdade.** Usar sempre `GET /widgets/{id}/data`.

## 5. Notas para quem opera

- Cache: Redis `sky:aovivo:v1:<cliente>:<pessoa>:<hash da consulta>:<limite>`, com TTL `DADOS_AO_VIVO_TTL_SECONDS` (por omissão 120 s, nunca mais de 300 s). Sem Redis, fica na memória do processo com o mesmo prazo.
- Limpeza do que ficou gravado antes de 13/10: `python -I scripts/limpar_linhas_do_cliente.py` só conta, e é seguro de correr. Com `--aplicar`, escreve. **Não correr com `--aplicar` em produção sem a aprovação do Lucas.**
- sky-ai: `POST /connections/{id}/rerun` aceita `sql`, `user_id`, `space_id`, `tabelas_autorizadas` `{ligação: [tabelas]}`, `connection_ids`, `security_config` e `max_rows` (até 10 000). Corre só SELECT, com o mesmo validador AST e o mesmo RLS. Responde 403 `sem_acesso`, 422 `nao_reexecutavel`/`sql_invalido`, ou 502/504 quando a fonte falha. Não grava nada e não gasta o plano.

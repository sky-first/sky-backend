# Dados do cliente: o que o sky-backend guarda e o que não guarda

**Princípio:** nunca guardamos linhas do cliente. O SQL é gerado a partir dos metadados e corre no servidor do cliente. Só guardamos o que a plataforma gera; o que é sensível vai cifrado.

Em vigor desde 13/10/2026. Origem: auditoria de 13/10 (achado B1).

## Metadados das ligações (`connection_metadata.tables`)

**Guardamos:** nomes de schemas, tabelas e colunas, tipos, nulidade, comentários da base (`COMMENT ON`), contagem aproximada de linhas e as edições do utilizador (descrições e tags).

**Não guardamos:** valores das colunas. Até 13/10 o conector Postgres escrevia na descrição de cada coluna de texto com ≤ 20 valores distintos o texto `Possible values: 'a', 'b', …`. Eram valores reais, guardados para sempre e copiados pelo sky-ai para `table_metadata` e para os embeddings. O conector deixou de os ler. Os outros conectores foram revistos e nenhum fazia o mesmo.

Os valores de que as perguntas precisam vêm de uma cache efémera do sky-ai (Redis, 30 min).

O `sync_connection` preserva as descrições guardadas, mas tira-lhes a pista antiga. Ver `src/services/metadados_sem_valores.py`.

## Credenciais

`data_connections.config` é guardado cifrado (`ENCRYPTION_KEY`) e só é decifrado em memória.

## Limpeza do que já estava guardado

`scripts/limpar_valores_das_colunas.py` corre na plataforma e em cada base de cliente, via `tenant_connection_manager`, e é idempotente. Tira a pista das descrições e pede ao sky-ai uma descoberta forçada (`skip_if_recent_seconds=0`) por cada espaço, para que os embeddings sejam refeitos sem os valores.

```
python scripts/limpar_valores_das_colunas.py           # dry-run: só conta
python scripts/limpar_valores_das_colunas.py --apply
```

A seguir, corre-se `scripts/limpar_dados_do_cliente.py --apply` no sky-ai.

Por verificar noutro lote (auditoria, parte 2): `ai_queries`, `messages.metadata`, os snapshots de widgets e demos, os insights, os exports e o `result_expires` do Celery.

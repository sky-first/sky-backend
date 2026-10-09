# -*- coding: utf-8 -*-
"""De onde veio cada resposta: as tabelas, o SQL e as linhas.

── Porque é que isto existe ────────────────────────────────────────

> «Toda resposta é preciso a gente ter ali um botão para a gente
>  entender de onde veio os dados. Quais foram as tabelas usadas, pode
>  ser que a pessoa queira exportar a tabela também… A pessoa cruzar a
>  informação e ver se isso bate realmente. Isso é importantíssimo.»
> — Lucas, 09/10/2026

Uma resposta com números que não se podem confirmar é uma opinião. Num
produto que vende respostas sobre os dados de uma empresa, isso é o
produto todo.

── Nada aqui foi inventado ─────────────────────────────────────────

Tudo isto já existia e não estava ligado:

* o motor (`sky-ai`) já emitia as tabelas e o SQL no `meta`, e o
  resultado inteiro (até 200 linhas) num evento `rows`;
* a tabela `ai_queries` já tinha colunas para a pergunta, o SQL e as
  linhas, e a `messages.query_id` já apontava para ela;
* o portão do stream deitava o `rows` fora, e o chat nunca preenchia a
  `ai_queries`.

── Porque NÃO se reexecuta o SQL ───────────────────────────────────

Para exportar tudo, a tentação era guardar o SQL e corrê-lo outra vez
quando se pede o CSV. Não se faz, de propósito:

* correr SQL guardado é abrir uma segunda porta para os dados, que teria
  de repetir TODAS as verificações de acesso da primeira — e repetir uma
  regra em dois sítios é como ela se perde (já aconteceu cinco vezes
  neste produto);
* o resultado de amanhã não é o de hoje. A pessoa quer confirmar a
  resposta que LEU, não uma consulta nova.

Guarda-se o resultado do momento, tal como o motor o devolveu. O teto é
o do motor — 200 linhas — e quando ele cortou, a fonte di-lo.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _tabelas(meta: Dict[str, Any]) -> List[str]:
    """As tabelas consultadas, venham elas como lista ou como uma só."""
    lista = meta.get("chosen_datasets")
    if isinstance(lista, list) and lista:
        return [str(t) for t in lista if t]
    uma = meta.get("chosen_table")
    return [str(uma)] if uma else []


def tem_fonte(meta: Dict[str, Any], linhas: Dict[str, Any]) -> bool:
    """Há alguma coisa para mostrar?

    Uma resposta que não consultou nada (uma saudação, um «não sei») não
    tem fonte — e mostrar um botão vazio era pior do que não o mostrar.
    """
    return bool(meta.get("sql") or _tabelas(meta) or (linhas or {}).get("rows"))


async def _guardar_a_fonte(
    db: AsyncSession,
    *,
    utilizador: Any,
    mensagem: Any,
    pergunta: str,
    resposta: str,
    meta: Dict[str, Any],
    linhas: Dict[str, Any],
    page_id: Optional[UUID],
) -> Optional[UUID]:
    """Guarda a fonte da resposta e liga-a à mensagem. Devolve o id, ou None.

    Não faz commit: corre dentro da transacção de quem guarda a resposta,
    para as duas coisas ficarem juntas ou nenhuma.
    """
    if not tem_fonte(meta, linhas) or page_id is None:
        return None

    from src.models.ai import AIQuery

    consulta = AIQuery(
        user_id=utilizador.id,
        page_id=page_id,
        question=pergunta,
        answer=resposta,
        sql=meta.get("sql"),
        # As linhas como o motor as mandou: colunas à parte, linhas como
        # listas. É mais compacto do que repetir os nomes em cada linha, e
        # é a forma que o CSV precisa.
        data_sample=(linhas or {}).get("rows") or [],
        status="completed",
        configure_data={
            "fonte": {
                "tabelas": _tabelas(meta),
                "colunas": (linhas or {}).get("columns") or [],
                "total_linhas": meta.get("num_rows"),
                "truncado": bool((linhas or {}).get("truncated")),
            }
        },
    )
    db.add(consulta)
    await db.flush()
    mensagem.query_id = consulta.id
    return consulta.id


def fonte_para_mostrar(consulta: Any) -> Dict[str, Any]:
    """A fonte no formato que os clientes desenham."""
    fonte = ((consulta.configure_data or {}).get("fonte")) or {}
    linhas = consulta.data_sample or []
    return {
        "tabelas": fonte.get("tabelas") or [],
        "sql": consulta.sql,
        "colunas": fonte.get("colunas") or [],
        "linhas": linhas,
        # O total do motor, quando o deu; senão, o que temos. Os dois
        # diferem quando o motor cortou — e é isso que o `truncado` diz.
        "total_linhas": fonte.get("total_linhas") or len(linhas),
        "truncado": bool(fonte.get("truncado")),
    }


def fonte_em_csv(consulta: Any) -> str:
    """As linhas da fonte em CSV, prontas a abrir numa folha de cálculo.

    **Separador `;`** e não `,`: em Portugal e Espanha o Excel usa a vírgula
    como separador decimal, e um CSV com vírgulas abre tudo numa coluna.
    É o detalhe que decide se a pessoa consegue mesmo «cruzar a
    informação» ou desiste no primeiro clique.
    """
    f = fonte_para_mostrar(consulta)
    saida = io.StringIO()
    # BOM no início: sem ele o Excel lê UTF-8 como Latin-1 e os acentos
    # saem estragados — «Restauración» vira «RestauraciÃ³n».
    saida.write("﻿")
    w = csv.writer(saida, delimiter=";")
    if f["colunas"]:
        w.writerow(f["colunas"])
    for linha in f["linhas"]:
        w.writerow(
            ["" if v is None else v for v in (linha if isinstance(linha, list) else [linha])]
        )
    return saida.getvalue()

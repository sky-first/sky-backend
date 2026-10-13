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

── O que mudou a 13/10/2026: volta-se a correr o SQL ───────────────

> «Nunca guardamos as linhas do cliente. O ver a fonte, os widgets e os
>  achados voltam a correr o SQL contra a fonte do cliente quando se
>  abrem.» — Lucas, 13/10/2026

Até aqui guardava-se o resultado do momento (até 200 linhas por resposta,
em `ai_queries.data_sample`, para sempre). Era o maior volume de linhas do
cliente na plataforma, e a razão de a frase «não copiamos os seus dados»
não ser verdade.

Guarda-se agora a DEFINIÇÃO: a pergunta, a resposta, o SQL, as tabelas,
as colunas, quantas linhas havia — e o contexto em que a pergunta foi
feita (ligação, projeto, equipa, modo pessoal). Ao abrir a fonte, o SQL
volta a correr no sky-ai, só de leitura, **com as tabelas de quem abre**
(`services/dados_ao_vivo`). Quem perdeu o acesso leva 403.

Os dois argumentos de antes contra reexecutar continuam certos, e cada um
tem resposta:

* «uma segunda porta para os dados» — não é segunda: usa o mesmo
  validador, as mesmas tabelas autorizadas (`get_authorized_tables`) e o
  mesmo RLS da pergunta, calculados num sítio só;
* «o resultado de amanhã não é o de hoje» — por isso a fonte diz
  «dados actuais, consultados agora», a hora, e se a contagem mudou desde
  a resposta.
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
    contexto: Optional[Dict[str, Any]] = None,
) -> Optional[UUID]:
    """Guarda a DEFINIÇÃO da fonte e liga-a à mensagem. Devolve o id, ou None.

    **Nunca as linhas.** Das linhas que o motor mandou fica só o que as
    descreve: as colunas, quantas eram, se o motor cortou.

    `contexto` é onde a pergunta foi feita — `connection_id`,
    `connection_ids`, `space_id`, `crew_id`, `is_personal` — e é o que
    permite voltar a correr o SQL com as regras certas.

    Não faz commit: corre dentro da transacção de quem guarda a resposta,
    para as duas coisas ficarem juntas ou nenhuma.
    """
    if not tem_fonte(meta, linhas) or page_id is None:
        return None

    from src.models.ai import AIQuery

    linhas = linhas or {}
    total = meta.get("num_rows")
    consulta = AIQuery(
        user_id=utilizador.id,
        page_id=page_id,
        question=pergunta,
        answer=resposta,
        sql=meta.get("sql"),
        status="completed",
        configure_data={
            "fonte": {
                "tabelas": _tabelas(meta),
                "colunas": linhas.get("columns") or [],
                "total_linhas": total if total is not None else len(linhas.get("rows") or []),
                "truncado": bool(linhas.get("truncated")),
                **contexto_limpo(contexto),
            }
        },
    )
    db.add(consulta)
    await db.flush()
    mensagem.query_id = consulta.id
    return consulta.id


def contexto_limpo(contexto: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Só as chaves do contexto, como texto — é JSON e vai para a base."""
    c = contexto or {}
    saida: Dict[str, Any] = {}
    if c.get("connection_id"):
        saida["connection_id"] = str(c["connection_id"])
    ids = [str(x) for x in (c.get("connection_ids") or []) if x]
    if ids:
        saida["connection_ids"] = ids
    for chave in ("space_id", "crew_id"):
        if c.get(chave):
            saida[chave] = str(c[chave])
    saida["is_personal"] = bool(c.get("is_personal"))
    return saida


def consulta_guardada(consulta: Any):
    """A `ConsultaGuardada` para voltar a correr, ou None se não há como.

    Lê as duas formas: a do stream (`configure_data.fonte`) e a do
    `/ai/query` (que também passa a escrever `fonte`; as consultas antigas
    da web só têm `knowledge` com o id da ligação).
    """
    from src.services.dados_ao_vivo import ConsultaGuardada

    config = consulta.configure_data or {}
    fonte = config.get("fonte") or {}
    ligacao = fonte.get("connection_id")
    if not ligacao:
        for item in config.get("knowledge") or []:
            if isinstance(item, str) and len(item) == 36 and item.count("-") == 4:
                ligacao = item
                break
    if not consulta.sql or not ligacao:
        return None
    total = fonte.get("total_linhas")
    return ConsultaGuardada(
        sql=consulta.sql,
        connection_id=str(ligacao),
        connection_ids=[str(x) for x in (fonte.get("connection_ids") or [])],
        space_id=fonte.get("space_id") or config.get("space_id"),
        crew_id=fonte.get("crew_id") or config.get("crew_id"),
        is_personal=bool(fonte.get("is_personal", config.get("is_personal", False))),
        total_na_resposta=int(total) if isinstance(total, (int, float)) else None,
    )


def definicao_da_fonte(consulta: Any) -> Dict[str, Any]:
    """O que está guardado: tabelas, SQL, colunas. Sem linhas."""
    config = consulta.configure_data or {}
    fonte = config.get("fonte") or {}
    return {
        "tabelas": fonte.get("tabelas") or _tabelas(config),
        "sql": consulta.sql,
        "colunas": list(fonte.get("colunas") or []),
        "total_linhas": fonte.get("total_linhas"),
        "truncado": bool(fonte.get("truncado")),
    }


def tem_o_que_mostrar(consulta: Any) -> bool:
    """Uma consulta sem tabelas e sem SQL (uma saudacao, um «nao sei») nao
    tem fonte. O /ai/query cria a linha em ``ai_queries`` para TODAS as
    perguntas; sem isto, o botao abria um painel vazio."""
    f = definicao_da_fonte(consulta)
    return bool(f["tabelas"] or f["sql"])


async def fonte_ao_vivo(db: Any, utilizador: Any, consulta: Any, *, limite: int) -> Dict[str, Any]:
    """A fonte no formato que os clientes desenham — com as linhas de AGORA.

    As chaves de sempre (`tabelas`, `sql`, `colunas`, `linhas`,
    `total_linhas`, `truncado`) e as novas do contrato de 13/10
    (`ao_vivo`, `consultado_em`, `nota`, `reexecutavel`, `motivo`,
    `mudou_desde_a_resposta`). Sem acesso → 403 (`ForbiddenError`).
    """
    from src.services.dados_ao_vivo import ConsultaGuardada, _sem_tabela, reexecutar

    base = definicao_da_fonte(consulta)
    guardada = consulta_guardada(consulta)
    if guardada is None:
        vivo = _sem_tabela("sem_sql", ConsultaGuardada(sql="", connection_id=""))
    else:
        vivo = await reexecutar(db, utilizador, guardada, limite=limite)
    return {
        "tabelas": base["tabelas"],
        "sql": base["sql"],
        "colunas": vivo.get("colunas") or base["colunas"],
        "linhas": vivo.get("linhas") or [],
        "total_linhas": vivo.get("total_linhas") if vivo.get("ao_vivo") else base["total_linhas"],
        "truncado": bool(vivo.get("truncado")),
        "ao_vivo": bool(vivo.get("ao_vivo")),
        "reexecutavel": bool(vivo.get("reexecutavel")),
        "motivo": vivo.get("motivo"),
        "consultado_em": vivo.get("consultado_em"),
        "nota": vivo.get("nota"),
        "total_na_resposta": base["total_linhas"],
        "mudou_desde_a_resposta": vivo.get("mudou_desde_a_resposta"),
    }


def fonte_em_csv(f: Dict[str, Any]) -> str:
    """As linhas da fonte em CSV, prontas a abrir numa folha de cálculo.

    **Separador `;`** e não `,`: em Portugal e Espanha o Excel usa a vírgula
    como separador decimal, e um CSV com vírgulas abre tudo numa coluna.
    É o detalhe que decide se a pessoa consegue mesmo «cruzar a
    informação» ou desiste no primeiro clique.
    """
    return "".join(csv_em_pedacos(f))


def csv_em_pedacos(f: Dict[str, Any], *, por_pedaco: int = 500):
    """O mesmo CSV, aos pedaços — para o `StreamingResponse` não montar o
    ficheiro inteiro de uma vez."""
    saida = io.StringIO()
    # BOM no início: sem ele o Excel lê UTF-8 como Latin-1 e os acentos
    # saem estragados — «Restauración» vira «RestauraciÃ³n».
    saida.write("﻿")
    w = csv.writer(saida, delimiter=";")
    if f.get("colunas"):
        w.writerow(f["colunas"])
    for i, linha in enumerate(f.get("linhas") or [], start=1):
        w.writerow(
            ["" if v is None else v for v in (linha if isinstance(linha, list) else [linha])]
        )
        if i % por_pedaco == 0:
            yield saida.getvalue()
            saida.seek(0)
            saida.truncate(0)
    resto = saida.getvalue()
    if resto:
        yield resto

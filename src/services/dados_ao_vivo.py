# -*- coding: utf-8 -*-
"""Nunca guardamos as linhas do cliente. Voltamos a correr o SQL.

── A decisão ───────────────────────────────────────────────────────

> «Nunca guardamos as linhas do cliente. O ver a fonte, os widgets e os
>  achados voltam a correr o SQL contra a fonte do cliente quando se
>  abrem.» — Lucas, 13/10/2026

A auditoria de 13/10 encontrou linhas do cliente guardadas de propósito em
quatro sítios permanentes: `ai_queries.data_sample` (até 200 por
resposta), `widgets.data`, `agent_findings.rows/series` e
`agent_executions.result_payload` (100 por corrida, uma corrida por
minuto). A frase comercial — «não copiamos os seus dados» — era falsa por
desenho.

── O que se guarda agora ───────────────────────────────────────────

A DEFINIÇÃO: o SQL, a ligação (e as outras do âmbito), o contexto da
pergunta (projeto, equipa, modo pessoal), as colunas e quantas linhas
havia. Texto gerado pela plataforma — a resposta, o título, o resumo do
cartão — continua a ser guardado: é nosso, não é uma cópia da base dele.

As linhas pedem-se quando alguém abre, a `POST /connections/{id}/rerun`
no sky-ai, **com as tabelas de quem abre** — não com as de quem
perguntou. Quem perdeu o acesso desde então leva 403.

── Duas guardas, de propósito ──────────────────────────────────────

1. **Na escrita**, nos próprios modelos (`@validates`): seja qual for o
   caminho que grava — o worker, o FE, um script — as chaves com linhas
   saem antes de chegar à base. Uma regra no sítio onde se grava não se
   esquece no sétimo caminho que alguém acrescentar.
2. **Na leitura**, aqui: o resultado vem do sky-ai e vai para quem
   pediu. A cache curta (≤ 5 min, por pessoa) é só para não martelar a
   base do cliente quando uma página com doze widgets abre.

Os dados de DEMONSTRAÇÃO são nossos (sintéticos, numa base nossa) e
ficam: marcam-se com ``"demo": true`` pelos semeadores. A API apaga essa
marca do que chega do cliente, para ninguém a usar como porta.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from src.utils.log_redaction import texto_para_log

logger = logging.getLogger(__name__)

#: A nota que acompanha qualquer tabela reexecutada. O resultado de hoje
#: pode não ser o da resposta — e a pessoa tem de saber qual está a ver.
NOTA_AO_VIVO = "dados actuais, consultados agora"

#: Chaves que, num widget, levam LINHAS (listas de valores do cliente).
CHAVES_DE_LINHAS = ("data", "data_sample", "series", "chart_data", "points", "values")

#: O que um achado pode guardar no seu `rows`: a definição, nunca os dados.
CHAVES_DA_DEFINICAO = (
    "columns",
    "row_count",
    "truncated",
    "sql",
    "connection_id",
    "connection_ids",
)

#: O que uma corrida de agente pode guardar: números sobre o resultado, para
#: as métricas e o delta. Nenhuma linha.
CHAVES_DA_EXECUCAO = ("row_count", "columns", "schema", "data_bytes")

#: Widgets que desenham dados. Os outros (texto, forma) não têm nada para
#: voltar a correr.
TIPOS_COM_DADOS = {"chart", "kpi", "table", "insight", "infographic"}


# ─── Guarda na escrita ───────────────────────────────────────────────


def e_demo(valor: Any) -> bool:
    """Dados sintéticos nossos, marcados pelos semeadores."""
    return isinstance(valor, dict) and valor.get("demo") is True


def _rows_sem_dados(rows: Any) -> Any:
    """`{columns, data}` → `{columns, row_count}`. Uma lista de linhas → nada."""
    if isinstance(rows, dict):
        if e_demo(rows):
            return rows
        saida = {k: rows[k] for k in CHAVES_DA_DEFINICAO if k in rows}
        if "row_count" not in saida and isinstance(rows.get("data"), list):
            saida["row_count"] = len(rows["data"])
        return saida or None
    if isinstance(rows, list):
        return None
    return rows


def widget_sem_linhas(tipo: Optional[str], data: Any) -> Any:
    """O `widgets.data` sem as linhas do cliente.

    Fica a definição (pergunta, SQL, mapeamento, configuração) e o texto
    gerado (`answer`, `infographic_data`). Saem as listas de linhas, o
    `value` do KPI e o `chart_block.data` dos cartões de insight.
    """
    if not isinstance(data, dict) or e_demo(data):
        return data
    saida = dict(data)
    for chave in CHAVES_DE_LINHAS:
        if isinstance(saida.get(chave), list):
            saida.pop(chave)
    if "rows" in saida:
        saida["rows"] = _rows_sem_dados(saida["rows"])
        if saida["rows"] is None:
            saida.pop("rows")
    if (tipo or "").lower() == "kpi":
        saida.pop("value", None)
    conteudo = saida.get("content")
    if isinstance(conteudo, dict) and isinstance(conteudo.get("chart_block"), dict):
        bloco = {k: v for k, v in conteudo["chart_block"].items() if k != "data"}
        saida["content"] = {**conteudo, "chart_block": bloco}
    return saida


def achado_rows_sem_dados(rows: Any) -> Any:
    """O `agent_findings.rows` só com a definição (SQL, ligação, colunas)."""
    return _rows_sem_dados(rows)


def achado_series_sem_dados(series: Any) -> Any:
    """A série de um achado é uma lista de valores do cliente: não se guarda."""
    if series is None:
        return None
    return []


def execucao_sem_linhas(payload: Any) -> Any:
    """O `agent_executions.result_payload` só com números sobre o resultado."""
    if not isinstance(payload, dict):
        return None
    saida = {k: payload[k] for k in CHAVES_DA_EXECUCAO if k in payload}
    if "row_count" not in saida:
        for chave in ("rows", "data", "data_sample"):
            if isinstance(payload.get(chave), list):
                saida["row_count"] = len(payload[chave])
                break
    return saida


def sem_marca_de_demo(data: Any) -> Any:
    """O que chega da API não pode dizer-se «demo»: era uma porta."""
    if isinstance(data, dict) and "demo" in data:
        return {k: v for k, v in data.items() if k != "demo"}
    return data


# ─── A consulta guardada ─────────────────────────────────────────────


@dataclass
class ConsultaGuardada:
    """Tudo o que é preciso para voltar a correr — e nada do resultado."""

    sql: str
    connection_id: str
    connection_ids: List[str] = field(default_factory=list)
    space_id: Optional[str] = None
    crew_id: Optional[str] = None
    is_personal: bool = False
    #: Quantas linhas havia quando a resposta foi dada (para dizer se mudou).
    total_na_resposta: Optional[int] = None

    def chave(self) -> str:
        bruto = json.dumps(
            [
                self.sql,
                self.connection_id,
                sorted(self.connection_ids),
                self.space_id,
                self.crew_id,
                self.is_personal,
            ],
            sort_keys=True,
        )
        return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def _erro_sem_acesso():
    from src.core.exceptions import ForbiddenError

    class SemAcessoAosDados(ForbiddenError):
        REASON = "sem_acesso_aos_dados"

        def __init__(self):
            super().__init__("Sem acesso aos dados desta consulta")
            self.details = {
                "reason": self.REASON,
                "messages": {
                    "pt": "Já não tem acesso aos dados desta consulta.",
                    "es": "Ya no tiene acceso a los datos de esta consulta.",
                    "en": "You no longer have access to the data behind this.",
                },
            }

    return SemAcessoAosDados()


class NaoReexecutavel(Exception):
    """O SQL não se pode voltar a correr (junção em memória, fonte não-SQL…)."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


# ─── Cache curta, por pessoa ─────────────────────────────────────────

_MEMORIA: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_MEMORIA_MAX = 256


def _ttl() -> int:
    from src.config.settings import settings

    return max(0, min(int(getattr(settings, "DADOS_AO_VIVO_TTL_SECONDS", 120) or 0), 300))


def _chave_da_cache(utilizador_id: Any, consulta: ConsultaGuardada, limite: int) -> str:
    try:
        from src.core.tenant_context import current_tenant

        ctx = current_tenant()
        cliente = getattr(ctx, "slug", None) or "-"
    except Exception:  # pragma: no cover
        cliente = "-"
    return f"sky:aovivo:v1:{cliente}:{utilizador_id}:{consulta.chave()}:{limite}"


async def _cache_ler(chave: str) -> Optional[Dict[str, Any]]:
    agora = time.monotonic()
    em_memoria = _MEMORIA.get(chave)
    if em_memoria and em_memoria[0] > agora:
        return em_memoria[1]
    try:
        from src.config.redis import get_redis

        redis = await get_redis()
        if redis is not None:
            bruto = await redis.get(chave)
            if bruto:
                return json.loads(bruto)
    except Exception as exc:  # noqa: BLE001 — a cache nunca parte a leitura
        logger.debug("dados_ao_vivo: cache redis indisponível: %s", exc)
    return None


async def _cache_gravar(chave: str, valor: Dict[str, Any]) -> None:
    ttl = _ttl()
    if ttl <= 0:
        return
    try:
        from src.config.redis import get_redis

        redis = await get_redis()
        if redis is not None:
            await redis.setex(chave, ttl, json.dumps(valor, default=str))
            return
    except Exception as exc:  # noqa: BLE001
        logger.debug("dados_ao_vivo: cache redis indisponível: %s", exc)
    # Sem Redis: na memória do processo, com o mesmo prazo.
    if len(_MEMORIA) >= _MEMORIA_MAX:
        agora = time.monotonic()
        for k in [k for k, (exp, _) in _MEMORIA.items() if exp <= agora] or list(_MEMORIA)[:32]:
            _MEMORIA.pop(k, None)
    _MEMORIA[chave] = (time.monotonic() + ttl, valor)


def limpar_cache_em_memoria() -> None:
    """Para os testes."""
    _MEMORIA.clear()


# ─── As tabelas de QUEM ABRE ─────────────────────────────────────────


async def tabelas_de_quem_abre(
    db: Any, utilizador_id: UUID, consulta: ConsultaGuardada
) -> Dict[str, List[str]]:
    """As tabelas que esta pessoa pode ver, por ligação, no contexto da consulta.

    **A mesma regra do `/ai/query`** (`AIService.process_query`), aplicada a
    quem ABRE e não a quem perguntou: as equipas dela no projeto (ou todas,
    em modo pessoal), o projeto só se for membro a sério, e o
    `get_authorized_tables` por cima. Qualquer falha dá lista vazia —
    fail-closed.
    """
    from src.services.ai_service import AIService

    ai = AIService(db)
    space_id = consulta.space_id
    if consulta.is_personal:
        equipas = await ai._get_user_crew_ids(utilizador_id, None, all_spaces=True)
        espaco_perm: Optional[UUID] = None
    else:
        equipas_no_projeto = (
            await ai._get_user_crew_ids(utilizador_id, space_id) if space_id else []
        )
        if consulta.crew_id and str(consulta.crew_id) in equipas_no_projeto:
            equipas = [str(consulta.crew_id)]
        else:
            # Como o stream: quem não está na equipa da pergunta vê com as
            # SUAS equipas do projeto. Se nenhuma dá a tabela, é 403.
            equipas = equipas_no_projeto
        espaco_perm = None
        if space_id and await ai._is_space_member(utilizador_id, space_id):
            try:
                espaco_perm = UUID(str(space_id))
            except (ValueError, TypeError):
                espaco_perm = None

    crew_uuids: Optional[List[UUID]] = None
    if equipas:
        crew_uuids = []
        for c in equipas:
            try:
                crew_uuids.append(UUID(str(c)))
            except (ValueError, TypeError):
                continue

    saida: Dict[str, List[str]] = {}
    for cid in [consulta.connection_id] + [
        c for c in consulta.connection_ids if c and c != consulta.connection_id
    ]:
        try:
            saida[str(cid)] = list(
                await ai.permission_service.get_authorized_tables(
                    user_id=utilizador_id,
                    connection_id=UUID(str(cid)),
                    space_id=espaco_perm,
                    crew_ids=crew_uuids,
                    is_personal=consulta.is_personal,
                )
                or []
            )
        except Exception as exc:  # noqa: BLE001 — fail-closed
            logger.warning(
                "dados_ao_vivo: tabelas autorizadas falharam (%s): %s", cid, texto_para_log(exc)
            )
            saida[str(cid)] = []
    return saida


# ─── Voltar a correr ─────────────────────────────────────────────────


async def reexecutar(
    db: Any,
    utilizador: Any,
    consulta: ConsultaGuardada,
    *,
    limite: Optional[int] = None,
    sem_cache: bool = False,
) -> Dict[str, Any]:
    """As linhas de AGORA para esta consulta, vistas por esta pessoa.

    Devolve sempre um dicionário no formato do contrato
    (`docs/contrato-dados-ao-vivo-2026-10.md`). Sem acesso → `ForbiddenError`
    (403). Não se pode voltar a correr → `reexecutavel: false` e o motivo.
    """
    from src.config.settings import settings

    limite = int(limite or getattr(settings, "DADOS_AO_VIVO_LIMITE_VER", 200) or 200)

    if not (consulta.sql or "").strip() or not consulta.connection_id:
        return _sem_tabela("sem_sql", consulta)

    chave = _chave_da_cache(utilizador.id, consulta, limite)
    em_cache = None if sem_cache else await _cache_ler(chave)
    if em_cache is not None:
        return {**em_cache, "em_cache": True}

    autorizadas = await tabelas_de_quem_abre(db, utilizador.id, consulta)
    if not any(autorizadas.values()):
        raise _erro_sem_acesso()

    seguranca = None
    try:
        from src.services.security_config_builder import build_security_config

        seguranca = await build_security_config(
            db=db, user_id=utilizador.id, connection_id=UUID(str(consulta.connection_id))
        )
    except Exception as exc:  # noqa: BLE001 — como no /ai/query
        logger.warning("dados_ao_vivo: security_config falhou: %s", texto_para_log(exc))

    from src.ai.http_client import AIServiceHTTPClient

    try:
        r = await AIServiceHTTPClient().reexecutar_sql(
            consulta.connection_id,
            sql=consulta.sql,
            user_id=str(utilizador.id),
            space_id=consulta.space_id,
            tabelas_autorizadas=autorizadas,
            connection_ids=[c for c in consulta.connection_ids if c != consulta.connection_id]
            or None,
            security_config=seguranca,
            max_rows=limite,
        )
    except ReexecucaoRecusada as recusa:
        if recusa.status == 403:
            raise _erro_sem_acesso()
        return _sem_tabela(recusa.codigo or "nao_reexecutavel", consulta)

    linhas = r.get("rows") or []
    total = int(r.get("row_count") or len(linhas))
    resultado = {
        "colunas": list(r.get("columns") or []),
        "linhas": linhas,
        "total_linhas": total,
        "truncado": bool(r.get("truncated")),
        "ao_vivo": True,
        "reexecutavel": True,
        "motivo": None,
        "consultado_em": r.get("executed_at") or datetime.now(timezone.utc).isoformat(),
        "nota": NOTA_AO_VIVO,
        "total_na_resposta": consulta.total_na_resposta,
        "mudou_desde_a_resposta": _mudou(
            consulta.total_na_resposta, total, bool(r.get("truncated"))
        ),
        "em_cache": False,
    }
    await _cache_gravar(chave, resultado)
    return resultado


def _mudou(antes: Optional[int], agora: int, cortou: bool) -> Optional[bool]:
    """Só se sabe com certeza quando a contagem difere e nada foi cortado."""
    if antes is None or cortou:
        return None
    return int(antes) != int(agora)


def _sem_tabela(motivo: str, consulta: ConsultaGuardada) -> Dict[str, Any]:
    return {
        "colunas": [],
        "linhas": [],
        "total_linhas": 0,
        "truncado": False,
        "ao_vivo": False,
        "reexecutavel": False,
        "motivo": motivo,
        "consultado_em": None,
        "nota": None,
        "total_na_resposta": consulta.total_na_resposta,
        "mudou_desde_a_resposta": None,
        "em_cache": False,
    }


class ReexecucaoRecusada(Exception):
    """O sky-ai recusou: 403 (sem acesso) ou 4xx/5xx (não dá)."""

    def __init__(self, status: int, codigo: Optional[str] = None):
        super().__init__(f"{status} {codigo or ''}")
        self.status = status
        self.codigo = codigo


# ─── Para os widgets: pôr as linhas onde o cliente as lê ──────────────


def linhas_em_objectos(colunas: List[str], linhas: List[List[Any]]) -> List[Dict[str, Any]]:
    return [dict(zip(colunas, linha)) for linha in linhas]


def hidratar_widget(
    tipo: Optional[str], data: Dict[str, Any], vivo: Dict[str, Any]
) -> Dict[str, Any]:
    """O `widget.data` como o cliente sempre o leu, com as linhas de agora.

    Nada disto se grava: é a resposta do `GET /widgets/{id}/data`.
    """
    saida = dict(data or {})
    colunas, linhas = vivo.get("colunas") or [], vivo.get("linhas") or []
    objectos = linhas_em_objectos(colunas, linhas)
    t = (tipo or "").lower()
    if saida.get("source") == "agent_finding" or isinstance(saida.get("rows"), dict):
        saida["rows"] = {**(saida.get("rows") or {}), "columns": colunas, "data": linhas}
    if t == "table":
        saida["columns"] = colunas
        saida["rows"] = objectos
        saida["data"] = objectos
    elif t == "kpi":
        saida["data"] = objectos
        if objectos and colunas:
            saida["value"] = (
                objectos[0].get(colunas[0])
                if len(colunas) == 1
                else next(
                    (v for v in objectos[0].values() if isinstance(v, (int, float))),
                    objectos[0].get(colunas[0]),
                )
            )
    elif t == "insight":
        saida["data"] = objectos
        conteudo = saida.get("content")
        if isinstance(conteudo, dict) and isinstance(conteudo.get("chart_block"), dict):
            saida["content"] = {
                **conteudo,
                "chart_block": {**conteudo["chart_block"], "data": objectos},
            }
    else:
        saida["data"] = objectos
    return saida


# ─── Para os achados ─────────────────────────────────────────────────


async def consulta_do_achado(db: Any, achado: Any, agente: Any) -> Optional[ConsultaGuardada]:
    """A consulta guardada no `rows` do achado, no âmbito do agente.

    Equipa → as tabelas da equipa no projeto dela; projeto → as do projeto;
    pessoal → o modo pessoal de quem abre (que, para um agente pessoal, só
    o dono vê).
    """
    rows = achado.rows if isinstance(getattr(achado, "rows", None), dict) else {}
    sql = rows.get("sql")
    ligacao = rows.get("connection_id") or getattr(achado, "connection_id", None)
    if not sql or not ligacao:
        return None
    space_id: Optional[str] = None
    crew_id: Optional[str] = None
    pessoal = False
    ambito = (getattr(agente, "scope", None) or "").lower() if agente is not None else ""
    if ambito == "crew" and getattr(agente, "scope_id", None):
        from src.services.agent_service import resolve_metadata_space_id

        crew_id = str(agente.scope_id)
        space_id = await resolve_metadata_space_id(db, agente, str(ligacao))
    elif ambito == "space" and getattr(agente, "scope_id", None):
        space_id = str(agente.scope_id)
    elif agente is None and getattr(achado, "space_id", None):
        space_id = str(achado.space_id)
    else:
        pessoal = True
    total = rows.get("row_count")
    return ConsultaGuardada(
        sql=sql,
        connection_id=str(ligacao),
        connection_ids=[str(c) for c in (rows.get("connection_ids") or [])],
        space_id=space_id,
        crew_id=crew_id,
        is_personal=pessoal,
        total_na_resposta=int(total) if isinstance(total, (int, float)) else None,
    )


def serie_das_linhas(colunas: List[str], linhas: List[List[Any]]) -> List[Dict[str, Any]]:
    """`[{t, v}]` — a primeira coluna de rótulo e a primeira numérica, se há."""
    if not colunas or not linhas:
        return []

    def _numerica(i: int) -> bool:
        return any(
            isinstance(l[i], (int, float)) and not isinstance(l[i], bool)
            for l in linhas
            if len(l) > i
        )

    num = next((i for i in range(len(colunas)) if _numerica(i)), None)
    rot = next((i for i in range(len(colunas)) if i != num), None)
    if num is None or rot is None:
        return []
    return [
        {"t": str(l[rot]), "v": float(l[num])}
        for l in linhas
        if len(l) > max(num, rot) and isinstance(l[num], (int, float))
    ]


async def dados_do_achado(db: Any, utilizador: Any, achado: Any, agente: Any) -> Dict[str, Any]:
    """As linhas de agora de um achado (e a série para o cartão)."""
    consulta = await consulta_do_achado(db, achado, agente)
    if consulta is None:
        vivo = _sem_tabela("sem_sql", ConsultaGuardada(sql="", connection_id=""))
    else:
        vivo = await reexecutar(db, utilizador, consulta)
    return {**vivo, "serie": serie_das_linhas(vivo.get("colunas") or [], vivo.get("linhas") or [])}
